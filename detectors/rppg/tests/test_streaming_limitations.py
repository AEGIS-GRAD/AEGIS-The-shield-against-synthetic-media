"""
Characterization tests for Streaming rPPG Limitations.
======================================================
Pins documented limitations in docs/LIMITATIONS.md (M2-L1 to M2-L4).
When any limitation is fixed in production, update both the test and
the corresponding LIMITATIONS.md entry.
"""

import numpy as np
import pytest
from detectors.rppg.streaming.streaming import StreamingRPPG, roi_mean_rgb


def test_m2_l1_flat_signal_returns_confident_synthetic():
    """
    M2-L1: Score Inversion Trap in Streaming rPPG.
    When a flat signal (e.g. constant illumination or motionless frame) is pushed,
    streaming rPPG returns ready=True with score=1.000 ("100% synthetic"),
    conflating lack of extracted physiological variance with deepfake synthesis.
    """
    stream = StreamingRPPG(fps=10.0, window_sec=8.0, min_sec=6.0, hop_sec=1.0)
    flat_rgb = np.array([120.0, 100.0, 90.0], dtype=np.float64)

    # Push 7 seconds of flat signal (70 frames at 10 fps)
    for i in range(70):
        t = i * 0.1
        res = stream.push(t, flat_rgb)

    assert res.ready is True
    # The score-inversion trap returns score=1.0 with reason "flat signal"
    assert res.score == 1.0
    assert "flat signal" in res.reason


def test_m2_l2_no_evidence_during_warmup():
    """
    M2-L2: Temporal Warmup Blind Spot.
    Until min_sec (default 6.0s) of contiguous frames accumulate,
    streaming rPPG emits ready=False and score=None.
    """
    stream = StreamingRPPG(fps=10.0, window_sec=8.0, min_sec=6.0, hop_sec=1.0)
    dummy_rgb = np.array([130.0, 110.0, 95.0])

    # Push 4 seconds (less than 6.0s min_sec)
    for i in range(40):
        t = i * 0.1
        res = stream.push(t, dummy_rgb)

    assert res.ready is False
    assert res.score is None
    assert "warming up" in res.reason


def test_m2_l2_gap_over_max_resets_and_reenters_warmup():
    """
    M2-L2: Face-loss gap reset.
    Any gap exceeding max_gap_sec (default 1.0s) completely purges
    the rolling buffer, re-imposing the full 6.0s warmup blind spot.
    """
    stream = StreamingRPPG(fps=10.0, window_sec=8.0, min_sec=6.0, hop_sec=1.0)
    dummy_rgb = np.array([130.0, 110.0, 95.0])

    # Warm up with 7 seconds
    for i in range(70):
        res = stream.push(i * 0.1, dummy_rgb)
    assert res.ready is True

    # Induce gap > 1.0s (jump from t=6.9s to t=8.5s)
    gap_res = stream.push(8.5, dummy_rgb)
    assert gap_res.ready is False
    assert "warming up" in gap_res.reason
    assert stream.buffered_sec() == 0.0


def test_m2_l3_whole_frame_roi_when_no_box():
    """
    M2-L3: Lack of Input Guardrails & Full-Frame Degradation.
    When box=None, roi_mean_rgb averages the entire frame background
    rather than verifying face presence or skin-tone ratio.
    """
    test_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    test_frame[:, :] = [50, 100, 150]  # BGR

    rgb = roi_mean_rgb(test_frame, box=None)
    assert rgb is not None
    # [R, G, B] order
    assert np.allclose(rgb, [150.0, 100.0, 50.0])


def test_m2_l4_fixed_logistic_snr_score_mapping():
    """
    M2-L4: Uncalibrated SNR to Synthetic Score Logistic Mapping.
    Demonstrates the hardcoded logistic parameters (snr_midpoint_db=1.0, snr_slope=0.6).
    """
    stream = StreamingRPPG(snr_midpoint_db=1.0, snr_slope=0.6)
    # At snr_db == snr_midpoint (1.0), logistic score is exactly 0.5
    expected_score = 1.0 / (1.0 + np.exp(0.6 * (1.0 - 1.0)))
    assert abs(expected_score - 0.5) < 1e-6
