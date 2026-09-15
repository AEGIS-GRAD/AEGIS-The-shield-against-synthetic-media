import base64
import os
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_endpoint():
    """Validates /health endpoint response shape and readiness."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "syncnet"
    assert data["model_loaded"] is True
    assert "model_version" in data
    assert "device" in data


def test_metrics_endpoint():
    """Validates Prometheus /metrics endpoint is exposed."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "detector_inference_calls_total" in response.text


def test_detect_silent_video_returns_not_applicable(sample_clips):
    """Crucial requirement: silent video with no audio track must return 'not_applicable'

    and never fail or return a misleading score.
    """
    silent_file = sample_clips["silent"]
    assert os.path.exists(silent_file)

    payload = {
        "job_id": "test-silent-job-001",
        "modality": "video",
        "payload": silent_file,
    }
    response = client.post("/detect", json=payload)
    assert response.status_code == 200

    data = response.json()
    # Schema validation
    assert data["job_id"] == "test-silent-job-001"
    assert "confidence" in data
    assert data["confidence"] == 0.5
    assert data["raw_score"] == 0.0
    assert "latency_ms" in data
    assert data["model_version"] == "syncnet-v1.3"
    assert "evidence" in data
    assert "claim" in data["evidence"]
    assert "flags" in data["evidence"]

    # Explicit not_applicable checks
    assert "not_applicable" in data["evidence"]["flags"]
    assert "No audio track" in data["evidence"]["claim"]


def test_detect_multipart_file_upload(sample_clips):
    """Validates multipart/form-data upload compatibility."""
    silent_file = sample_clips["silent"]
    with open(silent_file, "rb") as f:
        response = client.post(
            "/detect",
            files={"file": ("silent_sample.mp4", f, "video/mp4")},
            data={"job_id": "form-upload-job-123"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "form-upload-job-123"
    assert "not_applicable" in data["evidence"]["flags"]


def test_detect_base64_payload(sample_clips):
    """Validates JSON request with base64 encoded video payload."""
    silent_file = sample_clips["silent"]
    with open(silent_file, "rb") as f:
        b64_content = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "job_id": "test-b64-job-456",
        "modality": "video",
        "payload": b64_content,
    }
    response = client.post("/detect", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "test-b64-job-456"
    assert "not_applicable" in data["evidence"]["flags"]


def test_detect_dubbed_vs_authentic(sample_clips):
    """Sanity-checks that dubbed/desynchronized audio produces higher synthetic confidence

    or sync flags than authentic in-sync audio.
    """
    authentic_clip = sample_clips["authentic"]
    dubbed_clip = sample_clips["dubbed"]

    resp_auth = client.post(
        "/detect",
        json={"job_id": "auth-job", "modality": "video", "payload": authentic_clip},
    )
    assert resp_auth.status_code == 200
    data_auth = resp_auth.json()

    resp_dubbed = client.post(
        "/detect",
        json={"job_id": "dubbed-job", "modality": "video", "payload": dubbed_clip},
    )
    assert resp_dubbed.status_code == 200
    data_dubbed = resp_dubbed.json()

    # Both responses conform to schema
    for res in [data_auth, data_dubbed]:
        assert "confidence" in res
        assert 0.0 <= res["confidence"] <= 1.0
        assert "raw_score" in res
        assert "latency_ms" in res
        assert "model_version" in res
        assert "evidence" in res

    # If audio extraction was available, verify separation
    if "not_applicable" not in data_auth["evidence"]["flags"]:
        # Dubbed clip should have greater or equal synthetic confidence than authentic clip
        assert data_dubbed["confidence"] >= data_auth["confidence"]


def test_detect_malformed_requests():
    """Validates proper error codes on malformed requests."""
    # Missing fields
    resp = client.post("/detect", json={"invalid": "payload"})
    assert resp.status_code == 400

    # Wrong modality
    resp = client.post("/detect", json={"job_id": "1", "modality": "audio", "payload": "xyz"})
    assert resp.status_code == 400
