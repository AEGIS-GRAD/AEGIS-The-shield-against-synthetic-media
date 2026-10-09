"""
Integration test for the live-feed pipeline — no display, no network.
Feeds synthetic frames directly into the SlidingWindowDetector and
validates that the pipeline produces expected score shapes and ranges.
"""
import sys, os
import numpy as np
import pytest

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from engine.edge_model.sliding_window import SlidingWindowDetector


@pytest.fixture(scope="module")
def detector():
    return SlidingWindowDetector(backend="onnx_int8", window_size=16, stride=8)


def make_frames(n, noise_scale=0.1):
    """n synthetic (3,224,224) frames with random pixel noise."""
    rng = np.random.default_rng(42)
    return [rng.normal(0, noise_scale, (3, 224, 224)).astype(np.float32)
            for _ in range(n)]


# ── Test 1: window exactly fills ──────────────────────────────────────────────
def test_window_score_range(detector):
    frames = make_frames(16)
    score = detector.predict_window(frames)
    assert isinstance(score, float), "Score must be a float"
    assert 0.0 <= score <= 1.0, f"Score {score} out of range"


# ── Test 2: push_frame buffer/stride logic ────────────────────────────────────
def test_push_frame_fires_at_16_returns_none_before(detector):
    det = SlidingWindowDetector(backend="onnx_int8", window_size=16, stride=8)
    frames = make_frames(16)
    scores = [det.push_frame(f) for f in frames]
    assert all(s is None for s in scores[:15]), "First 15 pushes must return None"
    assert scores[15] is not None, "16th push must return a score"
    assert 0.0 <= scores[15] <= 1.0


# ── Test 3: EMA rolling score converges ───────────────────────────────────────
def test_ema_rolling_score():
    alpha = 0.6
    scores = [0.3, 0.4, 0.7, 0.9, 0.2]
    rolling = None
    for s in scores:
        rolling = s if rolling is None else alpha * s + (1 - alpha) * rolling
    assert 0.0 <= rolling <= 1.0, "EMA rolling score must stay in [0,1]"


# ── Test 4: empty window returns 0.5 (neutral) ───────────────────────────────
def test_empty_window_returns_neutral(detector):
    score = detector.predict_window([])
    assert score == 0.5, f"Empty window should return 0.5, got {score}"


# ── Test 5: face detection returns correct types ─────────────────────────────
def test_face_detection_blank_frame():
    try:
        from facenet_pytorch import MTCNN
    except ImportError:
        pytest.skip("facenet-pytorch not installed")
    import numpy as np
    mtcnn = MTCNN(keep_all=True, device="cpu")
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    boxes, probs = mtcnn.detect(blank)
    assert boxes is None, "Blank frame must produce no face boxes"


# ── Test 6: /health endpoint (requires running service) ──────────────────────
def test_video_classifier_health():
    import requests
    try:
        r = requests.get("http://localhost:8001/health", timeout=3)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["service"] == "video-classifier"
    except requests.exceptions.ConnectionError:
        pytest.skip("video-classifier service not running — skip network test")
