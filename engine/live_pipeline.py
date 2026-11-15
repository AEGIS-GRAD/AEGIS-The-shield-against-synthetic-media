# engine/live_pipeline.py
"""Live dual-model surveillance pipeline.

Fuses:
  1. SlidingWindowDetector (MobileNetV3-Small edge CNN) — spatial / frame-level
  2. StreamingRppgDetector (CHROM rolling window) — physiological / temporal

Failure modes addressed: M2-L1, M2-L2, M2-L3 (see streaming_rppg.py).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from engine.edge_model.sliding_window import SlidingWindowDetector
from engine.edge_model.streaming_rppg import StreamingRppgDetector

logger = logging.getLogger(__name__)

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _preprocess_frame_for_classifier(
    bgr_crop: np.ndarray,
) -> np.ndarray:
    """Resize + ImageNet normalise a BGR crop → (3, 224, 224) float32."""
    rgb = cv2.cvtColor(cv2.resize(bgr_crop, (224, 224)), cv2.COLOR_BGR2RGB)
    chw = rgb.astype(np.float32) / 255.0
    chw = (chw - _IMAGENET_MEAN) / _IMAGENET_STD
    return chw.transpose(2, 0, 1)   # (3, 224, 224)


class LiveSurveillancePipeline:
    """Multi-model live surveillance pipeline (Role 5 deliverable).

    Args:
        spatial_backend: Backend for SlidingWindowDetector
                         ('pytorch', 'onnx_fp32', 'onnx_int8').
        fps: Expected stream frame rate. Passed to streaming rPPG.
        rppg_window_sec: Temporal window for rPPG rolling buffer (seconds).
        weight_spatial: Fusion weight for spatial CNN score.
        weight_rppg:    Fusion weight for rPPG score.
    """

    def __init__(
        self,
        spatial_backend: str = "pytorch",
        fps: float = 30.0,
        rppg_window_sec: float = 6.0,
        weight_spatial: float = 0.6,
        weight_rppg: float = 0.4,
    ) -> None:
        self.spatial = SlidingWindowDetector(
            backend=spatial_backend, window_size=16, stride=8
        )
        self.rppg = StreamingRppgDetector(fps=fps, window_seconds=rppg_window_sec)
        self.w_spatial = weight_spatial
        self.w_rppg = weight_rppg
        self._frame_idx: int = 0

    def process_frame(
        self,
        frame_bgr: np.ndarray,
        face_box: Optional[Tuple[int, int, int, int]] = None,
    ) -> Dict[str, Any]:
        """Process a single raw BGR surveillance frame.

        Args:
            frame_bgr: Raw video frame (H, W, 3) in BGR colour space.
            face_box: (x1, y1, x2, y2) tight bounding box around the face,
                      or None when no face was detected this frame.

        Returns:
            Dict with keys:
              frame_idx, face_detected, spatial_score, rppg_score,
              rppg_status, rppg_claim, fused_score, verdict.
        """
        self._frame_idx += 1
        h, w = frame_bgr.shape[:2]

        # ----------------------------------------------------------------
        # 1. Determine face presence
        # ----------------------------------------------------------------
        face_detected = (
            face_box is not None
            and face_box[2] > face_box[0]
            and face_box[3] > face_box[1]
        )

        # ----------------------------------------------------------------
        # 2. Extract face crop (or fall back to full frame for classifier)
        # ----------------------------------------------------------------
        if face_detected:
            x1, y1, x2, y2 = (
                max(0, face_box[0]), max(0, face_box[1]),
                min(w, face_box[2]),  min(h, face_box[3]),
            )
            crop = frame_bgr[y1:y2, x1:x2]
        else:
            crop = frame_bgr

        if crop.size == 0:
            crop = frame_bgr
            face_detected = False

        # ----------------------------------------------------------------
        # 3. Spatial frame classifier
        # ----------------------------------------------------------------
        normed = _preprocess_frame_for_classifier(crop)
        spatial_score_raw = self.spatial.push_frame(normed)
        spatial_score: float = spatial_score_raw if spatial_score_raw is not None else 0.5

        # ----------------------------------------------------------------
        # 4. Streaming rPPG (M2-L1 / M2-L2 / M2-L3 guardrails inside)
        # ----------------------------------------------------------------
        mean_rgb: Optional[np.ndarray] = None
        if face_detected and crop.size > 0:
            face_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            mean_rgb = face_rgb.reshape(-1, 3).mean(axis=0).astype(np.float32)

        rppg_result = self.rppg.process_frame(mean_rgb, face_detected=face_detected)
        rppg_score: Optional[float] = rppg_result.get("score")

        # ----------------------------------------------------------------
        # 5. Score fusion
        # ----------------------------------------------------------------
        if rppg_score is not None:
            fused = float(np.clip(
                self.w_spatial * spatial_score + self.w_rppg * rppg_score,
                0.0, 1.0,
            ))
        else:
            # rPPG is warming_up, not_applicable, or motionless_face
            fused = float(np.clip(spatial_score, 0.0, 1.0))

        verdict = "synthetic" if fused > 0.5 else "authentic"

        return {
            "frame_idx": self._frame_idx,
            "face_detected": face_detected,
            "spatial_score": round(spatial_score, 4),
            "rppg_score": round(rppg_score, 4) if rppg_score is not None else None,
            "rppg_status": rppg_result.get("status"),
            "rppg_claim": rppg_result.get("claim"),
            "fused_score": round(fused, 4),
            "verdict": verdict,
        }

    def reset(self) -> None:
        """Reset both detectors (use when switching camera feed)."""
        self.rppg.reset()
        self._frame_idx = 0