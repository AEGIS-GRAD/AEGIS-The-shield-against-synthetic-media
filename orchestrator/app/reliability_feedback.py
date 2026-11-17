"""
reliability_feedback.py — Closed-loop detector reliability tracking & manifest write-back
=======================================================================================
Closes AEGIS's reliability feedback loop (RQ2):
  1. Records per-detector claims and whether the Judge Agent overruled them.
  2. Records post-hoc ground-truth confirmations and marks confirmed-wrong overrules.
  3. Computes rolling-window reliability per (detector, operating_condition) across
     low_light, short_clip, dubbed_audio, and nominal conditions.
  4. Atomically writes validated `observed_reliability` metrics back into
     `capability_manifests/*.json` so the Planner deprioritizes failing detectors.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from manifest_loader import _manifests_dir, _reliability_overlay_dir, validate_manifest
except ImportError:  # pragma: no cover - package-style import fallback
    from orchestrator.app.manifest_loader import _manifests_dir, _reliability_overlay_dir, validate_manifest


def _get_db():
    """Lazy import of orchestrator.app.db so pure condition/eligibility helpers stay SQLAlchemy-free."""
    try:
        import db as _db
        return _db
    except ImportError:  # pragma: no cover
        from orchestrator.app import db as _db
        return _db

logger = logging.getLogger("aegis.orchestrator.reliability_feedback")

_MANIFEST_WRITE_LOCK = threading.Lock()

CANONICAL_CONDITIONS: Tuple[str, ...] = ("low_light", "short_clip", "dubbed_audio", "nominal")

_LOW_LIGHT_FLAGS = {
    "low_light_attenuation",
    "insufficient_lighting",
    "rppg_dim_light_attenuation",
    "rppg_severe_dark_lum_lt_18",
    "vc_low_light",
    "vc_severe_dark",
}

_SHORT_CLIP_FLAGS = {
    "short_clip_attenuation",
    "marginal_duration",
    "rppg_short_duration_2_to_5s",
    "rppg_insufficient_duration_lt_2s",
    "vc_short_clip_lt_2s",
    "aasist_short_audio_1s_to_2s",
    "aasist_audio_lt_1s",
}

_DUBBED_AUDIO_FLAGS = {
    "foreign_dubbing_risk",
    "low_language_confidence",
    "syncnet_dubbing_language_discount",
}


@dataclass(frozen=True)
class ReliabilityConfig:
    """Configuration parameters for rolling per-condition reliability scoring."""

    window_size: int = 50
    min_samples: int = 5
    prior_alpha: float = 4.0
    prior_reliability: float = 0.75
    deprioritize_threshold: float = 0.55
    caution_threshold: float = 0.72
    overrule_rate_threshold: float = 0.40
    overrule_guard_ceiling: float = 0.60


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_truthy_tag(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() in {"1", "true", "yes", "dubbed", "mismatch", "foreign"}


def extract_condition_tags_from_input(metadata: Any) -> List[str]:
    """
    Derives canonical operating condition tags from InputMetadata or an input_summary dict.
    Returns one or more of: `low_light`, `short_clip`, `dubbed_audio`, or `["nominal"]`.
    """
    tags: List[str] = []

    modality = str(_get_field(metadata, "modality", "unknown") or "unknown").lower()
    mean_lum = _get_field(metadata, "mean_luminance", None)
    duration = _get_field(metadata, "duration_seconds", None)
    meta_tags = _get_field(metadata, "metadata_tags", {}) or {}
    explicit = _get_field(metadata, "operating_conditions", None) or []

    explicit_set = {str(x).strip().lower() for x in explicit if x}

    # 1. Low light
    if (
        "low_light" in explicit_set
        or (mean_lum is not None and float(mean_lum) < 40.0)
        or str(meta_tags.get("lighting", "")).strip().lower() in {"low", "low_light", "dark"}
        or _is_truthy_tag(meta_tags.get("low_light"))
    ):
        tags.append("low_light")

    # 2. Short clip (only applies to temporal media with positive duration)
    if (
        "short_clip" in explicit_set
        or (
            modality in {"video", "audio"}
            and duration is not None
            and 0.0 < float(duration) < 5.0
        )
        or _is_truthy_tag(meta_tags.get("short_clip"))
    ):
        tags.append("short_clip")

    # 3. Dubbed audio / audio-visual language mismatch
    audio_lang = str(meta_tags.get("audio_language", "")).strip().lower()
    video_lang = str(meta_tags.get("video_language", "")).strip().lower()
    lang_mismatch = bool(audio_lang and video_lang and audio_lang != video_lang)
    if (
        "dubbed_audio" in explicit_set
        or lang_mismatch
        or _is_truthy_tag(meta_tags.get("dubbed_audio"))
        or _is_truthy_tag(meta_tags.get("dubbed"))
        or _is_truthy_tag(meta_tags.get("foreign_dubbing_risk"))
    ):
        tags.append("dubbed_audio")

    if not tags:
        tags.append("nominal")
    return list(dict.fromkeys(tags))


def extract_condition_tags(
    metadata: Any,
    raw_results: Optional[Sequence[Any]] = None,
    judge_report: Optional[Any] = None,
) -> List[str]:
    """
    Enriches input-derived operating condition tags with runtime detector flags
    and Judge cross-examination / adjudication rules.
    """
    detected: List[str] = [
        t for t in extract_condition_tags_from_input(metadata) if t != "nominal"
    ]

    all_tokens: set[str] = set()
    for res in raw_results or []:
        ev = _get_field(res, "evidence", None)
        flags = _get_field(ev, "flags", []) or []
        all_tokens.update(str(f).strip().lower() for f in flags)

    if judge_report is not None:
        verdict = _get_field(judge_report, "verdict", None)
        adjudications = _get_field(verdict, "adjudications", []) or []
        for adj in adjudications:
            for cond in _get_field(adj, "applied_conditions", []) or []:
                all_tokens.add(str(cond).strip().lower())
            reason = str(_get_field(adj, "discount_reason", "") or "").lower()
            if "low-light" in reason or "low light" in reason or "luminance" in reason:
                all_tokens.add("low_light_attenuation")
            if "short duration" in reason or "short clip" in reason:
                all_tokens.add("short_clip_attenuation")

    if all_tokens & _LOW_LIGHT_FLAGS and "low_light" not in detected:
        detected.append("low_light")
    if all_tokens & _SHORT_CLIP_FLAGS and "short_clip" not in detected:
        detected.append("short_clip")
    if all_tokens & _DUBBED_AUDIO_FLAGS and "dubbed_audio" not in detected:
        detected.append("dubbed_audio")

    if not detected:
        return ["nominal"]
    # Keep deterministic canonical order
    ordered = [c for c in CANONICAL_CONDITIONS if c in detected]
    for c in detected:
        if c not in ordered:
            ordered.append(c)
    return ordered


def is_claim_overruled(adj: Any, final_verdict: str) -> bool:
    """
    Determines whether the Judge Agent overruled or materially discounted a
    detector's claim during arbitration.
    """
    orig_pol = str(
        getattr(_get_field(adj, "original_polarity"), "value", _get_field(adj, "original_polarity", ""))
    ).upper()
    orig_conf = float(_get_field(adj, "original_confidence", 0.5) or 0.5)
    acc_conf = float(_get_field(adj, "accepted_confidence", orig_conf) or orig_conf)
    weight = float(_get_field(adj, "weight_assigned", 1.0) or 0.0)
    discount_reason = _get_field(adj, "discount_reason", None)

    if discount_reason:
        return True
    if orig_pol in {"AUTHENTIC", "SYNTHETIC"}:
        if final_verdict in {"AUTHENTIC", "SYNTHETIC"} and orig_pol != final_verdict:
            return True
        if abs(orig_conf - acc_conf) >= 0.15 or weight <= 0.0:
            return True
    return False


def build_claim_outcome_records(
    job_id: str,
    metadata: Any,
    raw_results: Optional[Sequence[Any]],
    judge_report: Any,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Builds DB-ready per-detector claim outcome dicts from an orchestrated job's
    InputMetadata, detector results, and JudgeReport.
    """
    cond_tags = extract_condition_tags(metadata, raw_results=raw_results, judge_report=judge_report)
    modality = str(_get_field(metadata, "modality", "unknown") or "unknown")
    verdict_obj = _get_field(judge_report, "verdict", None)
    final_verdict_obj = _get_field(verdict_obj, "final_verdict", "INTEGRITY_UNKNOWN")
    final_verdict = str(getattr(final_verdict_obj, "value", final_verdict_obj))

    versions_by_det: Dict[str, Optional[str]] = {}
    for res in raw_results or []:
        det = _get_field(res, "detector", None)
        if det:
            versions_by_det[str(det)] = _get_field(res, "model_version", None)

    records: List[Dict[str, Any]] = []
    for adj in _get_field(verdict_obj, "adjudications", []) or []:
        det_id = str(_get_field(adj, "detector_id"))
        orig_pol_obj = _get_field(adj, "original_polarity", "INCONCLUSIVE")
        orig_pol = str(getattr(orig_pol_obj, "value", orig_pol_obj))
        overruled = is_claim_overruled(adj, final_verdict)
        records.append({
            "job_id": job_id,
            "session_id": session_id,
            "detector_name": det_id,
            "model_version": versions_by_det.get(det_id),
            "modality": modality,
            "condition_tags": cond_tags,
            "original_polarity": orig_pol,
            "original_confidence": float(_get_field(adj, "original_confidence", 0.5)),
            "accepted_confidence": float(_get_field(adj, "accepted_confidence", 0.5)),
            "weight_assigned": float(_get_field(adj, "weight_assigned", 0.0)),
            "judge_verdict": final_verdict,
            "overruled_by_judge": overruled,
            "discount_reason": _get_field(adj, "discount_reason", None),
        })
    return records


