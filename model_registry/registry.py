"""Versioned model registry persistence, verification, promotion, and rollback."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().with_name("registry.json")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from capability_manifests.Schema import DETECTOR_MANIFEST_SCHEMA  # noqa: E402
from debate.calibration import CalibratorRegistry  # noqa: E402
from model_registry.schema import (  # noqa: E402
    RegistryValidationError,
    validate_entry_data,
    validate_registry_data,
)
from security.supply_chain.model_integrity import (  # noqa: E402
    ModelIntegrityError,
    compute_sha256,
    load_weights_manifest,
    verify_file_sha256,
)

_MANIFEST_SNAPSHOT_KEYS = (
    "version",
    "description",
    "performance",
    "calibration",
    "model_metadata",
    "registry_entry_id",
)


class RegistryError(RuntimeError):
    """Base error for model registry operations."""


class PromotionBlockedError(RegistryError):
    """Raised when attempting to promote an entry that has not passed the gate."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.stem}_", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _snapshot_manifest_fields(manifest: Dict[str, Any]) -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    for key in _MANIFEST_SNAPSHOT_KEYS:
        if key in manifest:
            snap[key] = copy.deepcopy(manifest[key])
        else:
            snap[key] = "__ABSENT__"
    return snap


def _restore_manifest_fields(
    live_manifest: Dict[str, Any], snapshot: Dict[str, Any]
) -> Dict[str, Any]:
    restored = copy.deepcopy(live_manifest)
    for key in _MANIFEST_SNAPSHOT_KEYS:
        if key not in snapshot:
            continue
        val = snapshot[key]
        if val == "__ABSENT__":
            restored.pop(key, None)
        else:
            restored[key] = copy.deepcopy(val)
    return restored


