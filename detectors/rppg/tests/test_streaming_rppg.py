"""No display, no network, no real video: synthetic live feed."""
import os, sys
import numpy as np
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from detectors.rppg.streaming.streaming import StreamingRPPG
from fastapi.testclient import TestClient
from detectors.rppg.streaming.main import app

FPS = 10.0

def feed(det, seconds, hr_bpm=None, noise=0.15, seed=0, t0=0.0, drop=0.0):
    """Simulate a face colour trace: skin tone + pulse in green + noise."""
    rng = np.random.default_rng(seed); res = None
    for i in range(int(seconds * FPS)):
        t = t0 + i / FPS
        if drop and rng.random() < drop:
            continue                                    # dropped frame
        t += rng.normal(0, 0.005)                       # timestamp jitter
        pulse = 0 if hr_bpm is None else np.sin(2 * np.pi * hr_bpm / 60 * t)
        rgb = np.array([150, 110, 90]) + noise * rng.normal(size=3) \
              + np.array([0.15, 0.6, 0.2]) * pulse
        res = det.push(t, rgb)
    return res

def test_not_ready_until_min_sec():
    r = feed(StreamingRPPG(fps=FPS), 3, hr_bpm=72)
    assert r.ready is False and r.score is None

def test_real_pulse_detected_low_score():
    r = feed(StreamingRPPG(fps=FPS), 15, hr_bpm=72)
    assert r.ready and abs(r.hr_bpm - 72) < 4, r
    assert r.score < 0.3, r

def test_no_pulse_high_score():
    r = feed(StreamingRPPG(fps=FPS), 15, hr_bpm=None)
    assert r.ready and r.score > 0.6, r

def test_survives_dropped_frames():
    r = feed(StreamingRPPG(fps=FPS), 20, hr_bpm=90, drop=0.2)
    assert r.ready and abs(r.hr_bpm - 90) < 5, r

def test_gap_resets_buffer():
    d = StreamingRPPG(fps=FPS)
    feed(d, 12, hr_bpm=72)
    r = d.push(30.0, [150, 110, 90])                    # 18 s gap
    assert r.ready is False and d.buffered_sec() == 0.0

def test_bad_input_ignored():
    d = StreamingRPPG(fps=FPS)
    d.push(0.0, [float("nan"), 1, 1]); d.push(0.1, [1, 2])
    assert d.buffered_sec() == 0.0

def test_scores_in_range_over_stream():
    d = StreamingRPPG(fps=FPS); seen = []
    rng = np.random.default_rng(1)
    for i in range(300):
        r = d.push(i / FPS, [150, 110 + rng.normal(), 90])
        if r.ready: seen.append(r.score)
    assert seen and all(0.0 <= s <= 1.0 for s in seen)

def test_service_health_and_stream():
    c = TestClient(app)
    h = c.get("/health").json()
    assert h["status"] == "healthy" and h["service"] == "rppg"
    rng = np.random.default_rng(3); last = None
    for i in range(160):
        t = i / FPS
        g = 110 + 0.6 * np.sin(2 * np.pi * 1.2 * t) + 0.3 * rng.normal()
        last = c.post("/stream/s1/sample", json={"t": t, "rgb": [150, g, 90]}).json()
    assert last["ready"] and abs(last["hr_bpm"] - 72) < 4
    assert c.get("/stream/s1/score").json()["ready"]
    assert c.delete("/stream/s1").status_code == 200
    assert c.get("/stream/s1/score").status_code == 404
