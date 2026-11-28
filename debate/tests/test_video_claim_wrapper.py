"""
Tests for the extended video-classifier claim wrapper.
Verifies that frame_scores, flagged_range, and heatmap evidence
flow correctly from the detector response into the ForensicClaim.

Run: python -m pytest debate/tests/test_video_claim_wrapper_task4.py -v
"""
import pytest
from debate.claim_wrapper import wrap_detector_response
from debate.schemas import ClaimPolarity, SpatialMetrics

JOB = "job-task4-001"


def vc_with_frames(conf: float, frame_scores: list, flagged_range: str = None,
                   frame_evidence: list = None):
    """Builds a video-classifier response that includes the new Task 4 fields."""
    flags = (
        ["high_fake_probability"] if conf > 0.65
        else (["authentic_frames"] if conf < 0.35 else ["borderline_frames"])
    )
    return {
        "job_id": JOB,
        "confidence": conf,
        "raw_score": conf,
        "latency_ms": 1000,
        "model_version": "efficientnet-b0-df40-v1.0",
        "frame_scores": frame_scores,
        "evidence": {
            "claim": f"Frame-level analysis: {conf:.2f}",
            "flags": flags,
            "frame_scores": frame_scores,
            "flagged_range": flagged_range,
            "frame_evidence": frame_evidence or [],
        },
    }


# ─── Clip 1: Clear deepfake (high scores, flagged range) ────────────────────
def test_clip1_clear_deepfake_claim_contains_frame_range():
    scores = [0.12, 0.45, 0.72, 0.81, 0.79, 0.76, 0.68, 0.55, 0.42, 0.33]
    r = vc_with_frames(0.78, scores, flagged_range="frames 20-60")
    claim = wrap_detector_response("video-classifier", r)
    assert claim.polarity == ClaimPolarity.SYNTHETIC
    assert "frames 20-60" in claim.claim
    assert "blending artifacts" in claim.claim.lower() or "spatial evidence" in claim.claim.lower()


# ─── Clip 2: Authentic video (all low scores) ────────────────────────────────
def test_clip2_authentic_no_flagged_range():
    scores = [0.05, 0.08, 0.12, 0.09, 0.07, 0.11, 0.06, 0.13, 0.10, 0.08]
    r = vc_with_frames(0.09, scores)
    claim = wrap_detector_response("video-classifier", r)
    assert claim.polarity == ClaimPolarity.AUTHENTIC
    assert "no significant manipulation" in claim.claim


# ─── Clip 3: Borderline / inconclusive ───────────────────────────────────────
def test_clip3_borderline_claim_says_inconclusive():
    scores = [0.42, 0.51, 0.48, 0.55, 0.50, 0.46, 0.53, 0.49, 0.47, 0.52]
    r = vc_with_frames(0.49, scores)
    claim = wrap_detector_response("video-classifier", r)
    assert claim.polarity == ClaimPolarity.INCONCLUSIVE
    assert "borderline" in claim.claim.lower() or "neither confirms" in claim.claim.lower()


# ─── Clip 4: SpatialMetrics populated from frame_scores ──────────────────────
def test_clip4_spatial_metrics_suspicious_ratio():
    scores = [0.80, 0.75, 0.90, 0.20, 0.15, 0.10, 0.12, 0.09, 0.11, 0.08]
    # 3 out of 10 frames are >= 0.65
    r = vc_with_frames(0.53, scores)   # aggregate is borderline
    claim = wrap_detector_response("video-classifier", r)
    assert claim.observational_metrics is not None
    sm = claim.observational_metrics.spatial
    assert sm is not None
    assert sm.sampled_frames == 10
    # suspicious_frame_ratio = 3/10 = 0.3
    assert abs(sm.suspicious_frame_ratio - 0.3) < 0.01


# ─── Clip 5: max_frame_anomaly is the highest per-frame score ────────────────
def test_clip5_max_frame_anomaly():
    scores = [0.10, 0.20, 0.95, 0.30, 0.15, 0.08, 0.11, 0.09, 0.07, 0.06]
    r = vc_with_frames(0.31, scores)
    claim = wrap_detector_response("video-classifier", r)
    sm = claim.observational_metrics.spatial
    assert sm.max_frame_anomaly == pytest.approx(0.95, abs=0.001)


