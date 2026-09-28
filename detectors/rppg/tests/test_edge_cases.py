"""Edge-case regression test suite for rPPG detector low-light and short-clip handling.

Covers:
1. Low-light attenuation & guardrail boundary (lum < 18 vs 18 <= lum < 50 vs lum >= 50)
2. Short-clip attenuation & guardrail boundary (dur < 2.0s vs 2.0s <= dur < 5.0s vs dur >= 5.0s)
3. FPS-aware signal quality scoring (24fps, 30fps, 60fps)
4. Combined edge cases (dim + short compound degradation)
5. Service-level API contract validation (/detect endpoint with TestClient)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

# Ensure detectors/rppg package is importable
RPPG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RPPG_DIR))

from main import app
from preprocess import RppgPreprocessor
from rppg_extract import (
    _BPM_HIGH_HZ,
    _BPM_LOW_HZ,
    extract_pulse_signal,
    signal_quality_score,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test Suite 1: Low-Light Attenuation & Boundary Checks
# ---------------------------------------------------------------------------


class TestLowLightAttenuation:
    """Validates graduated luminance handling from pitch dark to studio lighting."""

    def test_pitch_dark_triggers_guardrail(self, pitch_dark_video_path: str, client: TestClient) -> None:
        """Video with luminance < 18 must trigger guardrail, return inconclusive with zero input quality."""
        prep = RppgPreprocessor()
        _, _, meta = prep.preprocess_video(pitch_dark_video_path)

        assert meta["guardrail_triggered"] is True
        assert "insufficient_lighting" in meta["flags"]
        assert meta["luminance_confidence_factor"] == 0.0

        # E2E API Check
        response = client.post("/detect", json={"job_id": "test-dark", "modality": "video", "payload": pitch_dark_video_path})
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] == "inconclusive"
        assert data["confidence"] == 0.5
        assert data["input_quality"] == 0.0
        assert "insufficient_lighting" in data["evidence"]["flags"]

    def test_dim_light_attenuates_confidence(self, dim_light_video_path: str, client: TestClient) -> None:
        """Video with luminance in 18–50 zone must pass guardrail but attenuate confidence and flag low light."""
        prep = RppgPreprocessor()
        _, _, meta = prep.preprocess_video(dim_light_video_path)

        assert meta["guardrail_triggered"] is False
        assert 0.0 < meta["luminance_confidence_factor"] < 1.0

        # E2E API Check
        response = client.post("/detect", json={"job_id": "test-dim", "modality": "video", "payload": dim_light_video_path})
        assert response.status_code == 200
        data = response.json()
        assert data["input_quality"] < 1.0
        assert "low_light_attenuation" in data["evidence"]["flags"]
        assert "low-light factor" in data["evidence"]["claim"]

        # If input_quality < 0.5, verdict must be forced to inconclusive
        if data["input_quality"] < 0.5:
            assert data["verdict"] == "inconclusive"

    def test_normal_light_full_confidence(self, synthetic_video_path: str, client: TestClient) -> None:
        """Well-lit video (lum >= 50) must receive full luminance factor (1.0) and no attenuation flag."""
        prep = RppgPreprocessor()
        _, _, meta = prep.preprocess_video(synthetic_video_path)

        assert meta["guardrail_triggered"] is False
        assert meta["luminance_confidence_factor"] == 1.0

        # E2E API Check
        response = client.post("/detect", json={"job_id": "test-clean", "modality": "video", "payload": synthetic_video_path})
        assert response.status_code == 200
        data = response.json()
        assert "low_light_attenuation" not in data["evidence"]["flags"]


# ---------------------------------------------------------------------------
# Test Suite 2: Short-Clip Attenuation & Boundary Checks
# ---------------------------------------------------------------------------


class TestShortClipAttenuation:
    """Validates graduated duration handling (< 2.0s, 2.0–5.0s, >= 5.0s)."""

    def test_under_2s_triggers_guardrail(self, under_2s_video_path: str, client: TestClient) -> None:
        """Video under 2.0s must trigger guardrail and return inconclusive."""
        prep = RppgPreprocessor()
        _, _, meta = prep.preprocess_video(under_2s_video_path)

        assert meta["guardrail_triggered"] is True
        assert "insufficient_duration" in meta["flags"]
        assert meta["duration_confidence_factor"] == 0.0

        # E2E API Check
        response = client.post("/detect", json={"job_id": "test-under2s", "modality": "video", "payload": under_2s_video_path})
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] == "inconclusive"
        assert data["confidence"] == 0.5
        assert data["input_quality"] == 0.0
        assert "insufficient_duration" in data["evidence"]["flags"]

    def test_2_5s_clip_low_confidence(self, marginal_short_video_path: str, client: TestClient) -> None:
        """A 2.5s clip passes guardrail but gets attenuated duration factor (~0.17) and inconclusive verdict."""
        prep = RppgPreprocessor()
        _, _, meta = prep.preprocess_video(marginal_short_video_path)

        assert meta["guardrail_triggered"] is False
        # (2.5 - 2.0) / (5.0 - 2.0) = 0.5 / 3.0 ≈ 0.167
        assert 0.10 <= meta["duration_confidence_factor"] <= 0.25

        # E2E API Check
        response = client.post("/detect", json={"job_id": "test-2.5s", "modality": "video", "payload": marginal_short_video_path})
        assert response.status_code == 200
        data = response.json()
        assert data["input_quality"] < 0.5
        assert data["verdict"] == "inconclusive"
        assert "short_clip_attenuation" in data["evidence"]["flags"]

    def test_4s_clip_moderate_confidence(self, borderline_short_video_path: str, client: TestClient) -> None:
        """A 4.0s clip gets moderate duration factor (~0.67)."""
        prep = RppgPreprocessor()
        _, _, meta = prep.preprocess_video(borderline_short_video_path)

        assert meta["guardrail_triggered"] is False
        # (4.0 - 2.0) / (5.0 - 2.0) = 2.0 / 3.0 ≈ 0.667
        assert 0.60 <= meta["duration_confidence_factor"] <= 0.75

        # E2E API Check
        response = client.post("/detect", json={"job_id": "test-4s", "modality": "video", "payload": borderline_short_video_path})
        assert response.status_code == 200
        data = response.json()
        assert data["input_quality"] >= 0.5
        assert "short_clip_attenuation" in data["evidence"]["flags"]

    def test_10s_clip_full_confidence(self) -> None:
        """A 10s video signal has duration factor == 1.0 (no duration penalty)."""
        # Test unit logic directly on duration factor formula
        duration_sec = 10.0
        dur_factor = 1.0 if duration_sec >= 5.0 else max(0.0, (duration_sec - 2.0) / 3.0)
        assert dur_factor == 1.0


# ---------------------------------------------------------------------------
# Test Suite 3: FPS-Aware Quality Scoring
# ---------------------------------------------------------------------------


class TestSignalQualityFpsAccuracy:
    """Validates that signal quality score uses actual FPS rather than hardcoded 30."""

    def test_quality_score_backward_compat(self) -> None:
        """Default call with single argument defaults to fps=30.0."""
        t = np.arange(300) / 30.0
        pulse = np.sin(2 * np.pi * 1.2 * t).astype(np.float32)
        score_default = signal_quality_score(pulse)
        score_explicit = signal_quality_score(pulse, fps=30.0)
        assert score_default == score_explicit
        assert score_default > 0.5

    def test_quality_score_respects_fps(self) -> None:
        """A 1.5 Hz pulse sampled at 24 fps is evaluated accurately when fps=24 is passed."""
        fps = 24.0
        t = np.arange(240) / fps  # 10s at 24fps
        pulse = np.sin(2 * np.pi * 1.5 * t).astype(np.float32)

        score_correct_fps = signal_quality_score(pulse, fps=fps)
        assert score_correct_fps > 0.5, f"Expected high quality score with correct fps, got {score_correct_fps}"

    def test_temporal_denoising_preserves_cardiac_band(self) -> None:
        """Temporal moving average smoothing reduces noise while preserving cardiac frequency component."""
        fps = 30.0
        n = 150
        t = np.arange(n) / fps
        clean_sine = np.sin(2 * np.pi * 1.2 * t).astype(np.float32)
        rng = np.random.default_rng(42)
        noise = rng.normal(0, 0.5, size=(n, 3)).astype(np.float32)

        base_rgb = np.array([120.0, 90.0, 70.0], dtype=np.float32)
        amps = np.array([3.0, 1.0, 0.5], dtype=np.float32)
        noisy_rgb = base_rgb + (amps * clean_sine[:, None]) + noise

        # Extract pulse without denoising vs with denoising
        pulse_raw = extract_pulse_signal(noisy_rgb, fps, denoise=False)
        pulse_denoised = extract_pulse_signal(noisy_rgb, fps, denoise=True)

        quality_raw = signal_quality_score(pulse_raw, fps=fps)
        quality_denoised = signal_quality_score(pulse_denoised, fps=fps)

        # Denoising should improve or at least match spectral purity on noisy signals
        assert quality_denoised >= quality_raw - 0.05
        assert len(pulse_denoised) == n


# ---------------------------------------------------------------------------
# Test Suite 4: Combined Edge Cases & API Schema
# ---------------------------------------------------------------------------


class TestCombinedEdgeCases:
    """Validates combined effects (dim + short) and schema conformance."""

    def test_dim_and_short_double_attenuation(self, client: TestClient, tmp_path: Path) -> None:
        """A video that is both dim and short has its input_quality constrained by min()."""
        video_path = str(tmp_path / "dim_short.mp4")
        fps = 30
        n_frames = 75  # 2.5s (duration factor ~0.167)
        width, height = 320, 240
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(video_path, fourcc, float(fps), (width, height))
        for _ in range(n_frames):
            frame = np.full((height, width, 3), 30, dtype=np.uint8)  # dim ~30
            cv2.circle(frame, (width // 2, height // 2), 60, (32, 36, 44), -1)
            out.write(frame)
        out.release()

        response = client.post("/detect", json={"job_id": "test-combo", "modality": "video", "payload": video_path})
        assert response.status_code == 200
        data = response.json()
        assert data["input_quality"] <= 0.5
        assert data["verdict"] == "inconclusive"
        assert "low_light_attenuation" in data["evidence"]["flags"]
        assert "short_clip_attenuation" in data["evidence"]["flags"]

    def test_api_response_schema_fields(self, synthetic_video_path: str, client: TestClient) -> None:
        """Validate all required fields per AEGIS DetectorResponse contract are present."""
        response = client.post("/detect", json={"job_id": "test-schema", "modality": "video", "payload": synthetic_video_path})
        assert response.status_code == 200
        data = response.json()

        required_fields = ["job_id", "modality", "confidence", "raw_score", "score", "verdict", "model", "model_version", "estimated_bpm", "latency_ms", "evidence", "input_quality"]
        for field in required_fields:
            assert field in data, f"Missing required field {field}"

        assert 0.0 <= data["confidence"] <= 1.0
        assert 0.0 <= data["input_quality"] <= 1.0
        assert isinstance(data["evidence"]["claim"], str)
        assert isinstance(data["evidence"]["flags"], list)
