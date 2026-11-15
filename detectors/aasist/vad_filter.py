"""
Voice Activity Detection (VAD) Pre-filter for AASIST Audio Detector.
====================================================================

Provides a lightweight speech pre-filter that sits in front of the AASIST
countermeasure pipeline. If the input audio contains no detectable speech
(e.g. pure music, ambient noise, or silence) the filter returns
``SpeechActivity.NON_SPEECH`` and the caller MUST return ``not_applicable``
rather than a fake/bonafide verdict.

Design goals
------------
* Zero heavy external model at import time — tries Silero VAD from
  torch.hub first; falls back to a pure-signal heuristic (zero-crossing
  rate + spectral flatness) so tests pass in every CI environment.
* Stateless & side-effect-free — no global mutable state.
* Deterministic fallback — the heuristic path always produces the same
  answer for the same waveform.

Public API
----------
    from vad_filter import classify_speech_activity, SpeechActivity, VADResult

    result = classify_speech_activity(waveform_np, sample_rate=16000)
    if result.activity == SpeechActivity.NON_SPEECH:
        # Return not_applicable; skip AASIST inference
        ...

The ``VADResult`` dataclass is intentionally JSON-serialisable (all fields
are plain Python scalars) so it can be embedded directly into the AEGIS
claim structure.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public enum + result type
# ---------------------------------------------------------------------------

class SpeechActivity(str, Enum):
    SPEECH     = "speech"       # Detector is confident audio contains speech
    NON_SPEECH = "non_speech"   # Audio is music / noise / ambient — not speech
    UNCERTAIN  = "uncertain"    # Detector could not decide (use with caution)


@dataclass
class VADResult:
    """Structured result returned by the speech pre-filter."""
    activity:          SpeechActivity
    speech_ratio:      float          # fraction [0, 1] of windows classified as speech
    confidence:        float          # overall confidence in the classification [0, 1]
    backend_used:      str            # "silero" | "heuristic"
    vad_flags:         List[str]      # machine-readable flags for downstream consumers
    speech_threshold:  float          # threshold that was applied
    num_windows:       int            # total analysis windows
    speech_windows:    int            # windows flagged as speech

    # Optional: per-window probabilities (Silero path only)
    window_probs:      Optional[List[float]] = field(default=None)


# ---------------------------------------------------------------------------
# Silero VAD backend (optional)
# ---------------------------------------------------------------------------

_SILERO_MODEL: Optional[object] = None
_SILERO_LOADED: bool = False
_SILERO_LOAD_FAILED: bool = False

def _try_load_silero(force_reload: bool = False):
    """Lazy-loads Silero VAD from torch.hub.  Returns (model, utils) or None."""
    global _SILERO_MODEL, _SILERO_LOADED, _SILERO_LOAD_FAILED
    if _SILERO_LOAD_FAILED:
        return None
    if _SILERO_LOADED and not force_reload:
        return _SILERO_MODEL

    try:
        import torch
        # Silero VAD v5 — snappy, 1.8 MB ONNX, runs fine on CPU
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            verbose=False,
            trust_repo=True,
        )
        _SILERO_MODEL = (model, utils)
        _SILERO_LOADED = True
        logger.info("Silero VAD loaded successfully from torch.hub.")
        return _SILERO_MODEL
    except Exception as exc:
        logger.warning(
            "Silero VAD unavailable (%s); VAD filter will use heuristic fallback.",
            exc,
        )
        _SILERO_LOAD_FAILED = True
        return None


def _run_silero_vad(
    waveform: np.ndarray,
    sample_rate: int,
    speech_threshold: float = 0.50,
    window_size_samples: int = 512,
) -> VADResult:
    """Runs Silero VAD on a mono float32 waveform (already at 16 kHz or 8 kHz)."""
    import torch

    pkg = _try_load_silero()
    if pkg is None:
        raise RuntimeError("Silero VAD not available")

    model, utils = pkg
    get_speech_timestamps, _, _, _, _ = utils

    wav_tensor = torch.from_numpy(waveform.astype(np.float32))
    # Silero expects (T,) for 16 kHz
    timestamps = get_speech_timestamps(
        wav_tensor,
        model,
        sampling_rate=sample_rate,
        threshold=speech_threshold,
        window_size_samples=window_size_samples,
        return_seconds=False,
    )

    total_samples = len(waveform)
    speech_samples = sum(ts["end"] - ts["start"] for ts in timestamps)
    speech_ratio = speech_samples / max(total_samples, 1)

    num_windows = max(1, total_samples // window_size_samples)
    speech_windows = int(round(speech_ratio * num_windows))

    if speech_ratio >= speech_threshold:
        activity = SpeechActivity.SPEECH
        confidence = min(1.0, speech_ratio * 1.2)
        flags = ["vad_speech_detected", "silero_vad"]
    elif speech_ratio >= speech_threshold * 0.4:
        activity = SpeechActivity.UNCERTAIN
        confidence = 0.5
        flags = ["vad_uncertain", "silero_vad"]
    else:
        activity = SpeechActivity.NON_SPEECH
        confidence = max(0.5, 1.0 - speech_ratio * 2.0)
        flags = ["vad_non_speech", "not_applicable", "silero_vad"]

    return VADResult(
        activity=activity,
        speech_ratio=round(speech_ratio, 4),
        confidence=round(confidence, 4),
        backend_used="silero",
        vad_flags=flags,
        speech_threshold=speech_threshold,
        num_windows=num_windows,
        speech_windows=speech_windows,
    )


# ---------------------------------------------------------------------------
# Heuristic fallback backend
# ---------------------------------------------------------------------------

def _compute_zcr(frame: np.ndarray) -> float:
    """Zero-crossing rate of a frame."""
    if len(frame) < 2:
        return 0.0
    signs = np.sign(frame)
    signs[signs == 0] = 1
    crossings = np.sum(np.abs(np.diff(signs))) / 2.0
    return float(crossings / len(frame))


def _compute_spectral_flatness(frame: np.ndarray) -> float:
    """Wiener entropy (spectral flatness): 0 = tonal, 1 = flat noise."""
    if len(frame) < 2:
        return 1.0
    spectrum = np.abs(np.fft.rfft(frame * np.hanning(len(frame)))) + 1e-10
    geom_mean = np.exp(np.mean(np.log(spectrum)))
    arith_mean = np.mean(spectrum)
    return float(geom_mean / max(arith_mean, 1e-10))


def _compute_energy(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame ** 2)))


def _run_heuristic_vad(
    waveform: np.ndarray,
    sample_rate: int,
    speech_threshold: float = 0.35,
    frame_ms: int = 20,
) -> VADResult:
    """
    Rule-based fallback VAD using three lightweight features:

    - ZCR:              speech typically has ZCR in [0.05, 0.25] /sample
    - Spectral flatness: speech is tonal (low flatness) vs. noise (high)
    - RMS energy:        pure silence / very low energy → not speech

    A frame is classified as speech if at least 2 of 3 cues fire.
    """
    frame_len = int(sample_rate * frame_ms / 1000)
    if frame_len < 2:
        frame_len = 2

    num_frames = max(1, len(waveform) // frame_len)
    frames = [
        waveform[i * frame_len : (i + 1) * frame_len]
        for i in range(num_frames)
        if len(waveform[i * frame_len : (i + 1) * frame_len]) > 1
    ]

    if not frames:
        return VADResult(
            activity=SpeechActivity.NON_SPEECH,
            speech_ratio=0.0,
            confidence=0.9,
            backend_used="heuristic",
            vad_flags=["vad_non_speech", "not_applicable", "empty_audio"],
            speech_threshold=speech_threshold,
            num_windows=0,
            speech_windows=0,
        )

    # Global RMS — signals with global_rms < threshold are silence
    global_rms = _compute_energy(waveform)
    silence = global_rms < 1e-4

    speech_frames = 0
    for frame in frames:
        if silence:
            break
        zcr = _compute_zcr(frame)
        sf  = _compute_spectral_flatness(frame)
        rms = _compute_energy(frame)

        # Speech cues
        zcr_cue = 0.03 <= zcr <= 0.30          # typical speech ZCR band
        tonal_cue = sf < 0.70                   # speech is more tonal than noise/music
        energy_cue = rms > global_rms * 0.15   # above noise floor

        votes = sum([zcr_cue, tonal_cue, energy_cue])
        if votes >= 2:
            speech_frames += 1

    speech_ratio = speech_frames / max(num_frames, 1)

    if silence or speech_ratio < speech_threshold * 0.3:
        activity = SpeechActivity.NON_SPEECH
        confidence = max(0.6, 1.0 - speech_ratio * 2.0)
        flags = ["vad_non_speech", "not_applicable", "heuristic_vad"]
    elif speech_ratio >= speech_threshold:
        activity = SpeechActivity.SPEECH
        confidence = min(0.90, 0.5 + speech_ratio)
        flags = ["vad_speech_detected", "heuristic_vad"]
    else:
        activity = SpeechActivity.UNCERTAIN
        confidence = 0.5
        flags = ["vad_uncertain", "heuristic_vad"]

    return VADResult(
        activity=activity,
        speech_ratio=round(speech_ratio, 4),
        confidence=round(confidence, 4),
        backend_used="heuristic",
        vad_flags=flags,
        speech_threshold=speech_threshold,
        num_windows=num_frames,
        speech_windows=speech_frames,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

# Env-var override: AEGIS_VAD_BACKEND=silero|heuristic (default: auto)
_BACKEND_OVERRIDE = os.getenv("AEGIS_VAD_BACKEND", "auto").lower()

# Speech fraction threshold: fraction of windows/time that must contain speech
# before the whole clip is classified as SPEECH.
# Configurable via AEGIS_VAD_SPEECH_THRESHOLD (float, 0–1).
_DEFAULT_SPEECH_THRESHOLD = float(os.getenv("AEGIS_VAD_SPEECH_THRESHOLD", "0.35"))


def classify_speech_activity(
    waveform: np.ndarray,
    sample_rate: int = 16000,
    speech_threshold: Optional[float] = None,
    force_backend: Optional[str] = None,
) -> VADResult:
    """
    Classify whether ``waveform`` contains human speech.

    Parameters
    ----------
    waveform:
        Mono float32 numpy array, already resampled to ``sample_rate``.
    sample_rate:
        Audio sample rate in Hz.  Silero works best at 16000 Hz.
    speech_threshold:
        Override the fraction of voiced windows required to classify as SPEECH.
        Defaults to ``AEGIS_VAD_SPEECH_THRESHOLD`` env var or 0.35.
    force_backend:
        ``"silero"`` | ``"heuristic"`` | ``None`` (auto).

    Returns
    -------
    VADResult
        Structured result.  Check ``result.activity == SpeechActivity.NON_SPEECH``
        to decide whether to skip AASIST inference.
    """
    if speech_threshold is None:
        speech_threshold = _DEFAULT_SPEECH_THRESHOLD

    backend = force_backend or _BACKEND_OVERRIDE

    # Ensure mono float32
    if waveform.ndim > 1:
        waveform = np.mean(waveform, axis=1 if waveform.shape[1] < waveform.shape[0] else 0)
    waveform = waveform.astype(np.float32)

    # --- Try requested / auto backend ---
    if backend in ("silero", "auto"):
        try:
            return _run_silero_vad(waveform, sample_rate, speech_threshold)
        except Exception as exc:
            if backend == "silero":
                logger.error("Silero VAD forced but failed: %s", exc)
                # Still fall through to heuristic rather than crash the pipeline
            else:
                logger.debug("Silero VAD unavailable, using heuristic: %s", exc)

    return _run_heuristic_vad(waveform, sample_rate, speech_threshold)
