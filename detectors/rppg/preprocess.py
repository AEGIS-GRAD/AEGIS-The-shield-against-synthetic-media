"""rPPG Preprocessor — face RGB signal extraction.

Adapts the frame extraction and face-crop logic from
detectors/video-classifier/preprocess.py (MTCNN with center-crop fallback).

Key difference from the video-classifier preprocessor:
  - Extracts *every* frame (no downsampling) to preserve temporal structure
    required by the CHROM rPPG algorithm.
  - Returns mean (R, G, B) pixel values over the face bounding box per frame
    rather than resizing/normalizing for a neural-network classifier.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Tuple, Union

import cv2
import numpy as np

try:
    import torch
    HAS_TORCH = True
except Exception:
    torch = None  # type: ignore[assignment]
    HAS_TORCH = False

logger = logging.getLogger(__name__)

# Try importing MTCNN from facenet_pytorch (same pattern as video-classifier)
try:
    from facenet_pytorch import MTCNN
    HAS_MTCNN = True
except ImportError:
    MTCNN = None  # type: ignore[assignment,misc]
    HAS_MTCNN = False
    logger.warning(
        "facenet-pytorch MTCNN not found. Fallback center-crop will be used."
    )


class RppgPreprocessor:
    """Extracts per-frame face-region RGB mean signals from a video for rPPG analysis.

    Produces three time-series R(t), G(t), B(t) that the CHROM algorithm
    operates on.  All frames are extracted at the video's native frame rate
    (no temporal downsampling) so that the rPPG bandpass filter can reference
    the correct sampling frequency.

    Args:
        device: PyTorch device string (e.g. ``"cpu"``, ``"cuda"``).
            Defaults to CUDA if available, otherwise CPU.
        face_scale: Multiplicative padding applied to the detected face
            bounding box before sampling pixel values.  Default 1.0 (no
            padding).  Slight expansion (e.g. 1.1) can include more forehead
            skin, which is rich in rPPG signal.
    """

    def __init__(
        self,
        device: Optional[str] = None,
        face_scale: float = 1.0,
    ) -> None:
        if HAS_TORCH:
            self.device: str = device or (
                "cuda" if torch.cuda.is_available() else "cpu"
            )
        else:
            self.device = "cpu"

        self.face_scale = face_scale
        self.mtcnn: Optional[object] = None

        if HAS_MTCNN:
            try:
                self.mtcnn = MTCNN(
                    keep_all=False,
                    select_largest=True,
                    device=self.device,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to initialise MTCNN detector: %s. "
                    "Fallback face cascade will be used.",
                    exc,
                )

        # OpenCV Haar cascade fallback
        self.face_cascade: Optional[cv2.CascadeClassifier] = None
        try:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            if os.path.exists(cascade_path):
                self.face_cascade = cv2.CascadeClassifier(cascade_path)
        except Exception as exc:
            logger.warning("Failed to load OpenCV Haar cascade: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def preprocess_video(
        self, video_path: Union[str, Path]
    ) -> Tuple[np.ndarray, float, dict]:
        """Extract per-frame mean face-region RGB and evaluate guardrails.

        Returns:
            Tuple of (rgb_signals, fps, metadata_dict).
        """
        video_path_str = str(video_path)
        cap = cv2.VideoCapture(video_path_str)

        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path_str}")

        fps: float = cap.get(cv2.CAP_PROP_FPS) or 30.0
        rgb_signals: list[np.ndarray] = []
        frame_idx = 0
        detected_faces_count = 0
        total_luminance = 0.0
        total_skin_ratio = 0.0

        _REDETECT_INTERVAL = 15
        cached_box: Optional[tuple[int, int, int, int]] = None
        cached_is_real: bool = False

        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                if frame_idx % _REDETECT_INTERVAL == 0:
                    cached_box, cached_is_real = self._detect_face_box(rgb_frame)

                if cached_is_real:
                    detected_faces_count += 1

                box = cached_box
                mean_rgb = self._mean_rgb_in_box(rgb_frame, box)
                rgb_signals.append(mean_rgb)

                # Compute frame luminance Y = 0.299*R + 0.587*G + 0.114*B
                lum = 0.299 * mean_rgb[0] + 0.587 * mean_rgb[1] + 0.114 * mean_rgb[2]
                total_luminance += lum

                # Skin-tone ratio check in YCrCb for occlusion detection
                if box is not None:
                    bx1, by1, bx2, by2 = box
                    roi = rgb_frame[by1:by2, bx1:bx2]
                else:
                    roi = rgb_frame
                if roi.size > 0:
                    ycrcb = cv2.cvtColor(roi, cv2.COLOR_RGB2YCrCb)
                    cr = ycrcb[:, :, 1]
                    cb = ycrcb[:, :, 2]
                    skin_mask = (cr >= 130) & (cr <= 175) & (cb >= 75) & (cb <= 130)
                    total_skin_ratio += float(np.mean(skin_mask))

                frame_idx += 1
        finally:
            cap.release()

        if not rgb_signals:
            raise ValueError(
                f"No frames could be extracted from video: {video_path_str}"
            )

        n_frames = len(rgb_signals)
        duration_sec = n_frames / fps if fps > 0 else 0.0
        mean_luminance = total_luminance / n_frames if n_frames > 0 else 0.0
        avg_skin_ratio = total_skin_ratio / n_frames if n_frames > 0 else 0.0
        face_detection_ratio = detected_faces_count / n_frames if n_frames > 0 else 0.0

        metadata = {
            "total_frames": n_frames,
            "fps": fps,
            "duration_sec": round(duration_sec, 2),
            "mean_luminance": round(mean_luminance, 2),
            "face_detection_ratio": round(face_detection_ratio, 2),
            "avg_skin_ratio": round(avg_skin_ratio, 2),
            "guardrail_triggered": False,
            "flags": [],
            "claim": "rPPG signal extracted across facial region.",
        }

        # Guardrail 1: Duration check (< 2.0 seconds or < 30 frames)
        if duration_sec < 2.0 or n_frames < 30:
            metadata["guardrail_triggered"] = True
            metadata["flags"].append("insufficient_duration")
            metadata["flags"].append("insufficient_signal")
            metadata["claim"] = (
                f"Video duration ({duration_sec:.1f}s, {n_frames} frames) is too short "
                "for stable physiological BVP pulse extraction (minimum 2.0s required)."
            )

        # Guardrail 2: Illumination check (dark / underexposed video)
        elif mean_luminance < 18.0:
            metadata["guardrail_triggered"] = True
            metadata["flags"].append("insufficient_lighting")
            metadata["flags"].append("insufficient_signal")
            metadata["claim"] = (
                f"Video illumination is too low (mean luminance {mean_luminance:.1f}/255) "
                "for optical skin-tone reflectance analysis."
            )

        # Guardrail 3: Face visibility & occlusion check
        elif (face_detection_ratio > 0 and face_detection_ratio < 0.25) or (avg_skin_ratio < 0.12):
            metadata["guardrail_triggered"] = True
            metadata["flags"].append("face_occluded")
            metadata["flags"].append("insufficient_signal")
            metadata["claim"] = (
                f"Face was undetected or occluded across frames (skin coverage {avg_skin_ratio*100:.1f}% < 12%) — "
                "insufficient facial surface for rPPG analysis."
            )

        return np.array(rgb_signals, dtype=np.float32), fps, metadata

    def get_face_rgb_signals(
        self, video_path: Union[str, Path]
    ) -> Tuple[np.ndarray, float]:
        """Extract per-frame mean face-region (R, G, B) from a video.
        Maintains backward compatibility with original caller interface.
        """
        signals, fps, _ = self.preprocess_video(video_path)
        return signals, fps

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_face_box(
        self, rgb_frame: np.ndarray
    ) -> Tuple[Optional[tuple[int, int, int, int]], bool]:
        """Return ``((x1, y1, x2, y2), is_real_detection)`` face box or fallback."""
        h, w, _ = rgb_frame.shape

        # Try MTCNN first
        if self.mtcnn is not None:
            try:
                boxes, _ = self.mtcnn.detect(rgb_frame)  # type: ignore[union-attr]
                if boxes is not None and len(boxes) > 0:
                    box = boxes[0].astype(int)
                    x1 = int(max(0, box[0]))
                    y1 = int(max(0, box[1]))
                    x2 = int(min(w, box[2]))
                    y2 = int(min(h, box[3]))
                    if x2 > x1 and y2 > y1:
                        if self.face_scale != 1.0:
                            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                            half_w = (x2 - x1) / 2 * self.face_scale
                            half_h = (y2 - y1) / 2 * self.face_scale
                            x1 = int(max(0, cx - half_w))
                            y1 = int(max(0, cy - half_h))
                            x2 = int(min(w, cx + half_w))
                            y2 = int(min(h, cy + half_h))
                        return (x1, y1, x2, y2), True
            except Exception as exc:
                logger.debug("MTCNN detection error: %s", exc)

        # Try Haar cascade next
        if self.face_cascade is not None:
            try:
                gray = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2GRAY)
                faces = self.face_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=3, minSize=(40, 40)
                )
                if len(faces) > 0:
                    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
                    fx, fy, fw, fh = faces[0]
                    x1 = int(max(0, fx))
                    y1 = int(max(0, fy))
                    x2 = int(min(w, fx + fw))
                    y2 = int(min(h, fy + fh))
                    return (x1, y1, x2, y2), True
            except Exception as exc:
                logger.debug("Haar cascade error: %s", exc)

        # Fallback to center crop marked as NOT a real face detection
        return self._center_square_box(rgb_frame), False

    def _center_square_box(
        self, frame: np.ndarray
    ) -> tuple[int, int, int, int]:
        """Return a center-square bounding box as fallback."""
        h, w, _ = frame.shape
        crop_dim = min(h, w)
        x1 = (w - crop_dim) // 2
        y1 = (h - crop_dim) // 2
        return (x1, y1, x1 + crop_dim, y1 + crop_dim)

    @staticmethod
    def _mean_rgb_in_box(
        rgb_frame: np.ndarray,
        box: Optional[tuple[int, int, int, int]],
    ) -> np.ndarray:
        """Compute mean [R, G, B] pixel values inside *box*.

        Falls back to the full frame if *box* is ``None``.

        Returns:
            1-D float32 array ``[R_mean, G_mean, B_mean]``.
        """
        if box is not None:
            x1, y1, x2, y2 = box
            roi = rgb_frame[y1:y2, x1:x2]
        else:
            roi = rgb_frame

        # roi shape: (H, W, 3)  — average over spatial dimensions
        return roi.reshape(-1, 3).mean(axis=0).astype(np.float32)