class ModelRegistry:
    """Manages versioned detector checkpoints, calibration links, and rollbacks."""

    def __init__(
        self,
        registry_path: Optional[Path] = None,
        repo_root: Optional[Path] = None,
        weights_manifest_path: Optional[Path] = None,
    ) -> None:
        self.repo_root = Path(repo_root) if repo_root else REPO_ROOT
        self.registry_path = Path(registry_path) if registry_path else DEFAULT_REGISTRY_PATH
        self.weights_manifest_path = (
            Path(weights_manifest_path)
            if weights_manifest_path
            else (self.repo_root / "security" / "supply_chain" / "weights_sha256.json")
        )
        self._data = self._load()

    def _resolve_repo_path(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        return p if p.is_absolute() else (self.repo_root / p)

    def _load(self) -> Dict[str, Any]:
        if not self.registry_path.is_file():
            raise RegistryError(f"Registry file not found: {self.registry_path}")
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RegistryError(f"Malformed registry JSON in {self.registry_path}: {exc}") from exc
        validate_registry_data(data)
        return data

    def _save(self) -> None:
        self._data["updated_at"] = _utc_now()
        validate_registry_data(self._data)
        _atomic_write_json(self.registry_path, self._data)

    def reload(self) -> Dict[str, Any]:
        self._data = self._load()
        return self._data

    @property
    def data(self) -> Dict[str, Any]:
        return copy.deepcopy(self._data)

    def get_entry(self, entry_id: str) -> Dict[str, Any]:
        entries = self._data["entries"]
        if entry_id not in entries:
            raise RegistryError(f"Unknown registry entry_id: {entry_id!r}")
        return copy.deepcopy(entries[entry_id])

    def get_active_entry(self, detector_name: str) -> Optional[Dict[str, Any]]:
        entry_id = self._data["active"].get(detector_name)
        if not entry_id:
            return None
        return self.get_entry(entry_id)

    def list_entries(self, detector_name: Optional[str] = None) -> List[Dict[str, Any]]:
        entries = [
            copy.deepcopy(e)
            for e in self._data["entries"].values()
            if detector_name is None or e["detector_name"] == detector_name
        ]
        entries.sort(key=lambda e: (e["detector_name"], e["version"], e["entry_id"]))
        return entries

    def register_entry(
        self,
        entry: Dict[str, Any],
        verify_files: bool = True,
        reason: str = "Registered new candidate checkpoint",
    ) -> Dict[str, Any]:
        candidate = copy.deepcopy(entry)
        candidate.setdefault("status", "staging")
        candidate.setdefault("measured_metrics", {})
        candidate.setdefault("registered_at", _utc_now())

        validate_entry_data(candidate)
        entry_id = candidate["entry_id"]
        if entry_id in self._data["entries"]:
            raise RegistryError(f"Registry entry already exists: {entry_id!r}")

        if verify_files:
            ckpt = candidate["checkpoint"]
            ckpt_path = self._resolve_repo_path(ckpt["path"])
            if ckpt_path.is_file():
                verify_file_sha256(ckpt_path, ckpt["sha256"])
            elif ckpt["source_type"] != "huggingface_hub":
                raise RegistryError(f"Checkpoint file missing on disk: {ckpt_path}")

            adapter_path_str = ckpt.get("adapter_path")
            if adapter_path_str:
                adapter_path = self._resolve_repo_path(adapter_path_str)
                if not adapter_path.is_file():
                    raise RegistryError(f"Adapter file missing on disk: {adapter_path}")
                if ckpt.get("adapter_sha256"):
                    verify_file_sha256(adapter_path, ckpt["adapter_sha256"])

            cal = candidate["calibration"]
            cal_path = self._resolve_repo_path(cal["path"])
            if not cal_path.is_file():
                raise RegistryError(f"Calibration file missing on disk: {cal_path}")
            verify_file_sha256(cal_path, cal["sha256"])
            loaded_cal = CalibratorRegistry.load_file(cal_path)
            _ = loaded_cal.predict(0.5)

            sig_path_str = cal.get("signal_calibration_path")
            if sig_path_str:
                sig_path = self._resolve_repo_path(sig_path_str)
                if not sig_path.is_file():
                    raise RegistryError(f"Signal calibration file missing: {sig_path}")
                json.loads(sig_path.read_text(encoding="utf-8"))
                if cal.get("signal_calibration_sha256"):
                    verify_file_sha256(sig_path, cal["signal_calibration_sha256"])

        self._data["entries"][entry_id] = candidate
        self._data["promotion_history"].append(
            {
                "timestamp": _utc_now(),
                "action": "register",
                "detector_name": candidate["detector_name"],
                "from_entry_id": self._data["active"].get(candidate["detector_name"]),
                "to_entry_id": entry_id,
                "gate_passed": None,
                "reason": reason,
                "gate_summary": None,
            }
        )
        self._save()
        return copy.deepcopy(candidate)

    def verify_all(self, require_local_hf: bool = False) -> Dict[str, Any]:
        """Verifies schema, weight digests against weights_sha256.json, and calibration artifacts."""
        validate_registry_data(self._data)
        weights_artifacts: Dict[str, Any] = {}
        if self.weights_manifest_path.is_file():
            weights_artifacts = load_weights_manifest(self.weights_manifest_path)

        results: List[Dict[str, Any]] = []
        all_ok = True
        for entry_id, entry in sorted(self._data["entries"].items()):
            issues: List[str] = []
            ckpt = entry["checkpoint"]
            ckpt_rel = ckpt["path"]
            ckpt_path = self._resolve_repo_path(ckpt_rel)

            if ckpt_rel in weights_artifacts:
                if weights_artifacts[ckpt_rel]["sha256"] != ckpt["sha256"]:
                    issues.append(
                        f"Checkpoint SHA-256 mismatch vs weights_sha256.json for {ckpt_rel}"
                    )

            if ckpt_path.is_file():
                try:
                    verify_file_sha256(ckpt_path, ckpt["sha256"])
                except ModelIntegrityError as exc:
                    issues.append(str(exc))
            elif ckpt["source_type"] != "huggingface_hub" or require_local_hf:
                issues.append(f"Checkpoint file missing on disk: {ckpt_path}")

            adapter_rel = ckpt.get("adapter_path")
            if adapter_rel:
                adapter_path = self._resolve_repo_path(adapter_rel)
                if adapter_rel in weights_artifacts and ckpt.get("adapter_sha256"):
                    if weights_artifacts[adapter_rel]["sha256"] != ckpt["adapter_sha256"]:
                        issues.append(
                            f"Adapter SHA-256 mismatch vs weights_sha256.json for {adapter_rel}"
                        )
                if adapter_path.is_file():
                    if ckpt.get("adapter_sha256"):
                        try:
                            verify_file_sha256(adapter_path, ckpt["adapter_sha256"])
                        except ModelIntegrityError as exc:
                            issues.append(str(exc))
                else:
                    issues.append(f"Adapter file missing on disk: {adapter_path}")

            cal = entry["calibration"]
            cal_path = self._resolve_repo_path(cal["path"])
            if not cal_path.is_file():
                issues.append(f"Calibration file missing on disk: {cal_path}")
            else:
                try:
                    verify_file_sha256(cal_path, cal["sha256"])
                    loaded_cal = CalibratorRegistry.load_file(cal_path)
                    _ = loaded_cal.predict(0.5)
                except Exception as exc:
                    issues.append(f"Calibration validation failed: {exc}")

            sig_rel = cal.get("signal_calibration_path")
            if sig_rel:
                sig_path = self._resolve_repo_path(sig_rel)
                if not sig_path.is_file():
                    issues.append(f"Signal calibration file missing: {sig_path}")
                elif cal.get("signal_calibration_sha256"):
                    try:
                        verify_file_sha256(sig_path, cal["signal_calibration_sha256"])
                    except ModelIntegrityError as exc:
                        issues.append(str(exc))

            manifest_path = self._resolve_repo_path(entry["manifest_path"])
            if not manifest_path.is_file():
                issues.append(f"Manifest missing: {manifest_path}")
            else:
                try:
                    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    jsonschema.validate(instance=manifest_data, schema=DETECTOR_MANIFEST_SCHEMA)
                except Exception as exc:
                    issues.append(f"Manifest invalid: {exc}")

            ok = len(issues) == 0
            if not ok:
                all_ok = False
            results.append(
                {
                    "entry_id": entry_id,
                    "detector_name": entry["detector_name"],
                    "status": entry["status"],
                    "verified": ok,
                    "local_checkpoint_present": ckpt_path.is_file(),
                    "issues": issues,
                }
            )

        return {"all_verified": all_ok, "entries": results}

    def activate_entry(
        self,
        entry_id: str,
        gate_report: Dict[str, Any],
        updated_manifest: Dict[str, Any],
        reason: str = "Passed promotion gate",
    ) -> Dict[str, Any]:
        """Atomically activates a gate-approved entry and updates its capability manifest."""
        if not gate_report.get("passed"):
            raise PromotionBlockedError(
                f"Cannot activate {entry_id!r}: promotion gate did not pass."
            )
        if entry_id not in self._data["entries"]:
            raise RegistryError(f"Unknown registry entry_id: {entry_id!r}")

        entry = self._data["entries"][entry_id]
        detector_name = entry["detector_name"]
        manifest_path = self._resolve_repo_path(entry["manifest_path"])
        if not manifest_path.is_file():
            raise RegistryError(f"Target capability manifest not found: {manifest_path}")

        current_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_snapshot = _snapshot_manifest_fields(current_manifest)

        # Preserve any live observed_reliability updates from disk
        final_manifest = copy.deepcopy(updated_manifest)
        if "observed_reliability" in current_manifest:
            final_manifest["observed_reliability"] = copy.deepcopy(
                current_manifest["observed_reliability"]
            )
        try:
            jsonschema.validate(instance=final_manifest, schema=DETECTOR_MANIFEST_SCHEMA)
        except jsonschema.ValidationError as exc:
            raise RegistryValidationError(
                f"Updated manifest violates DETECTOR_MANIFEST_SCHEMA: {exc.message}"
            ) from exc

        prev_entry_id = self._data["active"].get(detector_name)
        if prev_entry_id and prev_entry_id != entry_id and prev_entry_id in self._data["entries"]:
            self._data["entries"][prev_entry_id]["status"] = "archived"

        entry["status"] = "active"
        if gate_report.get("measured_metrics"):
            entry["measured_metrics"] = copy.deepcopy(gate_report["measured_metrics"])
        self._data["active"][detector_name] = entry_id

        _atomic_write_json(manifest_path, final_manifest)

        self._data["promotion_history"].append(
            {
                "timestamp": _utc_now(),
                "action": "promote",
                "detector_name": detector_name,
                "from_entry_id": prev_entry_id,
                "to_entry_id": entry_id,
                "gate_passed": True,
                "reason": reason,
                "gate_summary": copy.deepcopy(gate_report.get("summary", {})),
                "manifest_snapshot": manifest_snapshot,
            }
        )
        self._save()
        return {
            "detector_name": detector_name,
            "from_entry_id": prev_entry_id,
            "to_entry_id": entry_id,
            "manifest_path": str(manifest_path),
        }

    def rollback(
        self,
        detector_name: str,
        target_entry_id: Optional[str] = None,
        reason: str = "Operator rollback",
    ) -> Dict[str, Any]:
        """Rolls back a detector to its prior active entry and restores its manifest snapshot."""
        current_active_id = self._data["active"].get(detector_name)
        if not current_active_id:
            raise RegistryError(f"No active entry found for detector {detector_name!r}")

        promote_event: Optional[Dict[str, Any]] = None
        for event in reversed(self._data["promotion_history"]):
            if (
                event.get("action") == "promote"
                and event.get("detector_name") == detector_name
                and event.get("to_entry_id") == current_active_id
            ):
                if target_entry_id is None or event.get("from_entry_id") == target_entry_id:
                    promote_event = event
                    break

        resolved_target = target_entry_id or (
            promote_event.get("from_entry_id") if promote_event else None
        )
        if not resolved_target or resolved_target not in self._data["entries"]:
            raise RegistryError(
                f"No valid rollback target found for detector {detector_name!r} "
                f"(current active: {current_active_id!r})."
            )

        target_entry = self._data["entries"][resolved_target]
        manifest_path = self._resolve_repo_path(target_entry["manifest_path"])
        if not manifest_path.is_file():
            raise RegistryError(f"Target capability manifest not found: {manifest_path}")

        live_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        snapshot = promote_event.get("manifest_snapshot") if promote_event else None
        if isinstance(snapshot, dict):
            restored_manifest = _restore_manifest_fields(live_manifest, snapshot)
        else:
            restored_manifest = copy.deepcopy(live_manifest)
            restored_manifest["version"] = target_entry["model_version"]
            restored_manifest["calibration"] = {
                "modality": target_entry["modality"],
                "preferred_method": target_entry["calibration"]["preferred_method"],
                "checkpoint": target_entry["calibration"]["path"],
            }
            restored_manifest.pop("registry_entry_id", None)

        try:
            jsonschema.validate(instance=restored_manifest, schema=DETECTOR_MANIFEST_SCHEMA)
        except jsonschema.ValidationError as exc:
            raise RegistryValidationError(
                f"Restored manifest violates DETECTOR_MANIFEST_SCHEMA: {exc.message}"
            ) from exc

        _atomic_write_json(manifest_path, restored_manifest)

        if current_active_id in self._data["entries"]:
            self._data["entries"][current_active_id]["status"] = "rolled_back"
        target_entry["status"] = "active"
        self._data["active"][detector_name] = resolved_target

        self._data["promotion_history"].append(
            {
                "timestamp": _utc_now(),
                "action": "rollback",
                "detector_name": detector_name,
                "from_entry_id": current_active_id,
                "to_entry_id": resolved_target,
                "gate_passed": None,
                "reason": reason,
                "gate_summary": None,
            }
        )
        self._save()
        return {
            "detector_name": detector_name,
            "rolled_back_from": current_active_id,
            "restored_to": resolved_target,
            "manifest_path": str(manifest_path),
        }

    def compute_file_sha256(self, rel_or_abs: str) -> str:
        return compute_sha256(self._resolve_repo_path(rel_or_abs))