def _classify_status(
    sample_count: int,
    rolling_reliability: float,
    confirmed_overrule_rate: float,
    config: ReliabilityConfig,
) -> str:
    if sample_count < config.min_samples:
        return "insufficient_data"
    if rolling_reliability < config.deprioritize_threshold:
        return "deprioritize"
    if (
        confirmed_overrule_rate >= config.overrule_rate_threshold
        and rolling_reliability < config.overrule_guard_ceiling
    ):
        return "deprioritize"
    if rolling_reliability < config.caution_threshold:
        return "caution"
    return "reliable"


def _aggregate_window(
    rows: Sequence[Dict[str, Any]],
    config: ReliabilityConfig,
    timestamp_iso: str,
) -> Dict[str, Any]:
    """Aggregates the most recent `window_size` decisive outcomes into reliability metrics."""
    decisive = [r for r in rows if r.get("detector_was_wrong") is not None]
    window = decisive[-config.window_size :]
    n = len(window)
    wrong = sum(1 for r in window if r.get("detector_was_wrong") is True)
    correct = n - wrong
    overruled = sum(1 for r in window if r.get("overruled_by_judge") is True)
    confirmed_overrule = sum(1 for r in window if r.get("confirmed_overrule") is True)

    rolling = (correct + config.prior_alpha * config.prior_reliability) / (
        n + config.prior_alpha
    )
    rolling = round(max(0.0, min(1.0, rolling)), 4)
    raw_acc = round(correct / n, 4) if n > 0 else None
    overrule_rate = round(confirmed_overrule / n, 4) if n > 0 else None
    status = _classify_status(
        n,
        rolling,
        overrule_rate if overrule_rate is not None else 0.0,
        config,
    )

    last_ts = window[-1].get("confirmed_at") or window[-1].get("timestamp") or timestamp_iso if window else timestamp_iso

    return {
        "sample_count": n,
        "correct_count": correct,
        "wrong_count": wrong,
        "overruled_count": overruled,
        "confirmed_overrule_count": confirmed_overrule,
        "raw_accuracy": raw_acc,
        "rolling_reliability": rolling,
        "confirmed_overrule_rate": overrule_rate,
        "status": status,
        "last_updated": last_ts,
    }


