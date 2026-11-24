"""Tests for Task #5: Versioned Model Registry & Automatic Promotion Gate."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict

import jsonschema
import pytest

from capability_manifests.Schema import DETECTOR_MANIFEST_SCHEMA
from model_registry.gate import PromotionGate
from model_registry.registry import (
    ModelRegistry,
    PromotionBlockedError,
    RegistryError,
    RegistryValidationError,
)
from model_registry.schema import validate_registry_data
from security.supply_chain.model_integrity import load_weights_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().lower()


def _build_isolated_workspace(tmp_path: Path) -> tuple[Path, ModelRegistry]:
    """Creates a self-contained temp workspace with synthetic weights, calibrations, and manifests."""
    (tmp_path / "capability_manifests").mkdir(parents=True)
    (tmp_path / "detectors" / "text-detector" / "models" / "desklib-base").mkdir(parents=True)
    (tmp_path / "detectors" / "text-detector" / "models" / "desklib-finetuned" / "lora_adapter").mkdir(parents=True)
    (tmp_path / "detectors" / "image" / "weights").mkdir(parents=True)
    (tmp_path / "eval" / "calibration" / "checkpoints").mkdir(parents=True)
    (tmp_path / "eval" / "data" / "text").mkdir(parents=True)
    (tmp_path / "security" / "supply_chain").mkdir(parents=True)
    (tmp_path / "model_registry").mkdir(parents=True)

    # Copy real manifests and calibrations
    shutil.copy2(
        REPO_ROOT / "capability_manifests" / "detector_text.json",
        tmp_path / "capability_manifests" / "detector_text.json",
    )
    shutil.copy2(
        REPO_ROOT / "capability_manifests" / "image.json",
        tmp_path / "capability_manifests" / "image.json",
    )
    shutil.copy2(
        REPO_ROOT / "eval" / "calibration" / "checkpoints" / "detector_text_platt_calibrator.json",
        tmp_path / "eval" / "calibration" / "checkpoints" / "detector_text_platt_calibrator.json",
    )
    shutil.copy2(
        REPO_ROOT / "eval" / "calibration" / "checkpoints" / "image_temperature_calibrator.json",
        tmp_path / "eval" / "calibration" / "checkpoints" / "image_temperature_calibrator.json",
    )
    shutil.copy2(
        REPO_ROOT / "detectors" / "text-detector" / "models" / "signal_calibration.json",
        tmp_path / "detectors" / "text-detector" / "models" / "signal_calibration.json",
    )
    shutil.copy2(
        REPO_ROOT / "eval" / "data" / "text" / "text_eval_manifest.jsonl",
        tmp_path / "eval" / "data" / "text" / "text_eval_manifest.jsonl",
    )

    # Create deterministic synthetic weight files for fast, isolated gate testing
    base_bytes = b"synthetic-desklib-base-weights-v1"
    lora_bytes = b"synthetic-desklib-lora-adapter-v1.1"
    commfor_bytes = b"synthetic-commfor-vit-weights-v1"

    (tmp_path / "detectors" / "text-detector" / "models" / "desklib-base" / "model.safetensors").write_bytes(base_bytes)
    (tmp_path / "detectors" / "text-detector" / "models" / "desklib-finetuned" / "lora_adapter" / "adapter_model.safetensors").write_bytes(lora_bytes)
    (tmp_path / "detectors" / "image" / "weights" / "model.safetensors").write_bytes(commfor_bytes)

    weights_manifest = {
        "schema_version": "1.0",
        "artifacts": {
            "detectors/text-detector/models/desklib-base/model.safetensors": {
                "sha256": _sha256_bytes(base_bytes)
            },
            "detectors/text-detector/models/desklib-finetuned/lora_adapter/adapter_model.safetensors": {
                "sha256": _sha256_bytes(lora_bytes)
            },
            "detectors/image/weights/model.safetensors": {
                "sha256": _sha256_bytes(commfor_bytes)
            },
        },
    }
    (tmp_path / "security" / "supply_chain" / "weights_sha256.json").write_text(
        json.dumps(weights_manifest, indent=2), encoding="utf-8"
    )

    reg_data = json.loads((REPO_ROOT / "model_registry" / "registry.json").read_text(encoding="utf-8"))
    reg_data["entries"]["image@1.0.0-commfor"]["checkpoint"]["sha256"] = _sha256_bytes(commfor_bytes)
    reg_data["entries"]["image@1.0.0-commfor"]["checkpoint"]["size_bytes"] = len(commfor_bytes)

    for eid in ("detector_text@1.0.0-asis", "detector_text@1.1.0-lora-finetuned"):
        reg_data["entries"][eid]["checkpoint"]["sha256"] = _sha256_bytes(base_bytes)
        reg_data["entries"][eid]["checkpoint"]["size_bytes"] = len(base_bytes)
    reg_data["entries"]["detector_text@1.1.0-lora-finetuned"]["checkpoint"]["adapter_sha256"] = _sha256_bytes(lora_bytes)

    reg_path = tmp_path / "model_registry" / "registry.json"
    reg_path.write_text(json.dumps(reg_data, indent=2), encoding="utf-8")

    return tmp_path, ModelRegistry(registry_path=reg_path, repo_root=tmp_path)


def test_seeded_registry_schema_and_weights_manifest_consistency():
    registry = ModelRegistry()
    validate_registry_data(registry.data)

    entries = {e["entry_id"]: e for e in registry.list_entries()}
    assert "image@1.0.0-commfor" in entries
    assert "detector_text@1.0.0-asis" in entries
    assert "detector_text@1.1.0-lora-finetuned" in entries
    assert registry.data["active"]["image"] == "image@1.0.0-commfor"
    assert registry.data["active"]["detector_text"] == "detector_text@1.0.0-asis"

    weights = load_weights_manifest()
    assert entries["image@1.0.0-commfor"]["checkpoint"]["sha256"] == weights["detectors/image/weights/model.safetensors"]["sha256"]
    assert entries["detector_text@1.0.0-asis"]["checkpoint"]["sha256"] == weights["detectors/text-detector/models/desklib-base/model.safetensors"]["sha256"]
    assert entries["detector_text@1.1.0-lora-finetuned"]["checkpoint"]["adapter_sha256"] == weights["detectors/text-detector/models/desklib-finetuned/lora_adapter/adapter_model.safetensors"]["sha256"]

    verification = registry.verify_all(require_local_hf=False)
    assert verification["all_verified"] is True, verification


def test_register_new_model_and_reject_duplicates_or_bad_schema(tmp_path: Path):
    root, registry = _build_isolated_workspace(tmp_path)
    new_ckpt = root / "detectors" / "text-detector" / "models" / "desklib-finetuned" / "lora_adapter" / "v2.safetensors"
    new_bytes = b"new-lora-v2-checkpoint"
    new_ckpt.write_bytes(new_bytes)

    base_entry = registry.get_entry("detector_text@1.1.0-lora-finetuned")
    v2_entry = copy.deepcopy(base_entry)
    v2_entry["entry_id"] = "detector_text@1.2.0-lora-v2"
    v2_entry["version"] = "1.2.0-lora-v2"
    v2_entry["model_version"] = "desklib-v1.01-lora-v2-fp16"
    v2_entry["status"] = "staging"
    v2_entry["checkpoint"]["adapter_path"] = "detectors/text-detector/models/desklib-finetuned/lora_adapter/v2.safetensors"
    v2_entry["checkpoint"]["adapter_sha256"] = _sha256_bytes(new_bytes)

    saved = registry.register_entry(v2_entry, verify_files=True)
    assert saved["entry_id"] == "detector_text@1.2.0-lora-v2"

    with pytest.raises(RegistryError, match="already exists"):
        registry.register_entry(v2_entry, verify_files=False)

    bad_entry = copy.deepcopy(v2_entry)
    bad_entry["entry_id"] = "detector_text@bad"
    bad_entry["budgets"]["max_vram_mb"] = 99999  # exceeds 8192 schema ceiling
    with pytest.raises(RegistryValidationError):
        registry.register_entry(bad_entry, verify_files=False)


def test_gate_blocks_on_tampered_hash_and_corrupt_calibration(tmp_path: Path):
    root, registry = _build_isolated_workspace(tmp_path)
    gate = PromotionGate(registry)

    # 1. Corrupt adapter weights -> Gate 1 fails
    adapter_file = root / "detectors" / "text-detector" / "models" / "desklib-finetuned" / "lora_adapter" / "adapter_model.safetensors"
    adapter_file.write_bytes(b"tampered-adapter-bytes")

    res, act = gate.promote("detector_text@1.1.0-lora-finetuned")
    assert res.passed is False
    assert act is None
    assert res.checks[0].name == "integrity_and_calibration"
    assert res.checks[0].passed is False
    assert registry.get_active_entry("detector_text")["entry_id"] == "detector_text@1.0.0-asis"  # type: ignore[index]

    # 2. Restore adapter, corrupt calibration JSON -> Gate 1 fails
    adapter_file.write_bytes(b"synthetic-desklib-lora-adapter-v1.1")
    cal_file = root / "eval" / "calibration" / "checkpoints" / "detector_text_platt_calibrator.json"
    cal_file.write_text("{not-valid-json", encoding="utf-8")

    res2, act2 = gate.promote("detector_text@1.1.0-lora-finetuned")
    assert res2.passed is False
    assert act2 is None
    assert res2.checks[0].passed is False


def test_gate_blocks_on_contract_regression_and_budget_failures(tmp_path: Path):
    root, registry = _build_isolated_workspace(tmp_path)

    # 1. Contract test failure
    gate_bad_contract = PromotionGate(
        registry,
        contract_checker=lambda _e: (False, "Simulated API contract schema mismatch", {}),
        evaluator_fn=lambda _e, _b: {
            "n_samples": 16,
            "auroc": 0.96,
            "accuracy": 0.90,
            "avg_latency_ms": 120.0,
            "p95_latency_ms": 200.0,
            "peak_ram_mb": 1200.0,
            "peak_vram_mb": 1800.0,
            "device": "cuda",
        },
    )
    res_c, act_c = gate_bad_contract.promote("detector_text@1.1.0-lora-finetuned")
    assert res_c.passed is False and act_c is None
    assert any(c.name == "schema_and_contract_tests" and not c.passed for c in res_c.checks)

    # 2. Regression drop exceeding max_auroc_drop / max_accuracy_drop
    gate_regression = PromotionGate(
        registry,
        evaluator_fn=lambda _e, _b: {
            "n_samples": 16,
            "auroc": 0.81,  # baseline is 0.931 -> drop 0.121 > 0.05
            "accuracy": 0.78,
            "calibrated_ece": 0.09,
            "avg_latency_ms": 120.0,
            "p95_latency_ms": 200.0,
            "peak_ram_mb": 1200.0,
            "peak_vram_mb": 1800.0,
            "device": "cuda",
        },
    )
    res_r, act_r = gate_regression.promote("detector_text@1.1.0-lora-finetuned")
    assert res_r.passed is False and act_r is None
    assert any(c.name == "staged_eval_regression" and not c.passed for c in res_r.checks)

    # 3. Latency & VRAM budget exceeded
    gate_budget = PromotionGate(
        registry,
        evaluator_fn=lambda _e, _b: {
            "n_samples": 16,
            "auroc": 0.97,
            "accuracy": 0.94,
            "calibrated_ece": 0.05,
            "avg_latency_ms": 850.0,  # > 500 ms limit on cuda
            "p95_latency_ms": 1400.0,  # > 1000 ms limit
            "peak_ram_mb": 1500.0,
            "peak_vram_mb": 5200.0,  # > 4096 MB limit
            "device": "cuda",
        },
    )
    res_b, act_b = gate_budget.promote("detector_text@1.1.0-lora-finetuned")
    assert res_b.passed is False and act_b is None
    assert any(c.name == "latency_and_memory_budget" and not c.passed for c in res_b.checks)

    # Direct activate_entry with failing gate must raise PromotionBlockedError
    with pytest.raises(PromotionBlockedError):
        registry.activate_entry("detector_text@1.1.0-lora-finetuned", res_b.to_dict(), {})

    # Active entry & manifest untouched throughout all rejections
    assert registry.get_active_entry("detector_text")["entry_id"] == "detector_text@1.0.0-asis"  # type: ignore[index]


def test_promote_updates_manifest_atomically_and_rollback_preserves_reliability(tmp_path: Path):
    root, registry = _build_isolated_workspace(tmp_path)
    manifest_path = root / "capability_manifests" / "detector_text.json"
    orig_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    gate = PromotionGate(
        registry,
        evaluator_fn=lambda _e, _b: {
            "n_samples": 16,
            "auroc": 0.975,
            "accuracy": 0.9375,
            "f1": 0.9412,
            "tpr_at_1pct_fpr": 0.875,
            "calibrated_ece": 0.0412,
            "avg_latency_ms": 210.4,
            "p95_latency_ms": 480.2,
            "peak_ram_mb": 1920.5,
            "peak_vram_mb": 1950.0,
            "device": "cuda",
            "eval_manifest": "eval/data/text/text_eval_manifest.jsonl",
        },
    )
    res, activation = gate.promote(
        "detector_text@1.1.0-lora-finetuned",
        reason="Promote LoRA checkpoint after passing all 5 gates",
    )
    assert res.passed is True
    assert activation is not None
    assert activation["to_entry_id"] == "detector_text@1.1.0-lora-finetuned"
    assert registry.get_active_entry("detector_text")["entry_id"] == "detector_text@1.1.0-lora-finetuned"  # type: ignore[index]
    assert registry.get_entry("detector_text@1.0.0-asis")["status"] == "archived"

    promoted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=promoted_manifest, schema=DETECTOR_MANIFEST_SCHEMA)
    assert promoted_manifest["version"] == "desklib-v1.01-lora-finetuned-fp16"
    assert promoted_manifest["registry_entry_id"] == "detector_text@1.1.0-lora-finetuned"
    assert promoted_manifest["performance"]["avg_latency_ms"] == 210.4
    assert promoted_manifest["model_metadata"]["license"] == "MIT"
    assert promoted_manifest["model_metadata"]["backbone"] == "microsoft/deberta-v3-large"

    # Simulate reliability feedback loop writing observed_reliability while LoRA was active
    promoted_manifest["observed_reliability"] = {
        "updated_at": "2026-11-24T18:00:00+00:00",
        "window_size": 50,
        "revision": 3,
        "overall": {
            "sample_count": 12,
            "rolling_reliability": 0.89,
            "status": "reliable",
        },
    }
    manifest_path.write_text(json.dumps(promoted_manifest, indent=2), encoding="utf-8")

    # Rollback to as-is Desklib
    rb = registry.rollback("detector_text", reason="Verify clean rollback")
    assert rb["rolled_back_from"] == "detector_text@1.1.0-lora-finetuned"
    assert rb["restored_to"] == "detector_text@1.0.0-asis"
    assert registry.get_active_entry("detector_text")["entry_id"] == "detector_text@1.0.0-asis"  # type: ignore[index]
    assert registry.get_entry("detector_text@1.1.0-lora-finetuned")["status"] == "rolled_back"

    restored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=restored_manifest, schema=DETECTOR_MANIFEST_SCHEMA)
    assert restored_manifest["version"] == orig_manifest["version"]
    assert restored_manifest["performance"] == orig_manifest["performance"]
    assert "registry_entry_id" not in restored_manifest
    # Live feedback data preserved across rollback!
    assert restored_manifest["observed_reliability"]["revision"] == 3

    actions = [ev["action"] for ev in registry.data["promotion_history"]]
    assert actions[-2:] == ["promote", "rollback"]