# ─── Clip 6: Empty frame_scores (legacy response without Task 4 fields) ──────
def test_clip6_legacy_response_still_works():
    """Detector running old code (no frame_scores) must not crash the wrapper."""
    r = {
        "job_id": JOB,
        "confidence": 0.72,
        "raw_score": 0.72,
        "latency_ms": 500,
        "model_version": "efficientnet-b0-v1.0",
        "evidence": {
            "claim": "Frame-level EfficientNet-B0 analysis computed fake probability of 0.72.",
            "flags": ["high_fake_probability"],
        },
    }
    claim = wrap_detector_response("video-classifier", r)
    assert claim.polarity == ClaimPolarity.SYNTHETIC
    assert claim.observational_metrics.spatial.sampled_frames == 10  # falls back to constant


# ─── Clip 7: Video-classifier disagrees with rPPG (rPPG sees authentic pulse) ─
def test_clip7_disagreement_with_rppg_still_produces_valid_claim():
    """
    Task 4 says: "test on at least 10 clips, including some where the
    video model disagrees with rPPG or SyncNet."
    Here the video model is SYNTHETIC (0.88) but rPPG would be AUTHENTIC.
    The claim wrapper for video-classifier must still be SYNTHETIC and not
    be silenced by the disagreement.
    """
    scores = [0.85, 0.90, 0.88, 0.92, 0.87, 0.89, 0.91, 0.84, 0.86, 0.90]
    r = vc_with_frames(0.882, scores, flagged_range="frames 0-90")
    claim = wrap_detector_response("video-classifier", r)
    assert claim.polarity == ClaimPolarity.SYNTHETIC
    assert "frames 0-90" in claim.claim


# ─── Clip 8: SyncNet disagrees — dubbed audio (syncnet SYNTHETIC, vc AUTHENTIC) ─
def test_clip8_vc_authentic_syncnet_would_disagree():
    """
    Video classifier says authentic (0.18), but a dubbed-audio test would
    have SyncNet returning SYNTHETIC.
    """
    scores = [0.15, 0.18, 0.22, 0.17, 0.19, 0.21, 0.16, 0.20, 0.18, 0.14]
    r = vc_with_frames(0.18, scores)
    claim = wrap_detector_response("video-classifier", r)
    assert claim.polarity == ClaimPolarity.AUTHENTIC
    assert claim.confidence == pytest.approx(0.18, abs=0.01)


# ─── Clip 9: No face detected — scores all near 0.5 ─────────────────────────
def test_clip9_no_face_borderline_scores():
    scores = [0.49, 0.51, 0.50, 0.48, 0.52, 0.49, 0.51, 0.50, 0.48, 0.52]
    r = vc_with_frames(0.50, scores)
    claim = wrap_detector_response("video-classifier", r)
    assert claim.polarity == ClaimPolarity.INCONCLUSIVE


# ─── Clip 10: Strong synthetic, strong heatmap evidence in flagged range ─────
def test_clip10_strong_synthetic_with_heatmap_evidence():
    scores = [0.91, 0.93, 0.95, 0.89, 0.92, 0.94, 0.90, 0.88, 0.91, 0.93]
    frame_evidence = [
        {"frame_index": i, "fake_score": s, "heatmap_b64": "AAAA" if s > 0.65 else None}
        for i, s in enumerate(scores)
    ]
    r = vc_with_frames(0.916, scores,
                       flagged_range="frames 0-90",
                       frame_evidence=frame_evidence)
    claim = wrap_detector_response("video-classifier", r)
    assert claim.polarity == ClaimPolarity.SYNTHETIC
    # All 10 frames flagged → suspicious_frame_ratio == 1.0
    sm = claim.observational_metrics.spatial
    assert sm.suspicious_frame_ratio == pytest.approx(1.0, abs=0.01)
    assert "strong" in claim.claim.lower() or "blending" in claim.claim.lower()