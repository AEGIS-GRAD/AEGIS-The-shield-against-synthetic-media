"""rPPG signal extraction — CHROM algorithm (De Haan & Jeanne, 2013).

Reference implementation follows the CHROM math from the ubicomplab/rPPG-Toolbox
repository (MIT licence), which itself derives from:

  De Haan, G., & Jeanne, V. (2013). Robust pulse rate from chrominance-based
  rPPG. IEEE Transactions on Biomedical Engineering, 60(10), 2878–2886.
  https://doi.org/10.1109/TBME.2013.2266196

Pipeline
--------
1. Normalise each RGB channel by its temporal mean so that X, Y, Z ∈ (0, ∞).
2. Build two chrominance projections:
       Xc = 3R_n - 2G_n        (strong green-red opponent)
       Yc = 1.5R_n + G_n - 1.5B_n  (luminance-corrected complement)
3. Combine to cancel motion / illumination:
       S = Xc - (std(Xc) / std(Yc)) * Yc
4. Bandpass-filter to cardiac range 0.7–4 Hz (42–240 bpm).
"""
from __future__ import annotations

import logging
from typing import Tuple

import numpy as np
from scipy import signal as sp_signal

logger = logging.getLogger(__name__)

# Cardiac frequency band in Hz
_BPM_LOW_HZ: float = 0.7   # 42 bpm
_BPM_HIGH_HZ: float = 4.0  # 240 bpm

# Butterworth filter order
_FILTER_ORDER: int = 4


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_pulse_signal(
    rgb_signals: np.ndarray,
    fps: float,
) -> np.ndarray:
    """Apply the CHROM algorithm and return a bandpass-filtered pulse waveform.

    Args:
        rgb_signals: Float array of shape ``(N, 3)`` containing mean face-
            region [R, G, B] values per frame (as returned by
            :class:`~preprocess.RppgPreprocessor`).
        fps: Native video frame rate in frames-per-second.

    Returns:
        1-D float32 NumPy array of length N containing the filtered
        blood-volume-pulse (BVP) signal.

    Raises:
        ValueError: If ``rgb_signals`` has fewer than 2 frames or ``fps <= 0``.
    """
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    if rgb_signals.ndim != 2 or rgb_signals.shape[1] != 3:
        raise ValueError(
            f"rgb_signals must have shape (N, 3), got {rgb_signals.shape}"
        )
    n = rgb_signals.shape[0]
    if n < 2:
        raise ValueError(
            f"Need at least 2 frames to extract a pulse signal, got {n}."
        )

    # --- Step 1: per-channel temporal normalisation -------------------------
    # Divide each channel by its temporal mean.  This converts absolute
    # pixel values to relative fluctuations, making the algorithm invariant
    # to ambient lighting level.
    mean_rgb = rgb_signals.mean(axis=0)  # shape (3,)
    # Guard against zero-mean channels (e.g. fully black frames)
    mean_rgb = np.where(mean_rgb == 0.0, 1.0, mean_rgb)
    R_n = rgb_signals[:, 0] / mean_rgb[0]
    G_n = rgb_signals[:, 1] / mean_rgb[1]
    B_n = rgb_signals[:, 2] / mean_rgb[2]

    # --- Step 2: CHROM chrominance projections ------------------------------
    Xc = 3.0 * R_n - 2.0 * G_n
    Yc = 1.5 * R_n + G_n - 1.5 * B_n

    # --- Step 3: motion-cancellation combination ----------------------------
    std_Xc = np.std(Xc, ddof=0)
    std_Yc = np.std(Yc, ddof=0)

    # If Yc is constant (no variation), skip the correction term to avoid NaN.
    if std_Yc < 1e-9:
        alpha = 0.0
        logger.debug(
            "std(Yc) ≈ 0; skipping motion-cancellation term (signal may be noisy)."
        )
    else:
        alpha = std_Xc / std_Yc

    S = Xc - alpha * Yc  # raw pulse signal

    # --- Step 4: bandpass filter at cardiac frequencies ---------------------
    pulse = _bandpass_filter(S, fps, _BPM_LOW_HZ, _BPM_HIGH_HZ)

    return pulse.astype(np.float32)


def estimate_heart_rate(
    pulse_signal: np.ndarray,
    fps: float,
) -> float:
    """Estimate heart rate in BPM from a filtered pulse waveform.

    Uses FFT to find the dominant frequency within the cardiac band
    [0.7, 4.0] Hz and converts it to beats-per-minute.

    Args:
        pulse_signal: 1-D float array — the bandpass-filtered BVP signal.
        fps: Sampling rate in frames-per-second.

    Returns:
        Estimated heart rate in BPM as a Python float.

    Raises:
        ValueError: If ``pulse_signal`` has fewer than 2 samples or ``fps <= 0``.
    """
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    n = len(pulse_signal)
    if n < 2:
        raise ValueError(
            f"Need at least 2 samples for heart-rate estimation, got {n}."
        )

    freqs, power = _compute_power_spectrum(pulse_signal, fps)
    cardiac_mask = (freqs >= _BPM_LOW_HZ) & (freqs <= _BPM_HIGH_HZ)

    if not np.any(cardiac_mask):
        logger.warning(
            "No frequency bins fall within the cardiac band; "
            "defaulting to 60 BPM estimate."
        )
        return 60.0

    peak_idx = np.argmax(power[cardiac_mask])
    peak_freq_hz = freqs[cardiac_mask][peak_idx]
    bpm = float(peak_freq_hz * 60.0)
    logger.debug("Dominant cardiac frequency: %.3f Hz → %.1f BPM", peak_freq_hz, bpm)
    return bpm


