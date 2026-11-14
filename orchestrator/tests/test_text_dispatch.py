"""Tests verifying orchestrator manifest loading, dispatch URL resolution, and telemetry wiring for detector_text."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_APP = REPO_ROOT / "orchestrator" / "app"
if str(ORCH_APP) not in sys.path:
    sys.path.insert(0, str(ORCH_APP))

import dispatch  # noqa: E402
from manifest_loader import load_all_manifests  # noqa: E402
from telemetry_client import BASELINE_LATENCIES_MS, JOB_TO_DETECTOR  # noqa: E402


def test_text_manifest_loaded_and_advertises_text_modality():
    manifests = {
        m["detector_name"]: m for m in load_all_manifests(REPO_ROOT / "capability_manifests")
    }
    assert "detector_text" in manifests
    m = manifests["detector_text"]
    assert m["modality"] == ["text"]
    assert ".txt" in m["input_constraints"]["supported_formats"]
    assert m["input_constraints"]["requires_audio"] is False


def test_dispatch_resolves_detector_text_service_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DETECTOR_DETECTOR_TEXT_URL", raising=False)
    monkeypatch.delenv("DETECTOR_TEXT_URL", raising=False)
    url = dispatch._service_url("detector_text")
    assert url in {"http://detector_text:8000", "https://detector_text:8000"}

    monkeypatch.setenv("DETECTOR_DETECTOR_TEXT_URL", "http://127.0.0.1:8005")
    assert dispatch._service_url("detector_text") == "http://127.0.0.1:8005"


def test_telemetry_client_maps_aegis_detector_text():
    assert JOB_TO_DETECTOR["aegis_detector_text"] == "detector_text"
    assert JOB_TO_DETECTOR["aegis_detector_detector_text"] == "detector_text"
    assert "detector_text" in BASELINE_LATENCIES_MS
    assert BASELINE_LATENCIES_MS["detector_text"]["avg"] == pytest.approx(225.65)
