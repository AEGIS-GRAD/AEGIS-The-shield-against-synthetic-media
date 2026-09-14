"""Tests for rPPG signal extraction and quality scoring.

Fast tests (no video I/O):
  - test_signal_quality_score_clean_sine  — pure 1.2 Hz sine → high score
  - test_signal_quality_score_random_noise — white noise → low score
  - test_extract_pulse_signal_returns_correct_shape
  - test_estimate_heart_rate_sine_input
  - test_bandpass_removes_dc_and_high_freq

Slow test (requires real video from eval/data/):
  - test_full_pipeline_real_video_bpm_plausibility  @pytest.mark.slow
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

# Make the rppg package importable when tests are run from the repo root or
# from within detectors/rppg/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rppg_extract import (
    estimate_heart_rate,
    extract_pulse_signal,
    signal_quality_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FPS = 30.0  # sampling rate used by all fast synthetic tests
_N = 300     # 10 seconds at 30 fps — adequate for bandpass filter


def _make_sine_pulse(
    freq_hz: float = 1.2,
    n: int = _N,
    fps: float = _FPS,
) -> np.ndarray:
    """Return a pure bandpass-sine waveform (the output of extract_pulse_signal).

    Used to unit-test ``signal_quality_score`` in isolation — bypasses CHROM
    so the test validates only the spectral-purity math.
    """
    t = np.arange(n) / fps
    return np.sin(2 * np.pi * freq_hz * t).astype(np.float32)


def _make_differential_rgb(
    freq_hz: float = 1.2,
    n: int = _N,
    fps: float = _FPS,
    noise_std: float = 0.3,
) -> np.ndarray:
    """Return (N, 3) RGB with physiologically-realistic differential channel amplitudes.

    Real rPPG signals appear with *different* amplitudes in R, G, B due to
    wavelength-dependent haemoglobin absorption.  CHROM is designed to extract
    exactly this differential signal — identical amplitudes across all channels
    are cancelled by the algorithm (by design).

    This fixture uses R:G:B amplitude ratio 3:1:0.5, a plausible approximation
    of skin haemoglobin absorption differences.
    """
    t = np.arange(n) / fps
    base = np.array([160.0, 120.0, 100.0], dtype=np.float32)
    # Differential amplitudes — CHROM will preserve (not cancel) this signal
    amps = np.array([3.0, 1.0, 0.5], dtype=np.float32)
    sine_wave = np.sin(2 * np.pi * freq_hz * t).astype(np.float32)
    noise = np.random.default_rng(42).normal(0, noise_std, size=(n, 3)).astype(np.float32)
    return (base + (amps * sine_wave[:, None]) + noise).astype(np.float32)


def _make_noise_rgb(n: int = _N) -> np.ndarray:
    """Return (N, 3) RGB array of white noise (no periodic structure)."""
    rng = np.random.default_rng(0)
    return rng.uniform(80, 180, size=(n, 3)).astype(np.float32)


def _make_noise_pulse(n: int = _N) -> np.ndarray:
    """Return white-noise pulse (no dominant frequency in the cardiac band)."""
    rng = np.random.default_rng(1)
    return rng.standard_normal(n).astype(np.float32)


# ---------------------------------------------------------------------------
# Fast unit tests — signal_quality_score
# ---------------------------------------------------------------------------


class TestSignalQualityScore:
    """Validates the spectral-purity quality metric on synthetic signals.

    Note on test design
    -------------------
    ``signal_quality_score`` operates on the *output* of ``extract_pulse_signal``
    (a pre-filtered 1-D waveform).  The unit tests here call it directly on
    pure sine / noise pulses to isolate the spectral-purity math from the CHROM
    pipeline.  A separate integration test (``test_chrom_pipeline_*``) validates
    the full RGB → pulse → score path.
    """

    def test_clean_sine_scores_high(self) -> None:
        """A pure 1.2 Hz sine waveform (post-CHROM) should yield a high quality score.

        ``signal_quality_score`` computes peak_power / band_power.  A near-ideal
        sine has ≈ all its energy at a single frequency → ratio ≈ 1.0.
        """
        pulse = _make_sine_pulse(freq_hz=1.2)
        score = signal_quality_score(pulse)

        assert isinstance(score, float), "score must be a Python float"
        assert 0.0 <= score <= 1.0, f"score must be in [0, 1], got {score}"
        assert score > 0.5, (
            f"Expected high quality score (>0.5) for pure sine input, got {score:.4f}."
        )

    def test_random_noise_scores_low(self) -> None:
        """White-noise pulse should yield a low quality score.

        Random noise spreads power uniformly across the cardiac band,
        so the peak/band ratio should stay well below 0.5.
        """
        pulse = _make_noise_pulse()
        score = signal_quality_score(pulse)

        assert isinstance(score, float), "score must be a Python float"
        assert 0.0 <= score <= 1.0, f"score must be in [0, 1], got {score}"
        assert score < 0.5, (
            f"Expected low quality score (<0.5) for random noise, got {score:.4f}."
        )

    def test_chrom_pipeline_differential_rgb_scores_higher_than_noise(self) -> None:
        """Integration test: differential-channel RGB through CHROM scores above noise.

        CHROM is designed to extract a differential signal between RGB channels.
        A signal with physiologically-plausible per-channel amplitudes (R > G > B)
        should survive CHROM processing and yield a higher quality score than
        white-noise input through the same pipeline.
        """
        rgb_signal = _make_differential_rgb(freq_hz=1.2)
        rgb_noise = _make_noise_rgb()

        pulse_signal = extract_pulse_signal(rgb_signal, _FPS)
        pulse_noise = extract_pulse_signal(rgb_noise, _FPS)

        score_signal = signal_quality_score(pulse_signal)
        score_noise = signal_quality_score(pulse_noise)

        assert score_signal > score_noise, (
            f"Differential RGB signal (score={score_signal:.4f}) should score higher "
            f"than white noise (score={score_noise:.4f}) through CHROM pipeline."
        )

    def test_score_is_always_in_unit_interval(self) -> None:
        """score must always be clamped to [0, 1] regardless of input."""
        for seed in range(5):
            rng = np.random.default_rng(seed)
            rgb = rng.uniform(0, 255, size=(_N, 3)).astype(np.float32)
            pulse = extract_pulse_signal(rgb, _FPS)
            score = signal_quality_score(pulse)
            assert 0.0 <= score <= 1.0, f"score out of range: {score}"

    def test_short_signal_returns_zero(self) -> None:
        """Signals shorter than 4 samples should return 0.0 gracefully."""
        short_pulse = np.array([1.0, 0.0, -1.0], dtype=np.float32)
        score = signal_quality_score(short_pulse)
        assert score == 0.0


# ---------------------------------------------------------------------------
# Fast unit tests — extract_pulse_signal
# ---------------------------------------------------------------------------


class TestExtractPulseSignal:
    def test_output_shape_matches_input_length(self) -> None:
        rgb = _make_differential_rgb()
        pulse = extract_pulse_signal(rgb, _FPS)
        assert pulse.shape == (len(rgb),), (
            f"Pulse length {len(pulse)} != input length {len(rgb)}"
        )

    def test_output_dtype_is_float32(self) -> None:
        rgb = _make_differential_rgb()
        pulse = extract_pulse_signal(rgb, _FPS)
        assert pulse.dtype == np.float32

    def test_bandpass_removes_dc(self) -> None:
        """After bandpass filtering, the DC component should be near zero."""
        rgb = _make_differential_rgb()
        pulse = extract_pulse_signal(rgb, _FPS)
        assert abs(pulse.mean()) < 0.1, (
            f"DC component not removed: mean={pulse.mean():.4f}"
        )

    def test_raises_on_single_frame(self) -> None:
        with pytest.raises(ValueError, match="at least 2 frames"):
            extract_pulse_signal(np.array([[160, 120, 100]], dtype=np.float32), _FPS)

    def test_raises_on_wrong_shape(self) -> None:
        with pytest.raises(ValueError, match="shape \\(N, 3\\)"):
            extract_pulse_signal(np.zeros((_N,), dtype=np.float32), _FPS)

    def test_raises_on_nonpositive_fps(self) -> None:
        rgb = _make_differential_rgb()
        with pytest.raises(ValueError, match="fps must be positive"):
            extract_pulse_signal(rgb, 0.0)


# ---------------------------------------------------------------------------
# Fast unit tests — estimate_heart_rate
# ---------------------------------------------------------------------------


class TestEstimateHeartRate:
    def test_sine_at_1hz_estimates_60bpm(self) -> None:
        """A 1.0 Hz sine wave should be estimated near 60 BPM."""
        t = np.arange(_N) / _FPS
        pulse = np.sin(2 * np.pi * 1.0 * t).astype(np.float32)
        bpm = estimate_heart_rate(pulse, _FPS)
        # Allow ±10 BPM tolerance for FFT bin resolution
        assert 50.0 <= bpm <= 70.0, f"Expected ~60 BPM for 1 Hz sine, got {bpm:.1f}"

    def test_returns_float(self) -> None:
        pulse = np.sin(np.linspace(0, 10, _N)).astype(np.float32)
        bpm = estimate_heart_rate(pulse, _FPS)
        assert isinstance(bpm, float)

    def test_raises_on_single_sample(self) -> None:
        with pytest.raises(ValueError, match="at least 2 samples"):
            estimate_heart_rate(np.array([0.0], dtype=np.float32), _FPS)


# ---------------------------------------------------------------------------
# Slow integration test — real video BPM plausibility
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_full_pipeline_real_video_bpm_plausibility(real_video_path: str) -> None:
    """Run the complete rPPG pipeline on a real video and check BPM plausibility.

    This is a *plausibility check*, not an accuracy benchmark.  The assertion
    only verifies that the estimated BPM falls within the physiologically
    possible human range (40–180 BPM).  It does NOT assert a specific value.

    Requires: eval/data/video_subset/real/006.mp4 (auto-skipped if absent).
    """
    if not os.path.exists(real_video_path):
        pytest.skip(
            f"Real video not found at {real_video_path}. "
            "Run the eval data download script first."
        )

    # Import here so the test module itself has no mandatory heavy imports
    from preprocess import RppgPreprocessor

    preprocessor = RppgPreprocessor()
    rgb_signals, fps = preprocessor.get_face_rgb_signals(real_video_path)

    assert rgb_signals.ndim == 2 and rgb_signals.shape[1] == 3, (
        f"Unexpected rgb_signals shape: {rgb_signals.shape}"
    )
    assert fps > 0, f"FPS must be positive, got {fps}"
    assert len(rgb_signals) >= 10, (
        f"Expected at least 10 frames, got {len(rgb_signals)}"
    )

    pulse = extract_pulse_signal(rgb_signals, fps)
    assert len(pulse) == len(rgb_signals), "Pulse length must match frame count"

    bpm = estimate_heart_rate(pulse, fps)

    assert 40.0 <= bpm <= 180.0, (
        f"Estimated BPM {bpm:.1f} is outside the plausible human range [40, 180]. "
        "This may indicate a bug in the FFT or bandpass logic, not necessarily "
        "a detection failure — rPPG accuracy depends on video quality and face visibility."
    )
