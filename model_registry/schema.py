"""JSON Schema definitions for the AEGIS versioned model registry."""

from __future__ import annotations

from typing import Any, Dict

import jsonschema

_SHA256_PATTERN = "^[0-9a-f]{64}$"

ENTRY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": [
        "entry_id",
        "detector_name",
        "modality",
        "version",
        "model_version",
        "status",
        "checkpoint",
        "calibration",
        "manifest_path",
        "budgets",
        "regression_policy",
        "measured_metrics",
        "registered_at",
    ],
    "additionalProperties": True,
    "properties": {
        "entry_id": {"type": "string", "minLength": 3},
        "detector_name": {"type": "string", "minLength": 1},
        "modality": {"type": "string", "enum": ["video", "audio", "image", "text"]},
        "version": {"type": "string", "minLength": 1},
        "model_version": {"type": "string", "minLength": 1},
        "status": {
            "type": "string",
            "enum": ["staging", "active", "archived", "rolled_back"],
        },
        "description": {"type": "string"},
        "checkpoint": {
            "type": "object",
            "required": ["path", "format", "sha256", "size_bytes", "source_type"],
            "additionalProperties": True,
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "format": {
                    "type": "string",
                    "enum": ["safetensors", "pytorch_weights_only", "onnx", "lora_adapter"],
                },
                "sha256": {"type": "string", "pattern": _SHA256_PATTERN},
                "size_bytes": {"type": "integer", "minimum": 1},
                "source_type": {
                    "type": "string",
                    "enum": ["tracked_git", "huggingface_hub", "local_staged"],
                },
                "hf_repo": {"type": "string"},
                "hf_revision": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                "adapter_path": {"type": ["string", "null"]},
                "adapter_sha256": {"type": ["string", "null"], "pattern": _SHA256_PATTERN},
                "load_config": {"type": "object"},
            },
        },
        "calibration": {
            "type": "object",
            "required": ["path", "sha256", "calibrator_type", "preferred_method"],
            "additionalProperties": True,
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "sha256": {"type": "string", "pattern": _SHA256_PATTERN},
                "calibrator_type": {"type": "string", "minLength": 1},
                "preferred_method": {"type": "string", "minLength": 1},
                "signal_calibration_path": {"type": ["string", "null"]},
                "signal_calibration_sha256": {
                    "type": ["string", "null"],
                    "pattern": _SHA256_PATTERN,
                },
            },
        },
        "manifest_path": {"type": "string", "minLength": 1},
        "budgets": {
            "type": "object",
            "required": [
                "max_avg_latency_ms",
                "max_p95_latency_ms",
                "max_vram_mb",
                "max_ram_mb",
            ],
            "additionalProperties": True,
            "properties": {
                "max_avg_latency_ms": {"type": "number", "exclusiveMinimum": 0},
                "max_p95_latency_ms": {"type": "number", "exclusiveMinimum": 0},
                "max_vram_mb": {"type": "number", "minimum": 0, "maximum": 8192},
                "max_ram_mb": {"type": "number", "exclusiveMinimum": 0},
                "cpu_max_avg_latency_ms": {"type": ["number", "null"], "exclusiveMinimum": 0},
                "cpu_max_p95_latency_ms": {"type": ["number", "null"], "exclusiveMinimum": 0},
            },
        },
        "regression_policy": {
            "type": "object",
            "required": [
                "eval_manifest",
                "min_auroc",
                "max_auroc_drop",
                "min_accuracy",
                "max_accuracy_drop",
            ],
            "additionalProperties": True,
            "properties": {
                "eval_manifest": {"type": "string", "minLength": 1},
                "min_auroc": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "max_auroc_drop": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "min_accuracy": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "max_accuracy_drop": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        },
        "measured_metrics": {"type": "object"},
        "registered_at": {"type": "string", "minLength": 10},
    },
}

HISTORY_EVENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": [
        "timestamp",
        "action",
        "detector_name",
        "from_entry_id",
        "to_entry_id",
        "gate_passed",
        "reason",
    ],
    "additionalProperties": True,
    "properties": {
        "timestamp": {"type": "string", "minLength": 10},
        "action": {"type": "string", "enum": ["register", "gate", "promote", "rollback"]},
        "detector_name": {"type": "string", "minLength": 1},
        "from_entry_id": {"type": ["string", "null"]},
        "to_entry_id": {"type": ["string", "null"]},
        "gate_passed": {"type": ["boolean", "null"]},
        "reason": {"type": "string"},
        "gate_summary": {"type": ["object", "null"]},
        "manifest_snapshot": {"type": ["object", "null"]},
    },
}

REGISTRY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": [
        "schema_version",
        "updated_at",
        "active",
        "entries",
        "promotion_history",
    ],
    "additionalProperties": True,
    "properties": {
        "schema_version": {"type": "string", "const": "1.0"},
        "updated_at": {"type": "string", "minLength": 10},
        "active": {
            "type": "object",
            "additionalProperties": {"type": "string", "minLength": 1},
        },
        "entries": {
            "type": "object",
            "additionalProperties": ENTRY_SCHEMA,
        },
        "promotion_history": {
            "type": "array",
            "items": HISTORY_EVENT_SCHEMA,
        },
    },
}


class RegistryValidationError(ValueError):
    """Raised when registry data violates REGISTRY_SCHEMA."""


def validate_registry_data(data: Dict[str, Any]) -> None:
    """Validates a full registry payload against REGISTRY_SCHEMA."""
    try:
        jsonschema.validate(instance=data, schema=REGISTRY_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise RegistryValidationError(f"Registry schema validation failed: {exc.message}") from exc

    active = data.get("active", {})
    entries = data.get("entries", {})
    for detector_name, entry_id in active.items():
        if entry_id not in entries:
            raise RegistryValidationError(
                f"Active pointer for '{detector_name}' references missing entry '{entry_id}'."
            )
        if entries[entry_id]["detector_name"] != detector_name:
            raise RegistryValidationError(
                f"Active pointer '{detector_name}' points to mismatched detector "
                f"'{entries[entry_id]['detector_name']}'."
            )


def validate_entry_data(entry: Dict[str, Any]) -> None:
    """Validates a single entry payload against ENTRY_SCHEMA."""
    try:
        jsonschema.validate(instance=entry, schema=ENTRY_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise RegistryValidationError(f"Registry entry validation failed: {exc.message}") from exc
