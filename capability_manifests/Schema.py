DETECTOR_MANIFEST_SCHEMA = {
    "type": "object",
    "required": [
        "detector_name", "modality", "version", "description",
        "input_constraints", "performance", "known_failure_modes",
        "reliability_notes"
    ],
    "properties": {
        "detector_name": {"type": "string"},
        "modality": {
            "type": "array",
            "items": {"type": "string", "enum": ["video", "audio", "image", "text"]}
        },
        "version": {"type": "string"},
        "description": {"type": "string"},
        "input_constraints": {
            "type": "object",
            "required": ["requires_audio", "min_duration_seconds", "supported_formats"],
            "properties": {
                "requires_audio": {"type": "boolean"},
                "min_duration_seconds": {"type": "number"},
                "max_duration_seconds": {"type": ["number", "null"]},
                "supported_formats": {"type": "array", "items": {"type": "string"}}
            }
        },
        "performance": {
            "type": "object",
            "required": ["avg_latency_ms", "measured_on"],
            "properties": {
                "avg_latency_ms": {"type": ["number", "null"]},
                "p95_latency_ms": {"type": ["number", "null"]},
                "avg_ram_usage_mb": {"type": ["number", "null"]},
                "avg_vram_usage_mb": {"type": ["number", "null"]},
                "measured_on": {"type": "string"}
            }
        },
        "known_failure_modes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["condition", "effect", "source"],
                "properties": {
                    "condition": {"type": "string"},
                    "effect": {"type": "string"},
                    "source": {"type": "string"}
                }
            }
        },
        "reliability_notes": {"type": "string"}
    }
}