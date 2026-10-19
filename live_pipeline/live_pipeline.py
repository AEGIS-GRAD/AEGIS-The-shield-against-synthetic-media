"""
Live Surveillance Pipeline for AEGIS
====================================
End-to-end streaming integration of:
1. Video Frame Ingestion (OpenCV / numpy arrays)
2. Streaming StreamValidator (Sequence number & Timestamp drift / regression checks)
3. Rolling-Window Deepfake Detection (MobileNetV3 Edge Model: ONNX INT8, ONNX FP32, or PyTorch)
4. Feed-Integrity Fusion (FeedFusionEngine)
5. Structured Alert Emission with Evidence Justifications
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import cv2
import numpy as np
import torch

from engine.edge_model.sliding_window import SlidingWindowDetector
from security.fusion.feed_fusion import FeedFusionEngine, FusionResult
from security.stream_integrity.stream_validator import Anomaly, StreamValidator

logger = logging.getLogger(__name__)

# Normalization parameters matching standard MobileNetV3 edge model input
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
INPUT_SIZE = 224


def preprocess_frame(bgr_or_rgb: np.ndarray, is_bgr: bool = True) -> np.ndarray:
    """Preprocess frame to (3, 224, 224) float32 normalized tensor array."""
    if is_bgr:
        rgb = cv2.cvtColor(bgr_or_rgb, cv2.COLOR_BGR2RGB)
    else:
        rgb = bgr_or_rgb
    rgb_resized = cv2.resize(rgb, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_AREA)
    normed = (rgb_resized.astype(np.float32) / 255.0 - MEAN) / STD
    return np.transpose(normed, (2, 0, 1)).astype(np.float32)


@dataclass
class FusedAlert:
    """Represents a rolling-window alert produced end-to-end by the live pipeline."""

    camera_id: str
    window_idx: int
    frame_count: int
    start_seq: int
    end_seq: int
    verdict: str  # 'AUTHENTIC', 'SYNTHETIC', 'INTEGRITY_UNKNOWN', 'UNCERTAIN'
    combined_score: float
    integrity_score: float
    ai_score: float
    integrity_ok: bool
    evidence: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def is_threat(self) -> bool:
        """Returns True if this alert represents an active security incident."""
        return self.verdict in ("SYNTHETIC", "INTEGRITY_UNKNOWN")

    def justification_narrative(self) -> str:
        """Returns human-readable forensic reasoning for audit logs & UI alerts."""
        reasons = []
        if not self.integrity_ok:
            reasons.append("Stream integrity compromised")
            if not self.evidence.get("hash_chain_ok", True):
                reasons.append("Cryptographic hash mismatch")
            if not self.evidence.get("prnu_ok", True):
                pce = self.evidence.get("prnu_pce", 0.0)
                reasons.append(f"Hardware PRNU mismatch (PCE={pce:.1f})")
            anomalies = self.evidence.get("anomalies", [])
            if anomalies:
                reasons.append(f"{len(anomalies)} stream sequence/timestamp anomalies")
        elif self.verdict == "SYNTHETIC":
            reasons.append(f"AI content anomaly score high ({self.ai_score:.2f})")
        elif self.verdict == "AUTHENTIC":
            reasons.append("Feed integrity verified and AI anomaly score low")
        else:
            reasons.append("Borderline signal correlation")

        return "; ".join(reasons)


class LiveSurveillancePipeline:
    """
    End-to-End Live Surveillance Pipeline.
    
    Wires together:
    - Frame buffering & pre-processing
    - StreamValidator for transport / sequence integrity
    - SlidingWindowDetector (MobileNetV3 INT8/FP32/PyTorch)
    - FeedFusionEngine for combined AI-plus-integrity decision making
    """

    def __init__(
        self,
        camera_id: str = "camera-001",
        backend: str = "onnx_int8",
        window_size: int = 16,
        stride: int = 8,
        fps: float = 30.0,
        custom_model_path: Optional[Union[str, Path]] = None,
        device: str = "cpu",
        w_integrity: float = 0.5,
        w_ai: float = 0.5,
        synthetic_threshold: float = 0.65,
        authentic_threshold: float = 0.35,
    ):
        self.camera_id = camera_id
        self.window_size = window_size
        self.stride = stride
        self.fps = fps

        # Sub-components
        self.detector = SlidingWindowDetector(
            backend=backend,
            window_size=window_size,
            stride=stride,
            custom_model_path=custom_model_path,
            device=device,
        )
        self.stream_validator = StreamValidator(fps=fps)
        self.fusion_engine = FeedFusionEngine(
            w_integrity=w_integrity,
            w_ai=w_ai,
            synthetic_threshold=synthetic_threshold,
            authentic_threshold=authentic_threshold,
        )

        # Pipeline runtime state
        self.frame_count = 0
        self.window_count = 0
        self.frame_buffer: List[np.ndarray] = []
        self.meta_buffer: List[Dict[str, Any]] = []
        self.window_anomalies: List[Anomaly] = []
        self.all_anomalies: List[Anomaly] = []
        self.last_alert: Optional[FusedAlert] = None

    def reset(self):
        """Resets stream state and rolling buffers."""
        self.frame_count = 0
        self.window_count = 0
        self.frame_buffer.clear()
        self.meta_buffer.clear()
        self.window_anomalies.clear()
        self.all_anomalies.clear()
        self.stream_validator = StreamValidator(fps=self.fps)
        self.last_alert = None

    def push_frame(
        self,
        frame: np.ndarray,
        sequence_number: Optional[int] = None,
        timestamp_ms: Optional[int] = None,
        hash_chain_ok: bool = True,
        prnu_ok: bool = True,
        prnu_pce: float = 100.0,
        is_preprocessed: bool = False,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[FusedAlert]:
        """
        Pushes a single frame into the live pipeline.

        Args:
            frame: Video frame (BGR numpy array if not preprocessed, or (3, 224, 224) if preprocessed).
            sequence_number: Frame sequence number (optional, defaults to monotonic count).
            timestamp_ms: Frame timestamp in milliseconds (optional, estimated from fps).
            hash_chain_ok: True if cryptographic hash chain for this frame is valid.
            prnu_ok: True if physical sensor PRNU fingerprint matches enrolled baseline.
            prnu_pce: Peak-to-Correlation Energy from PRNU extractor.
            is_preprocessed: Whether frame is already (3, 224, 224) normalized.
            extra_metadata: Any optional caller telemetry.

        Returns:
            FusedAlert when a rolling window boundary triggers (every stride frames),
            or None while filling buffer.
        """
        self.frame_count += 1
        seq = sequence_number if sequence_number is not None else self.frame_count
        ts = timestamp_ms if timestamp_ms is not None else int((self.frame_count / self.fps) * 1000)

        # 1. Transport & Sequence Integrity Check
        anomalies = self.stream_validator.check(seq, ts)
        if anomalies:
            self.window_anomalies.extend(anomalies)
            self.all_anomalies.extend(anomalies)

        # 2. Preprocess & Buffer Frame
        proc_frame = frame if is_preprocessed else preprocess_frame(frame)
        self.frame_buffer.append(proc_frame)
        self.meta_buffer.append({
            "seq": seq,
            "ts": ts,
            "hash_chain_ok": hash_chain_ok,
            "prnu_ok": prnu_ok,
            "prnu_pce": prnu_pce,
            "extra": extra_metadata or {},
        })

        # 3. Check if Window is Ready
        if len(self.frame_buffer) < self.window_size:
            return None

        # 4. Process Window End-to-End
        t_start = time.perf_counter()
        window_frames = self.frame_buffer[: self.window_size]
        window_meta = self.meta_buffer[: self.window_size]

        # AI Detection across the 16-frame window
        ai_score = self.detector.predict_window(window_frames)

        # Window Integrity Signals aggregation
        win_hash_ok = all(m["hash_chain_ok"] for m in window_meta)
        win_prnu_ok = all(m["prnu_ok"] for m in window_meta)
        win_prnu_pce = min(m["prnu_pce"] for m in window_meta)

        # Combine with accumulated integrity anomalies
        fusion_res: FusionResult = self.fusion_engine.fuse(
            hash_chain_ok=win_hash_ok,
            integrity_anomalies=self.window_anomalies,
            prnu_ok=win_prnu_ok,
            prnu_pce=win_prnu_pce,
            ai_score=ai_score,
            details={
                "camera_id": self.camera_id,
                "window_idx": self.window_count,
                "window_size": self.window_size,
                "start_seq": window_meta[0]["seq"],
                "end_seq": window_meta[-1]["seq"],
            },
        )
        latency_ms = (time.perf_counter() - t_start) * 1000.0

        alert = FusedAlert(
            camera_id=self.camera_id,
            window_idx=self.window_count,
            frame_count=self.frame_count,
            start_seq=window_meta[0]["seq"],
            end_seq=window_meta[-1]["seq"],
            verdict=fusion_res.verdict,
            combined_score=fusion_res.combined_score,
            integrity_score=fusion_res.integrity_score,
            ai_score=fusion_res.ai_score,
            integrity_ok=fusion_res.integrity_ok,
            evidence=fusion_res.evidence,
            latency_ms=latency_ms,
        )

        self.last_alert = alert
        self.window_count += 1

        # Advance buffers by stride
        self.frame_buffer = self.frame_buffer[self.stride :]
        self.meta_buffer = self.meta_buffer[self.stride :]
        # Clear window anomalies for next stride interval
        self.window_anomalies = []

        return alert
