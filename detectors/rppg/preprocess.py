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
                    "Fallback center-crop will be used.",
                    exc,
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_face_rgb_signals(
        self, video_path: Union[str, Path]
    ) -> Tuple[np.ndarray, float]:
        """Extract per-frame mean face-region (R, G, B) from a video.

        Args:
            video_path: Path to input video file.

        Returns:
            A tuple ``(rgb_signals, fps)`` where:
            - ``rgb_signals`` is a ``float32`` array of shape ``(N, 3)``
              containing mean [R, G, B] values in [0, 255] for each frame.
            - ``fps`` is the video's native frames-per-second as a float.

        Raises:
            ValueError: If the video cannot be opened or yields no frames.
        """
        video_path_str = str(video_path)
        cap = cv2.VideoCapture(video_path_str)

        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path_str}")

        fps: float = cap.get(cv2.CAP_PROP_FPS) or 30.0
        rgb_signals: list[np.ndarray] = []
        frame_idx = 0

        # MTCNN box cache: reuse the detected box for efficiency when MTCNN
        # is available.  Re-detect every `_REDETECT_INTERVAL` frames to adapt
        # to slight head movement.
        _REDETECT_INTERVAL = 15
        cached_box: Optional[tuple[int, int, int, int]] = None

        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                # OpenCV reads BGR — convert to RGB immediately.
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Detect or reuse face box
                if frame_idx % _REDETECT_INTERVAL == 0:
                    cached_box = self._detect_face_box(rgb_frame)

                box = cached_box
                mean_rgb = self._mean_rgb_in_box(rgb_frame, box)
                rgb_signals.append(mean_rgb)
                frame_idx += 1
        finally:
            cap.release()

        if not rgb_signals:
            raise ValueError(
                f"No frames could be extracted from video: {video_path_str}"
            )

        logger.info(
            "Extracted %d frames at %.2f fps from '%s'.",
            frame_idx,
            fps,
            video_path_str,
        )

        return np.array(rgb_signals, dtype=np.float32), fps

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_face_box(
        self, rgb_frame: np.ndarray
    ) -> Optional[tuple[int, int, int, int]]:
        """Return ``(x1, y1, x2, y2)`` face box clipped to image bounds, or ``None``."""
        if self.mtcnn is not None:
            try:
                boxes, _ = self.mtcnn.detect(rgb_frame)  # type: ignore[union-attr]
                if boxes is not None and len(boxes) > 0:
                    h, w, _ = rgb_frame.shape
                    box = boxes[0].astype(int)
                    x1 = int(max(0, box[0]))
                    y1 = int(max(0, box[1]))
                    x2 = int(min(w, box[2]))
                    y2 = int(min(h, box[3]))
                    if x2 > x1 and y2 > y1:
                        # Optionally expand box
                        if self.face_scale != 1.0:
                            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                            half_w = (x2 - x1) / 2 * self.face_scale
                            half_h = (y2 - y1) / 2 * self.face_scale
                            x1 = int(max(0, cx - half_w))
                            y1 = int(max(0, cy - half_h))
                            x2 = int(min(w, cx + half_w))
                            y2 = int(min(h, cy + half_h))
                        return (x1, y1, x2, y2)
            except Exception as exc:
                logger.debug("MTCNN detection error: %s. Falling back to center crop.", exc)

        # TODO: MTCNN fallback used. Replace with proper face detector when
        # facenet-pytorch is available/configured.
        return self._center_square_box(rgb_frame)

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
