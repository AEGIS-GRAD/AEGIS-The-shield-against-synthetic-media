"""
test_planner_pipeline.py — Unit and integration tests for Task 1 LLM planner pipeline
======================================================================================
Verifies:
1. Switchable planning modes via configuration and request parameter/header.
2. Rule-based orchestrator retained as control condition for RQ1 evaluation.
3. LLM-driven planning integration using manifests, eligibility, and telemetry grounding.
4. Plan validation rules and graceful fallback to rule-based baseline on error/timeout.
5. FastAPI /health and /orchestrate endpoints behavior in both modes.
"""

from __future__ import annotations

import io
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from models import InputMetadata, DetectorResult, DetectorEvidence
from planner import (
    resolve_planner_mode,
    validate_plan,
    plan_detectors,
    PlanningResult,
    REQUIRED_PLAN_KEYS,
)
from main import app


# ---------------------------------------------------------------------------
# Suite 1: Configuration & Feature Flag Mode Resolution
# ---------------------------------------------------------------------------

def test_resolve_planner_mode_defaults():
    # When no override is given, defaults to configured mode ("llm")
    with patch.dict("os.environ", {}, clear=False):
        mode = resolve_planner_mode(None)
        assert mode in ("llm", "rule_based")


def test_resolve_planner_mode_env_switch():
    with patch.dict("os.environ", {"PLANNER_MODE": "rule"}):
        assert resolve_planner_mode(None) == "rule_based"

    with patch.dict("os.environ", {"PLANNER_MODE": "rule_based"}):
        assert resolve_planner_mode(None) == "rule_based"

    with patch.dict("os.environ", {"PLANNER_MODE": "llm"}):
        assert resolve_planner_mode(None) == "llm"

    with patch.dict("os.environ", {"AEGIS_PLANNER_MODE": "baseline"}):
        assert resolve_planner_mode(None) == "rule_based"


def test_resolve_planner_mode_explicit_override():
    assert resolve_planner_mode("rule") == "rule_based"
    assert resolve_planner_mode("rule_based") == "rule_based"
    assert resolve_planner_mode("llm") == "llm"


# ---------------------------------------------------------------------------
# Suite 2: Rule-Based Baseline (Control Condition)
# ---------------------------------------------------------------------------

def test_rule_based_mode_control_condition():
    # Video with audio
    meta_multimodal = InputMetadata(
        filename="interview.mp4",
        modality="video",
        has_audio=True,
        duration_seconds=10.0,
    )
    res = plan_detectors(meta_multimodal, mode="rule_based")
    assert res.planner_mode == "rule_based"
    assert res.fallback is False
    assert set(res.detectors_to_call) == {"video-classifier", "rppg", "aasist", "syncnet"}
    assert res.plan is None

    # Audio only
    meta_audio = InputMetadata(
        filename="speech.wav",
        modality="audio",
        has_audio=True,
        duration_seconds=5.0,
    )
    res_audio = plan_detectors(meta_audio, mode="rule_based")
    assert res_audio.detectors_to_call == ["aasist"]
    assert res_audio.fallback is False

    # Silent video
    meta_silent = InputMetadata(
        filename="silent.mp4",
        modality="video",
        has_audio=False,
        duration_seconds=6.0,
    )
    res_silent = plan_detectors(meta_silent, mode="rule_based")
    assert set(res_silent.detectors_to_call) == {"video-classifier", "rppg"}


# ---------------------------------------------------------------------------
# Suite 3: Plan Validation
# ---------------------------------------------------------------------------

def test_validate_plan_valid():
    valid_plan = {
        "plan_version": "3",
        "stages": [{"stage": 1, "run": ["video-classifier", "aasist"], "mode": "parallel"}],
        "skipped": [{"detector_name": "rppg", "reason": "budget"}],
        "coverage_warnings": [],
        "estimated_latency_s": 7.3,
        "rationale": "Selected top detectors within budget.",
    }
    problems = validate_plan(valid_plan, eligible_ids={"video-classifier", "aasist", "rppg"}, budget_s=10.0)
    assert problems == []


def test_validate_plan_missing_schema_keys():
    incomplete_plan = {
        "plan_version": "3",
        "stages": [],
    }
    problems = validate_plan(incomplete_plan, eligible_ids={"aasist"}, budget_s=10.0)
    assert any("missing schema keys" in p for p in problems)


def test_validate_plan_ineligible_or_invented_detectors():
    bad_plan = {
        "plan_version": "3",
        "stages": [{"stage": 1, "run": ["video-classifier", "invented-detector"], "mode": "parallel"}],
        "skipped": [],
        "coverage_warnings": [],
        "estimated_latency_s": 5.0,
        "rationale": "test",
    }
    problems = validate_plan(bad_plan, eligible_ids={"video-classifier"}, budget_s=10.0)
    assert any("used ineligible or non-existent detector ids" in p for p in problems)


def test_validate_plan_exceeds_budget():
    over_budget_plan = {
        "plan_version": "3",
        "stages": [{"stage": 1, "run": ["video-classifier"], "mode": "parallel"}],
        "skipped": [],
        "coverage_warnings": [],
        "estimated_latency_s": 25.0,
        "rationale": "test",
    }
    problems = validate_plan(over_budget_plan, eligible_ids={"video-classifier"}, budget_s=10.0)
    assert any("exceeds budget ceiling" in p for p in problems)


