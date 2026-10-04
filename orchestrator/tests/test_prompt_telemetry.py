"""
Tests for prompt_builder.py v3 with live telemetry integration
"""

import pytest
from orchestrator.app.prompt_builder import (
    PROMPT_VERSION,
    build_planning_prompt,
    _latency_for,
)
from orchestrator.app.telemetry_client import DetectorTelemetry


def test_prompt_version():
    assert PROMPT_VERSION == "planner-v3.0"


def test_latency_for_with_and_without_telemetry():
    manifest_aasist = {
        "detector_name": "aasist",
        "performance": {"avg_latency_ms": None, "p95_latency_ms": None}
    }

    # 1. Without telemetry -> fallback baseline
    avg, p95, source = _latency_for(manifest_aasist, telemetry=None)
    assert p95 == 334.0
    assert "benchmark fallback" in source

    # 2. With live degraded telemetry -> uses live values & flags DEGRADED
    telemetry = {
        "aasist": DetectorTelemetry(
            detector_name="aasist", status="degraded", p95_latency_ms=8500.0,
            avg_latency_ms=8200.0, ram_usage_mb=210.0, vram_usage_mb=None, calls_count=12,
            source="live_prometheus", degradation_ratio=25.4, up=True, last_updated=0
        )
    }
    avg, p95, source = _latency_for(manifest_aasist, telemetry=telemetry)
    assert p95 == 8500.0
    assert avg == 8200.0
    assert "DEGRADED" in source
    assert "25.4x" in source


def test_prompt_builder_includes_telemetry_section():
    eligible = [
        {"detector_name": "video-classifier", "description": "EfficientNet", "known_failure_modes": [], "performance": {}},
        {"detector_name": "aasist", "description": "AASIST audio", "known_failure_modes": [], "performance": {}},
    ]
    excluded = []
    input_summary = {"modality": "video", "has_audio": True, "duration_seconds": 10.0}

    telemetry = {
        "aasist": DetectorTelemetry(
            detector_name="aasist", status="degraded", p95_latency_ms=8500.0,
            avg_latency_ms=8200.0, ram_usage_mb=210.0, vram_usage_mb=None, calls_count=12,
            source="live_prometheus", degradation_ratio=25.4, up=True, last_updated=0
        )
    }

    prompt = build_planning_prompt(
        eligible=eligible,
        excluded=excluded,
        input_summary=input_summary,
        risk_profile="standard",
        budget_s=10.0,
        telemetry=telemetry,
    )

    assert "# 5. LIVE SYSTEM TELEMETRY (Prometheus Real-Time Load)" in prompt
    assert "aasist" in prompt
    assert "DEGRADED" in prompt
    assert "25.40x" in prompt
    assert "8.50s" in prompt
    assert "Example E — LIVE TELEMETRY DEGRADATION" in prompt