def signal_quality_score(pulse_signal: np.ndarray) -> float:
    """Compute a spectral purity score measuring how periodic the pulse signal is.

    The score is defined as the fraction of total power in the cardiac band
    that is concentrated at the dominant frequency:

        score = peak_power / band_power

    A clean, regular heartbeat produces a near-sinusoidal waveform with most
    power at a single frequency → high score (approaching 1.0).
    Random noise spreads power uniformly → low score (near 0.0).

    This score is used downstream as a proxy for physiological plausibility.
    Higher score ≈ more "real" biological signal present.

    Args:
        pulse_signal: 1-D float array — the bandpass-filtered BVP signal.

    Returns:
        Spectral purity score in ``[0.0, 1.0]``.
    """
    n = len(pulse_signal)
    if n < 4:
        # Cannot compute a meaningful spectrum; return neutral score.
        logger.warning(
            "Signal too short (%d samples) for quality scoring; returning 0.0.", n
        )
        return 0.0

    # Use a fixed placeholder fps of 30 for the quality score because this
    # function does not accept fps — quality is relative, not absolute.
    # The cardiac band mask uses a wide [0.7–4 Hz] window so the exact fps
    # matters only for resolving individual bins, not the overall ratio.
    _fps_default = 30.0

    freqs, power = _compute_power_spectrum(pulse_signal, _fps_default)
    cardiac_mask = (freqs >= _BPM_LOW_HZ) & (freqs <= _BPM_HIGH_HZ)

    if not np.any(cardiac_mask):
        return 0.0

    band_power = power[cardiac_mask].sum()
    if band_power < 1e-12:
        return 0.0

    peak_power = power[cardiac_mask].max()
    score = float(np.clip(peak_power / band_power, 0.0, 1.0))
    logger.debug("Signal quality score: %.4f", score)
    return score


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _bandpass_filter(
    signal_1d: np.ndarray,
    fps: float,
    low_hz: float,
    high_hz: float,
) -> np.ndarray:
    """Zero-phase Butterworth bandpass filter.

    Uses second-order sections (``sosfiltfilt``) for numerical stability.

    Args:
        signal_1d: Input signal array.
        fps: Sampling frequency in Hz.
        low_hz: Lower cutoff frequency.
        high_hz: Upper cutoff frequency.

    Returns:
        Filtered signal array of the same length.
    """
    nyquist = fps / 2.0
    low = low_hz / nyquist
    high = high_hz / nyquist

    # Clamp to valid Butterworth range (0, 1) exclusive
    low = float(np.clip(low, 1e-4, 0.9999))
    high = float(np.clip(high, 1e-4, 0.9999))

    if low >= high:
        logger.warning(
            "Bandpass low cutoff (%.4f) >= high cutoff (%.4f) at fps=%.1f; "
            "returning unfiltered signal.",
            low_hz,
            high_hz,
            fps,
        )
        return signal_1d.copy()

    # Reduce filter order if signal is very short
    min_len = 3 * _FILTER_ORDER
    order = _FILTER_ORDER if len(signal_1d) > min_len else max(1, len(signal_1d) // 3)

    try:
        sos = sp_signal.butter(order, [low, high], btype="bandpass", output="sos")
        # Ensure padlen does not exceed signal length
        n_sections = sos.shape[0]
        default_padlen = 3 * (2 * n_sections + 1)
        padlen = min(default_padlen, len(signal_1d) - 1) if len(signal_1d) > 2 else 0
        if padlen <= 0:
            return signal_1d.copy()
        return sp_signal.sosfiltfilt(sos, signal_1d, padlen=padlen)
    except Exception as exc:
        logger.warning("Bandpass filtering failed on signal of length %d: %s. Returning demeaned raw signal.", len(signal_1d), exc)
        return signal_1d - np.mean(signal_1d)


def _compute_power_spectrum(
    signal_1d: np.ndarray,
    fps: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute one-sided FFT power spectrum.

    Args:
        signal_1d: Input signal array.
        fps: Sampling frequency in Hz.

    Returns:
        Tuple ``(freqs, power)`` — frequency axis (Hz) and squared magnitude.
    """
    n = len(signal_1d)
    fft_vals = np.fft.rfft(signal_1d, n=n)
    freqs = np.fft.rfftfreq(n, d=1.0 / fps)
    power = np.abs(fft_vals) ** 2
    return freqs, power
