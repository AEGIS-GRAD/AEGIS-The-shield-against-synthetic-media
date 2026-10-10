"""
Streaming rPPG core (Week 2 / Task 5).

The file-based rPPG detector needs a whole clip: it extracts the colour trace
for every frame, then filters + spectrum-analyses the full signal once.
Here the same signal-processing chain (POS projection -> detrend -> band-pass
-> spectral peak/SNR) runs on a ROLLING buffer, re-evaluated every `hop_sec`.

Differences from the file version:
  * input is one (t, mean-RGB-of-face-ROI) sample at a time, not a video file
  * timestamps are used and the buffer is resampled to a uniform grid, so
    dropped / jittery frames from a live feed do not distort the spectrum
  * "not ready" state until `min_sec` of signal exists (no fake scores)
  * face-lost gaps longer than `max_gap_sec` reset the buffer (a pulse trace
    spliced across a gap is meaningless)
Only numpy + scipy are needed.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
from scipy.signal import butter, filtfilt, detrend, welch


@dataclass
class RPPGResult:
    ready: bool
    score: Optional[float]      # 0..1, higher = more likely SYNTHETIC (no pulse)
    hr_bpm: Optional[float]     # dominant pulse frequency in bpm
    snr_db: Optional[float]     # pulse-band SNR around the peak
    window_sec: float           # seconds of signal currently buffered
    reason: str = ""

    def to_dict(self):
        return asdict(self)


class StreamingRPPG:
    def __init__(self, fps: float = 10.0, window_sec: float = 10.0,
                 min_sec: float = 6.0, hop_sec: float = 1.0,
                 band=(0.7, 3.0), max_gap_sec: float = 1.0,
                 snr_midpoint_db: float = 1.0, snr_slope: float = 0.6):
        if band[1] >= fps / 2:
            raise ValueError(f"band upper edge {band[1]} Hz must be < fps/2 ({fps/2})")
        self.fps, self.window_sec, self.min_sec = fps, window_sec, min_sec
        self.hop_sec, self.band, self.max_gap_sec = hop_sec, band, max_gap_sec
        self.snr_mid, self.snr_slope = snr_midpoint_db, snr_slope
        self._t: deque = deque()
        self._rgb: deque = deque()
        self._last_eval_t = -1e9
        self.last: RPPGResult = RPPGResult(False, None, None, None, 0.0, "warming up")

    # ------------------------------------------------------------------ state
    def reset(self):
        self._t.clear(); self._rgb.clear()
        self._last_eval_t = -1e9
        self.last = RPPGResult(False, None, None, None, 0.0, "reset")

    def buffered_sec(self) -> float:
        return (self._t[-1] - self._t[0]) if len(self._t) > 1 else 0.0

    # ------------------------------------------------------------------- push
    def push(self, t: float, rgb) -> RPPGResult:
        """Add one sample. rgb = mean (R,G,B) of the face ROI for this frame.
        Returns the latest result (re-computed at most once per hop_sec)."""
        rgb = np.asarray(rgb, dtype=np.float64)
        if rgb.shape != (3,) or not np.all(np.isfinite(rgb)):
            return self.last
        if self._t and t <= self._t[-1]:           # out-of-order / duplicate
            return self.last
        if self._t and (t - self._t[-1]) > self.max_gap_sec:
            self.reset()                            # face lost too long
            self.last = RPPGResult(False, None, None, None, 0.0, "gap -> buffer reset")
        self._t.append(float(t)); self._rgb.append(rgb)
        while self._t and (self._t[-1] - self._t[0]) > self.window_sec:
            self._t.popleft(); self._rgb.popleft()

        if self.buffered_sec() < self.min_sec:
            self.last = RPPGResult(False, None, None, None, self.buffered_sec(),
                                   f"warming up {self.buffered_sec():.1f}/{self.min_sec:.0f}s")
        elif t - self._last_eval_t >= self.hop_sec:
            self._last_eval_t = t
            self.last = self._evaluate()
        return self.last

    def notify_no_face(self, t: float):
        """Call when the detector finds no face; long gaps reset the buffer."""
        if self._t and (t - self._t[-1]) > self.max_gap_sec:
            self.reset()
            self.last = RPPGResult(False, None, None, None, 0.0, "no face")

    # --------------------------------------------------------------- the maths
    def _resample(self):
        t = np.asarray(self._t); x = np.asarray(self._rgb)          # (N,), (N,3)
        grid = np.arange(t[0], t[-1], 1.0 / self.fps)
        return np.stack([np.interp(grid, t, x[:, c]) for c in range(3)], axis=1)

    @staticmethod
    def _pos(rgb: np.ndarray, win: int) -> np.ndarray:
        """POS (Wang et al. 2017) with overlap-add over short windows."""
        n = len(rgb); h = np.zeros(n)
        P = np.array([[0, 1, -1], [-2, 1, 1]], dtype=np.float64)
        for s in range(0, n - win + 1):
            seg = rgb[s:s + win]
            c = seg / (seg.mean(axis=0) + 1e-9)                      # temporal norm
            sig = P @ c.T                                             # (2,win)
            p = sig[0] + (sig[0].std() / (sig[1].std() + 1e-9)) * sig[1]
            h[s:s + win] += p - p.mean()
        return h

    def _evaluate(self) -> RPPGResult:
        rgb = self._resample()
        n = len(rgb)
        win = max(int(1.6 * self.fps), 8)
        if n < win + 4:
            return RPPGResult(False, None, None, None, self.buffered_sec(), "too short")
        sig = self._pos(rgb, win)
        sig = detrend(sig)
        b, a = butter(3, [self.band[0], self.band[1]], btype="band", fs=self.fps)
        if n <= 3 * max(len(a), len(b)):
            return RPPGResult(False, None, None, None, self.buffered_sec(), "too short")
        sig = filtfilt(b, a, sig)

        nper = min(n, int(8 * self.fps))
        f, pxx = welch(sig, fs=self.fps, nperseg=nper, noverlap=nper // 2,
                       nfft=max(1024, nper * 4))
        m = (f >= self.band[0]) & (f <= self.band[1])
        if not m.any() or pxx[m].sum() <= 0:
            return RPPGResult(True, 1.0, None, None, self.buffered_sec(), "flat signal")
        fb, pb = f[m], pxx[m]
        k = int(np.argmax(pb)); f0 = fb[k]
        sig_mask = (np.abs(fb - f0) <= 0.1) | (np.abs(fb - 2 * f0) <= 0.1)  # fundamental + 2nd harmonic
        p_sig = pb[sig_mask].sum(); p_noise = pb[~sig_mask].sum() + 1e-18
        snr_db = 10.0 * np.log10(p_sig / p_noise + 1e-12)
        # strong periodic pulse -> low "synthetic" score. Logistic map; the
        # midpoint/slope are heuristics to be calibrated on the /eval set.
        score = float(1.0 / (1.0 + np.exp(self.snr_slope * (snr_db - self.snr_mid))))
        return RPPGResult(True, score, float(f0 * 60.0), float(snr_db),
                          self.buffered_sec(), "ok")


def roi_mean_rgb(frame_bgr: np.ndarray, box=None) -> Optional[np.ndarray]:
    """Mean (R,G,B) of the face ROI. Uses the central 60% of the box (drops
    background/hair at the borders). box=(x1,y1,x2,y2); None -> whole frame."""
    if box is not None:
        x1, y1, x2, y2 = box
        w, h = x2 - x1, y2 - y1
        x1, x2 = x1 + int(0.2 * w), x2 - int(0.2 * w)
        y1, y2 = y1 + int(0.2 * h), y2 - int(0.2 * h)
        frame_bgr = frame_bgr[y1:y2, x1:x2]
    if frame_bgr.size == 0:
        return None
    b, g, r = frame_bgr.reshape(-1, 3).mean(axis=0)
    return np.array([r, g, b])