def compute_rolling_reliability(
    confirmed_outcomes: Iterable[Dict[str, Any]],
    config: Optional[ReliabilityConfig] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Computes rolling-window reliability metrics per `(detector_name, condition)`
    and overall per detector from chronologically ordered confirmed outcomes.
    """
    cfg = config or ReliabilityConfig()
    now_iso = datetime.now(timezone.utc).isoformat()

    by_det_all: Dict[str, List[Dict[str, Any]]] = {}
    by_det_cond: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    for row in confirmed_outcomes:
        det = row.get("detector_name")
        if not det:
            continue
        by_det_all.setdefault(det, []).append(row)
        conds = row.get("condition_tags") or ["nominal"]
        cond_map = by_det_cond.setdefault(det, {})
        for cond in conds:
            cond_map.setdefault(str(cond), []).append(row)

    summary: Dict[str, Dict[str, Any]] = {}
    for det, rows in sorted(by_det_all.items()):
        overall = _aggregate_window(rows, cfg, now_iso)
        cond_entries: Dict[str, Dict[str, Any]] = {}
        for cond, cond_rows in sorted(by_det_cond.get(det, {}).items()):
            entry = _aggregate_window(cond_rows, cfg, now_iso)
            if entry["sample_count"] > 0:
                cond_entries[cond] = entry
        if overall["sample_count"] == 0 and not cond_entries:
            continue
        summary[det] = {
            "updated_at": now_iso,
            "window_size": cfg.window_size,
            "overall": overall,
            "by_condition": cond_entries,
        }
    return summary


def _atomic_write_json(target_path: Path, payload: Dict[str, Any]) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target_path.stem}_",
        suffix=".tmp",
        dir=str(target_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_fh:
            json.dump(payload, tmp_fh, indent=2)
            tmp_fh.write("\n")
        os.replace(tmp_name, target_path)
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def write_reliability_to_manifests(
    reliability_by_detector: Dict[str, Dict[str, Any]],
    manifests_dir: Optional[Path] = None,
) -> List[str]:
    """
    Atomically updates `observed_reliability` inside each matching manifest JSON
    after validating against DETECTOR_MANIFEST_SCHEMA. Falls back gracefully to a
    writable overlay directory (`AEGIS_RELIABILITY_OVERLAY_DIR`) if the manifests
    directory is mounted read-only (e.g. Docker `:ro`).
    Returns list of updated detector names.
    """
    if not reliability_by_detector:
        return []

    target_dir = Path(manifests_dir) if manifests_dir is not None else _manifests_dir()
    if not target_dir.is_dir():
        logger.warning(f"Manifest directory '{target_dir}' does not exist; skipping write-back.")
        return []

    updated_detectors: List[str] = []
    with _MANIFEST_WRITE_LOCK:
        for det_name, obs_payload in reliability_by_detector.items():
            manifest_path = target_dir / f"{det_name}.json"
            if not manifest_path.exists():
                # Support image manifest alias when detector_id == "image" vs "detector_image"
                if det_name == "image" and (target_dir / "detector_image.json").exists():
                    manifest_path = target_dir / "detector_image.json"
                else:
                    logger.debug(f"No manifest JSON at '{manifest_path}' for detector '{det_name}'; skipping.")
                    continue

            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)

            base_rev = int((manifest.get("observed_reliability") or {}).get("revision", 0))
            overlay_dir_existing = _reliability_overlay_dir(create=False)
            overlay_rev = 0
            if overlay_dir_existing is not None:
                ov_path = overlay_dir_existing / manifest_path.name
                if ov_path.is_file():
                    try:
                        with open(ov_path, "r", encoding="utf-8") as ofh:
                            ov_json = json.load(ofh)
                        overlay_rev = int((ov_json.get("observed_reliability") or {}).get("revision", 0))
                    except Exception:
                        overlay_rev = 0

            prev_rev = max(base_rev, overlay_rev)
            payload_with_rev = dict(obs_payload)
            payload_with_rev["revision"] = prev_rev + 1
            manifest["observed_reliability"] = payload_with_rev

            # Schema validation gate before touching disk
            validate_manifest(manifest)

            try:
                _atomic_write_json(manifest_path, manifest)
            except OSError as exc:
                if exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM) or isinstance(exc, PermissionError):
                    overlay_dir = _reliability_overlay_dir(create=True)
                    if overlay_dir is None:
                        raise
                    overlay_path = overlay_dir / manifest_path.name
                    _atomic_write_json(
                        overlay_path,
                        {
                            "detector_name": manifest.get("detector_name", det_name),
                            "observed_reliability": payload_with_rev,
                        },
                    )
                    logger.warning(
                        f"Manifest directory '{target_dir}' is read-only ({exc}); wrote reliability overlay "
                        f"to '{overlay_path}' (rev={payload_with_rev['revision']})."
                    )
                else:
                    raise

            updated_detectors.append(det_name)
            logger.info(
                f"Updated manifest '{manifest_path.name}' observed_reliability "
                f"(rev={payload_with_rev['revision']}, conditions={list(obs_payload.get('by_condition', {}).keys())})"
            )

    return updated_detectors


class ReliabilityFeedbackEngine:
    """High-level coordinator for recording claim outcomes and updating manifests."""

    def __init__(
        self,
        manifests_dir: Optional[Path] = None,
        session_factory=None,
        config: Optional[ReliabilityConfig] = None,
        telemetry_hook: Optional[Callable[[Dict[str, Dict[str, Any]]], None]] = None,
    ) -> None:
        self.manifests_dir = Path(manifests_dir) if manifests_dir is not None else None
        self._session_factory = session_factory
        self.config = config or ReliabilityConfig()
        self.telemetry_hook = telemetry_hook

    @property
    def session_factory(self):
        return self._session_factory or _get_db().SessionLocal

    def record_adjudication(
        self,
        job_id: str,
        metadata: Any,
        raw_results: Optional[Sequence[Any]],
        judge_report: Any,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        records = build_claim_outcome_records(
            job_id=job_id,
            metadata=metadata,
            raw_results=raw_results,
            judge_report=judge_report,
            session_id=session_id,
        )
        _get_db().log_claim_outcomes(records, session_factory=self.session_factory)
        return records

    def recompute_and_write_manifests(self, apply_to_manifests: bool = True) -> Dict[str, Dict[str, Any]]:
        confirmed = _get_db().fetch_confirmed_claim_outcomes(session_factory=self.session_factory)
        summary = compute_rolling_reliability(confirmed, config=self.config)
        if apply_to_manifests and summary:
            write_reliability_to_manifests(summary, manifests_dir=self.manifests_dir)
        if self.telemetry_hook and summary:
            try:
                self.telemetry_hook(summary)
            except Exception as exc:  # pragma: no cover
                logger.warning(f"Telemetry hook failed during reliability update: {exc}")
        return summary

    def confirm_and_update(
        self,
        job_id: str,
        ground_truth_label: str,
        confirmed_by: str = "analyst",
        apply_to_manifests: bool = True,
    ) -> Dict[str, Any]:
        updated_rows = _get_db().confirm_ground_truth(
            job_id=job_id,
            ground_truth_label=ground_truth_label,
            confirmed_by=confirmed_by,
            session_factory=self.session_factory,
        )
        if not updated_rows:
            return {"job_id": job_id, "updated_claims": [], "manifests_updated": []}

        summary = self.recompute_and_write_manifests(apply_to_manifests=apply_to_manifests)
        return {
            "job_id": job_id,
            "ground_truth_label": updated_rows[0]["ground_truth_label"],
            "updated_claims": updated_rows,
            "manifests_updated": sorted(summary.keys()) if apply_to_manifests else [],
            "reliability_summary": summary,
        }

    def confirm_batch_and_update(
        self,
        confirmations: Sequence[Tuple[str, str]],
        confirmed_by: str = "batch_eval",
        apply_to_manifests: bool = True,
    ) -> Dict[str, Any]:
        db_mod = _get_db()
        rows = db_mod.confirm_ground_truth_batch(
            list(confirmations),
            confirmed_by=confirmed_by,
            session_factory=self.session_factory,
        )
        total_updated = len(rows)
        confirmed_overrules = sum(1 for r in rows if r.get("confirmed_overrule"))

        summary = self.recompute_and_write_manifests(apply_to_manifests=apply_to_manifests)
        return {
            "jobs_confirmed": len(confirmations),
            "claims_updated": total_updated,
            "confirmed_overrules_in_batch": confirmed_overrules,
            "manifests_updated": sorted(summary.keys()) if apply_to_manifests else [],
            "reliability_summary": summary,
        }

    def get_summary(self) -> Dict[str, Dict[str, Any]]:
        confirmed = _get_db().fetch_confirmed_claim_outcomes(session_factory=self.session_factory)
        return compute_rolling_reliability(confirmed, config=self.config)
