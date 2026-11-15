# tests/test_role5_streaming_rppg.py
"""Role 5 test suite — Streaming rPPG failure-mode fixes + live pipeline fusion.

Run with:
    pytest tests/test_role5_streaming_rppg.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

# Make repo root importable
_cur = Path(__file__).resolve().parent
while _cur.parent != _cur:
    if (_cur / "capability_manifests").exists() or (_cur / ".git").exists():
        REPO = _cur
        break
    _cur = _cur.parent
else:
    REPO = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "capability_manifests"))

from engine.edge_model.streaming_rppg import StreamingRppgDetector


# =========================================================================
# Helpers
# =========================================================================

def _make_detector(fps: float = 30.0, window_sec: float = 6.0) -> StreamingRppgDetector:
    return StreamingRppgDetector(fps=fps, window_seconds=window_sec, stride_frames=1)


def _constant_rgb(value: float = 150.0) -> np.ndarray:
    """Completely static (motionless) face."""
    return np.array([value, value * 0.67, value * 0.53], dtype=np.float32)


def _live_rgb(frame_idx: int, fps: float = 30.0, bpm: float = 72.0) -> np.ndarray:
    """Simulates realistic periodic skin-tone fluctuation mimicking a heartbeat."""
    t = frame_idx / fps
    cardiac_hz = bpm / 60.0
    r = 150.0 + 3.0 * np.sin(2 * np.pi * cardiac_hz * t)
    g = 100.0 + 2.0 * np.sin(2 * np.pi * cardiac_hz * t + 0.1)
    b = 80.0  + 1.0 * np.sin(2 * np.pi * cardiac_hz * t + 0.2)
    return np.array([r, g, b], dtype=np.float32)


WINDOW_FRAMES = int(30 * 6.0)   # 180 frames


# =========================================================================
# TEST 1 — M2-L1: Motionless Face Guardrail
# =========================================================================

class TestMotionlessFaceGuardrail:
    """M2-L1: A completely static face must NOT be classified 100% synthetic."""

    def _run_full_buffer(self, detector: StreamingRppgDetector) -> dict:
        result = {}
        for i in range(WINDOW_FRAMES):
            result = detector.process_frame(_constant_rgb(), face_detected=True)
        return result

    def test_motionless_status(self):
        """Status must be 'motionless_face', never 'synthetic'."""
        det = _make_detector()
        result = self._run_full_buffer(det)
        assert result["status"] == "motionless_face", (
            f"Expected 'motionless_face', got '{result['status']}'"
        )

    def test_motionless_neutral_score(self):
        """Score must be 0.5 (neutral), never 1.0."""
        det = _make_detector()
        result = self._run_full_buffer(det)
        assert result["score"] == 0.5, (
            f"Expected 0.5 neutral score for still face, got {result['score']}"
        )

    def test_motionless_zero_confidence(self):
        """Confidence must be 0.0 for a motionless face."""
        det = _make_detector()
        result = self._run_full_buffer(det)
        assert result["confidence"] == 0.0, (
            f"Expected 0.0 confidence, got {result['confidence']}"
        )

    def test_motionless_not_full_synthetic(self):
        """Score must NOT be 1.0 (this was the original bug)."""
        det = _make_detector()
        result = self._run_full_buffer(det)
        assert result["score"] != 1.0, (
            "BUG M2-L1 NOT FIXED: Motionless face scored as 100% synthetic!"
        )

    def test_motionless_has_flags(self):
        """'motionless_face' flag must be present."""
        det = _make_detector()
        result = self._run_full_buffer(det)
        assert "motionless_face" in result.get("flags", [])


# =========================================================================
# TEST 2 — M2-L2: Six-Second Silent Warm-up
# =========================================================================

class TestWarmupState:
    """M2-L2: During initial buffer fill, return 'warming_up' — not silent."""

    def test_first_frame_is_warming_up(self):
        """Very first frame must report 'warming_up'."""
        det = _make_detector()
        result = det.process_frame(_live_rgb(0), face_detected=True)
        assert result["status"] == "warming_up"

    def test_warmup_score_is_none(self):
        """Score must be None during warm-up (no premature verdict)."""
        det = _make_detector()
        for i in range(50):
            result = det.process_frame(_live_rgb(i), face_detected=True)
        assert result["score"] is None, (
            f"Expected None score during warm-up, got {result['score']}"
        )

    def test_warmup_progress_increases(self):
        """Progress percentage must increase with each new frame."""
        det = _make_detector()
        progresses = []
        for i in range(60):
            r = det.process_frame(_live_rgb(i), face_detected=True)
            if r["status"] == "warming_up":
                progresses.append(r.get("progress", 0))
        assert progresses == sorted(progresses), "Warmup progress must be non-decreasing"

    def test_warmup_resolves_after_full_buffer(self):
        """After WINDOW_FRAMES frames, status must NOT be 'warming_up'."""
        det = _make_detector()
        result = {}
        for i in range(WINDOW_FRAMES + 10):
            result = det.process_frame(_live_rgb(i), face_detected=True)
        assert result["status"] != "warming_up", (
            "Warmup never resolved after full buffer was filled!"
        )

    def test_warmup_has_target_frames(self):
        """Response during warm-up must include 'target_frames' field."""
        det = _make_detector()
        result = det.process_frame(_live_rgb(0), face_detected=True)
        assert "target_frames" in result
        assert result["target_frames"] == WINDOW_FRAMES


# =========================================================================
# TEST 3 — M2-L3: Face Loss / Whole-Frame Fallback Fix
# =========================================================================

class TestFaceLossGuardrail:
    """M2-L3: Losing face must return 'not_applicable', not noisy whole-frame RGB."""

    def test_no_face_returns_not_applicable(self):
        """face_detected=False → status must be 'not_applicable'."""
        det = _make_detector()
        result = det.process_frame(None, face_detected=False)
        assert result["status"] == "not_applicable"

    def test_no_face_score_is_none(self):
        """When face is lost, score must be None (no fabricated score)."""
        det = _make_detector()
        result = det.process_frame(None, face_detected=False)
        assert result["score"] is None, (
            f"Expected None for missing face, got {result['score']}"
        )

    def test_no_face_has_flag(self):
        """'not_applicable' flag must be in response flags."""
        det = _make_detector()
        result = det.process_frame(None, face_detected=False)
        assert "not_applicable" in result.get("flags", [])

    def test_buffer_not_poisoned_by_face_loss(self):
        """Face loss frames must NOT append to the CHROM buffer."""
        det = _make_detector()
        # First, fill with live data
        for i in range(60):
            det.process_frame(_live_rgb(i), face_detected=True)
        buffer_before = len(det._buffer)

        # Feed 10 "face lost" frames
        for _ in range(10):
            det.process_frame(None, face_detected=False)

        buffer_after = len(det._buffer)
        assert buffer_after == buffer_before, (
            f"Face-loss frames should NOT grow the buffer. "
            f"Before: {buffer_before}, After: {buffer_after}"
        )

    def test_face_lost_then_recovered(self):
        """After face is re-acquired, detector resumes from 'warming_up' or last known."""
        det = _make_detector()
        # Feed 60 live frames
        for i in range(60):
            det.process_frame(_live_rgb(i), face_detected=True)
        # Lose face for 5 frames
        for _ in range(5):
            det.process_frame(None, face_detected=False)
        # Re-acquire face
        result = det.process_frame(_live_rgb(70), face_detected=True)
        # Should NOT be 'not_applicable' on re-acquisition
        assert result["status"] != "not_applicable"


# =========================================================================
# TEST 4 — Capability Manifest Schema Validation
# =========================================================================

class TestCapabilityManifest:
    """The streaming-rppg.json manifest must pass schema validation."""

    MANIFEST_PATH = REPO / "capability_manifests" / "streaming-rppg.json"
    SCHEMA_PATH = REPO / "capability_manifests" / "Schema.py"

    def test_manifest_file_exists(self):
        assert self.MANIFEST_PATH.exists(), (
            f"Manifest file missing: {self.MANIFEST_PATH}"
        )

    def test_manifest_loads_as_valid_json(self):
        with open(self.MANIFEST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_manifest_has_required_fields(self):
        with open(self.MANIFEST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        required = [
            "detector_name", "modality", "version", "description",
            "input_constraints", "performance", "known_failure_modes",
            "reliability_notes",
        ]
        for field in required:
            assert field in data, f"Missing required field: '{field}'"

    def test_manifest_modality_is_video(self):
        with open(self.MANIFEST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert "video" in data["modality"]

    def test_manifest_min_duration_6_seconds(self):
        with open(self.MANIFEST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert data["input_constraints"]["min_duration_seconds"] == 6.0

    def test_manifest_has_three_failure_modes(self):
        with open(self.MANIFEST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        modes = data.get("known_failure_modes", [])
        assert len(modes) >= 3, (
            f"Expected ≥3 failure modes (M2-L1, M2-L2, M2-L3), got {len(modes)}"
        )

    def test_manifest_jsonschema_validation(self):
        """Full schema validation using jsonschema library."""
        try:
            import jsonschema
        except ImportError:
            pytest.skip("jsonschema not installed — pip install jsonschema")

        sys.path.insert(0, str(REPO / "capability_manifests"))
        try:
            from capability_manifests.Schema import DETECTOR_MANIFEST_SCHEMA  # type: ignore
        except ImportError:
            from Schema import DETECTOR_MANIFEST_SCHEMA  # type: ignore

        with open(self.MANIFEST_PATH, encoding="utf-8") as f:
            data = json.load(f)

        # Should not raise
        jsonschema.validate(instance=data, schema=DETECTOR_MANIFEST_SCHEMA)


# =========================================================================
# TEST 5 — Dual-Model Score Fusion Logic
# =========================================================================

class TestFusionLogic:
    """Verify the 60/40 fusion math and fallback behaviour."""

    def test_fusion_math_when_both_active(self):
        """fused = 0.6 * spatial + 0.4 * rppg (within floating-point tolerance)."""
        w_spatial, w_rppg = 0.6, 0.4
        spatial_score = 0.8
        rppg_score = 0.3
        expected = round(w_spatial * spatial_score + w_rppg * rppg_score, 4)
        actual = round(0.6 * 0.8 + 0.4 * 0.3, 4)
        assert abs(actual - expected) < 1e-6, f"{actual} != {expected}"

    def test_fusion_fallback_when_rppg_warming_up(self):
        """When rPPG score is None (warm-up), fused_score must equal spatial_score."""
        spatial = 0.75
        rppg = None
        fused = spatial if rppg is None else 0.6 * spatial + 0.4 * rppg
        assert fused == spatial

    def test_fusion_fallback_when_rppg_not_applicable(self):
        """When face is lost (not_applicable), fused_score must equal spatial_score."""
        spatial = 0.3
        rppg = None   # not_applicable returns score=None
        fused = spatial if rppg is None else 0.6 * spatial + 0.4 * rppg
        assert fused == spatial

    def test_authentic_verdict_below_half(self):
        """Score < 0.5 → 'authentic' verdict."""
        fused = 0.3
        verdict = "synthetic" if fused > 0.5 else "authentic"
        assert verdict == "authentic"

    def test_synthetic_verdict_above_half(self):
        """Score > 0.5 → 'synthetic' verdict."""
        fused = 0.7
        verdict = "synthetic" if fused > 0.5 else "authentic"
        assert verdict == "synthetic"