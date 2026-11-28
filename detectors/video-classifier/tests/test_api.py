import os
import sys
import tempfile
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

# Add parent directory to path so the IDE can resolve local imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import app

client = TestClient(app)


def test_health_endpoint():
    """Test GET /health endpoint returns 200 OK and healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "video-classifier"


def create_dummy_video_file() -> str:
    """Helper to generate a short synthetic MP4 video file for testing."""
    temp_video = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    temp_path = temp_video.name
    temp_video.close()

    height, width = 300, 300
    fps = 10
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(temp_path, fourcc, fps, (width, height))

    # Generate 15 synthetic RGB frames
    for i in range(15):
        frame = np.full((height, width, 3), (i * 10) % 255, dtype=np.uint8)
        out.write(frame)

    out.release()
    return temp_path


@pytest.mark.slow
def test_detect_endpoint():
    """Test POST /detect endpoint with a valid video file upload."""
    video_path = create_dummy_video_file()
    try:
        with open(video_path, "rb") as f:
            response = client.post(
                "/detect",
                files={"file": ("test_video.mp4", f, "video/mp4")},
            )

        assert response.status_code == 200
        data = response.json()

        # Validate schema fields
        assert "job_id" in data
        assert isinstance(data["raw_score"], float)
        assert isinstance(data["confidence"], float)
        assert 0.0 <= data["confidence"] <= 1.0
        assert "latency_ms" in data
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)


def test_detect_endpoint_no_file():
    """Test POST /detect without uploading a file returns 400 Bad Request."""
    response = client.post("/detect")
    assert response.status_code == 400


def test_metrics_endpoint():
    """Validates Prometheus /metrics endpoint is mounted and exposes inference metrics."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "detector_inference_latency_seconds" in response.text
    assert "detector_inference_calls_total" in response.text


@pytest.mark.slow
def test_detect_returns_frame_scores():
    """Task 4: /detect must return non-empty per-frame fake probabilities."""
    video_path = create_dummy_video_file()
    try:
        with open(video_path, "rb") as f:
            resp = client.post("/detect", files={"file": ("v.mp4", f, "video/mp4")})
        assert resp.status_code == 200
        data = resp.json()
        evidence = data.get("evidence", {})
        assert "frame_scores" in evidence, "Missing frame_scores in evidence"
        fs = evidence["frame_scores"]
        assert isinstance(fs, list) and len(fs) > 0
        assert all(isinstance(x, float) and 0.0 <= x <= 1.0 for x in fs)
        assert data.get("frame_scores") == fs
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)


@pytest.mark.slow
def test_detect_returns_frame_evidence_with_heatmaps():
    """Task 4: /detect must return per-frame evidence entries with Grad-CAM field."""
    video_path = create_dummy_video_file()
    try:
        with open(video_path, "rb") as f:
            resp = client.post("/detect", files={"file": ("v.mp4", f, "video/mp4")})
        assert resp.status_code == 200
        data = resp.json()
        fe = data["evidence"].get("frame_evidence", [])
        assert isinstance(fe, list) and len(fe) > 0
        for entry in fe:
            assert "frame_index" in entry
            assert "fake_score" in entry
            assert 0.0 <= entry["fake_score"] <= 1.0
            assert "heatmap_b64" in entry
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)


@pytest.mark.slow
def test_detect_evidence_claim_is_human_readable():
    """Task 4: /detect evidence claim must be a full human-readable sentence."""
    video_path = create_dummy_video_file()
    try:
        with open(video_path, "rb") as f:
            resp = client.post("/detect", files={"file": ("v.mp4", f, "video/mp4")})
        assert resp.status_code == 200
        claim = resp.json()["evidence"]["claim"]
        assert len(claim.split()) >= 8, f"Claim too short: {claim!r}"
        assert claim.rstrip().endswith("."), f"Claim must end with '.': {claim!r}"
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)