# ---------------------------------------------------------------------------
# Suite 4: LLM Planning & Graceful Fallback
# ---------------------------------------------------------------------------

def test_llm_mode_with_mock_reference_planner():
    meta = InputMetadata(
        filename="interview.mp4",
        modality="video",
        has_audio=True,
        duration_seconds=10.0,
    )
    res = plan_detectors(meta, mode="llm", budget_s=20.0, mock_llm=True)
    assert res.planner_mode == "llm"
    assert res.fallback is False
    assert res.plan is not None
    assert "plan_version" in res.plan
    assert len(res.detectors_to_call) > 0
    # Must only contain known eligible detectors
    for det in res.detectors_to_call:
        assert det in ("video-classifier", "rppg", "aasist", "syncnet")


def test_llm_mode_fallback_when_api_key_missing():
    meta = InputMetadata(
        filename="interview.mp4",
        modality="video",
        has_audio=True,
        duration_seconds=10.0,
    )
    # Ensure no API key and no mock flag
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "", "AEGIS_MOCK_LLM": ""}, clear=False):
        res = plan_detectors(meta, mode="llm", mock_llm=False)
        assert res.planner_mode == "llm"
        assert res.fallback is True
        assert res.fallback_reason is not None
        assert "LLM call failed" in res.fallback_reason
        # Fallback must match rule-based detectors
        assert set(res.detectors_to_call) == {"video-classifier", "rppg", "aasist", "syncnet"}
        assert res.plan["plan_version"] == "fallback-rule-baseline"


def test_llm_mode_fallback_when_llm_returns_invalid_plan():
    meta = InputMetadata(
        filename="speech.wav",
        modality="audio",
        has_audio=True,
        duration_seconds=4.0,
    )
    # Mock call_llm returning an invalid plan that invents detectors
    with patch("planner.call_llm") as mock_call:
        mock_call.return_value = (
            {
                "plan_version": "3",
                "stages": [{"stage": 1, "run": ["fake-hallucinated-model"], "mode": "parallel"}],
                "skipped": [],
                "coverage_warnings": [],
                "estimated_latency_s": 1.0,
                "rationale": "test",
            },
            "mock-hallucinating-llm",
            0.1,
        )
        res = plan_detectors(meta, mode="llm")
        assert res.fallback is True
        assert "used ineligible or non-existent detector ids" in res.fallback_reason
        assert res.detectors_to_call == ["aasist"]  # Fell back to rule baseline


# ---------------------------------------------------------------------------
# Suite 5: Integration with FastAPI Endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint_reports_planner_mode(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "planner_mode" in data
    assert data["planner_mode"] in ("llm", "rule_based")


@patch("main.call_all_detectors")
@patch("main.get_input_metadata")
def test_orchestrate_rule_based_mode(mock_meta, mock_dispatch, client):
    mock_meta.return_value = InputMetadata(
        filename="test.mp4",
        modality="video",
        has_audio=True,
        duration_seconds=5.0,
    )
    mock_dispatch.return_value = [
        DetectorResult(
            detector="video-classifier",
            status="ok",
            confidence=0.8,
            raw_score=0.8,
            latency_ms=100,
            model_version="v1",
            evidence=DetectorEvidence(claim="Fake detected"),
        )
    ]

    dummy_file = ("test.mp4", io.BytesIO(b"fake mp4 content"), "video/mp4")
    res = client.post(
        "/orchestrate?planner_mode=rule_based",
        files={"file": dummy_file},
        headers={"X-API-Key": "dev_default_key"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["planner_mode"] == "rule_based"
    assert data["plan"] is None
    assert data["fallback"] is False
    assert set(data["detectors_called"]) == {"video-classifier", "rppg", "aasist", "syncnet"}


@patch("main.call_all_detectors")
@patch("main.get_input_metadata")
def test_orchestrate_header_mode_override(mock_meta, mock_dispatch, client):
    mock_meta.return_value = InputMetadata(
        filename="audio.wav",
        modality="audio",
        has_audio=True,
        duration_seconds=3.0,
    )
    mock_dispatch.return_value = []

    dummy_file = ("audio.wav", io.BytesIO(b"fake wav content"), "audio/wav")
    res = client.post(
        "/orchestrate",
        files={"file": dummy_file},
        headers={
            "X-API-Key": "dev_default_key",
            "X-Planner-Mode": "rule_based",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["planner_mode"] == "rule_based"
    assert data["detectors_called"] == ["aasist"]


@patch("main.call_all_detectors")
@patch("main.get_input_metadata")
def test_orchestrate_llm_mode_with_fallback(mock_meta, mock_dispatch, client):
    mock_meta.return_value = InputMetadata(
        filename="video.mp4",
        modality="video",
        has_audio=False,
        duration_seconds=8.0,
    )
    mock_dispatch.return_value = []

    dummy_file = ("video.mp4", io.BytesIO(b"fake video content"), "video/mp4")
    # With no OpenRouter API key set, LLM mode gracefully falls back to rule-based baseline
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "", "AEGIS_MOCK_LLM": ""}):
        res = client.post(
            "/orchestrate?planner_mode=llm",
            files={"file": dummy_file},
            headers={"X-API-Key": "dev_default_key"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["planner_mode"] == "llm"
        assert data["fallback"] is True
        assert data["fallback_reason"] is not None
        assert set(data["detectors_called"]) == {"video-classifier", "rppg"}
