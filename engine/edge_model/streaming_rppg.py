# engine/edge_model/streaming_rppg.py
"""Streaming rPPG detector — CHROM rolling-window for live surveillance.

Fixes applied vs Month 1 rPPG microservice:
  M2-L1: Motionless face guardrail (variance check → neutral 0.5, never 1.0)
  M2-L2: Explicit 'warming_up' state during initial buffer fill (no silent period)
  M2-L3: 'not_applicable' when face lost (no whole-frame fallback)
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Any, Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class StreamingRppgDetector:
    """Real-time streaming rPPG detector using a rolling FIFO buffer."""

    # Minimum RGB variance to consider a face as "live" (not frozen/still)
    _MOTIONLESS_VARIANCE_THRESHOLD: float = 1e-4

    def __init__(
        self,
        fps: float = 30.0,
        window_seconds: float = 6.0,
        stride_frames: int = 15,
    ) -> None:
        self.fps = max(1.0, float(fps))
        self.window_size = int(self.fps * window_seconds)
        self.stride_frames = max(1, stride_frames)

        self._buffer: deque = deque(maxlen=self.window_size)
        self._frames_since_calc: int = 0
        self._last_result: Dict[str, Any] = self._warmup_response(0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_frame(
        self,
        mean_rgb: Optional[np.ndarray],
        face_detected: bool = True,
    ) -> Dict[str, Any]:
        """Ingest one frame and return a rPPG assessment dict.

        Args:
            mean_rgb: Shape-(3,) float array [R_mean, G_mean, B_mean] of
                      the face ROI, or None when face is absent.
            face_detected: Whether a face was localised this frame.

        Returns:
            Dict with keys: status, score, confidence, bpm, quality,
            verdict, claim, flags.
        """
        # --- M2-L3 Fix ---------------------------------------------------
        if not face_detected or mean_rgb is None:
            return {
                "status": "not_applicable",
                "score": None,
                "confidence": 0.0,
                "bpm": None,
                "quality": 0.0,
                "verdict": "inconclusive",
                "claim": "Face tracking lost — rPPG analysis not applicable for this frame.",
                "flags": ["face_lost", "not_applicable"],
            }

        self._buffer.append(np.asarray(mean_rgb, dtype=np.float32))
        self._frames_since_calc += 1

        # --- M2-L2 Fix ---------------------------------------------------
        buffered = len(self._buffer)
        if buffered < self.window_size:
            self._last_result = self._warmup_response(buffered)
            return self._last_result

        # Throttle recalculation to every `stride_frames` frames
        if (self._frames_since_calc < self.stride_frames
                and self._last_result.get("score") is not None):
            return self._last_result

        self._frames_since_calc = 0
        signal = np.array(self._buffer)  # (N, 3)

        # --- M2-L1 Fix ---------------------------------------------------
        variance = float(np.var(signal, axis=0).sum())
        if variance < self._MOTIONLESS_VARIANCE_THRESHOLD:
            result: Dict[str, Any] = {
                "status": "motionless_face",
                "score": 0.5,
                "confidence": 0.0,
                "bpm": 0.0,
                "quality": 0.0,
                "verdict": "inconclusive",
                "claim": (
                    f"Face has no measurable micro-variation (Σvar={variance:.2e}). "
                    "Cardiac signal cannot be extracted — defaulting to neutral."
                ),
                "flags": ["motionless_face", "insufficient_signal"],
            }
            self._last_result = result
            return result

        # Normal CHROM pipeline
        try:
            pulse = self._chrom(signal)
            bpm, quality = self._bpm_and_quality(pulse)

            score = float(np.clip(1.0 - quality, 0.0, 1.0))
            confidence = round(abs(score - 0.5) * 2.0, 4)
            verdict = "synthetic" if score > 0.5 else "authentic"

            result = {
                "status": "ok",
                "score": round(score, 4),
                "confidence": confidence,
                "bpm": round(bpm, 1),
                "quality": round(quality, 4),
                "verdict": verdict,
                "claim": (
                    f"BVP pulse extracted via CHROM. Heart rate {bpm:.1f} BPM, "
                    f"spectral purity {quality:.2f}."
                ),
                "flags": [],
            }
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Streaming rPPG calculation error: %s", exc)
            result = {
                "status": "error",
                "score": 0.5,
                "confidence": 0.0,
                "bpm": 0.0,
                "quality": 0.0,
                "verdict": "inconclusive",
                "claim": f"Computation error: {exc}",
                "flags": ["computation_error"],
            }

        self._last_result = result
        return result

    def reset(self) -> None:
        """Clear the temporal buffer (e.g. when camera source changes)."""
        self._buffer.clear()
        self._frames_since_calc = 0
        self._last_result = self._warmup_response(0)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _warmup_response(self, buffered: int) -> Dict[str, Any]:
        progress = round(buffered / max(1, self.window_size), 2)
        return {
            "status": "warming_up",
            "progress": progress,
            "buffered_frames": buffered,
            "target_frames": self.window_size,
            "score": None,
            "confidence": 0.0,
            "bpm": None,
            "quality": 0.0,
            "verdict": "inconclusive",
            "claim": (
                f"Warming up rPPG buffer "
                f"({buffered}/{self.window_size} frames, {progress*100:.0f}%)."
            ),
            "flags": ["warming_up"],
        }

    def _chrom(self, signal: np.ndarray) -> np.ndarray:
        """CHROM algorithm (De Haan & Jeanne, 2013)."""
        mean_rgb = signal.mean(axis=0)
        mean_rgb = np.where(mean_rgb == 0.0, 1.0, mean_rgb)
        rn = signal[:, 0] / mean_rgb[0]
        gn = signal[:, 1] / mean_rgb[1]
        bn = signal[:, 2] / mean_rgb[2]

        xc = 3.0 * rn - 2.0 * gn
        yc = 1.5 * rn + gn - 1.5 * bn

        std_yc = float(np.std(yc))
        alpha = (float(np.std(xc)) / std_yc) if std_yc > 1e-9 else 0.0
        s = xc - alpha * yc
        return self._bandpass(s)

    def _bandpass(self, s: np.ndarray) -> np.ndarray:
        from scipy import signal as sp_signal  # local import to keep module importable without scipy
        nyq = self.fps / 2.0
        low = float(np.clip(0.7 / nyq, 1e-4, 0.9999))
        high = float(np.clip(4.0 / nyq, 1e-4, 0.9999))
        if low >= high:
            return s - s.mean()
        sos = sp_signal.butter(3, [low, high], btype="bandpass", output="sos")
        padlen = min(15, len(s) - 1) if len(s) > 2 else 0
        if padlen <= 0:
            return s - s.mean()
        return sp_signal.sosfiltfilt(sos, s, padlen=padlen)

    def _bpm_and_quality(self, pulse: np.ndarray) -> Tuple[float, float]:
        n = len(pulse)
        power = np.abs(np.fft.rfft(pulse, n=n)) ** 2
        freqs = np.fft.rfftfreq(n, d=1.0 / self.fps)
        cardiac = (freqs >= 0.7) & (freqs <= 4.0)

        if not np.any(cardiac):
            return 60.0, 0.0

        band_power = float(power[cardiac].sum())
        if band_power < 1e-12:
            return 60.0, 0.0

        peak_freq = float(freqs[cardiac][np.argmax(power[cardiac])])
        peak_power = float(power[cardiac].max())
        bpm = peak_freq * 60.0
        quality = float(np.clip(peak_power / band_power, 0.0, 1.0))
        return bpm, quality