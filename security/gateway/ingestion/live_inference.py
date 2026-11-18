"""
AEGIS Ingestion Gateway — Live Inference Stage (Week 10 Task 6, closes M2-L15)
=============================================================================

Until now the ingestion gateway fused feed-integrity signals with a hard-coded
``ai_score=0.10`` placeholder, so every live-path load test measured transport
only. This module puts the real AI models into the per-frame loop:

    decoded frame
      -> face localisation      (OpenCV Haar cascade, re-detected every N frames)
      -> MobileNetV3-Small edge (INT8 ONNX, sliding window 16 / stride 8)
      -> streaming rPPG         (CHROM rolling buffer, engine/edge_model)
      -> combined AI score      (0.6 spatial + 0.4 rPPG, same as engine/live_pipeline.py)

The combined AI score is what the gateway now passes to ``FeedFusionEngine``.

Design notes
------------
* One ``onnxruntime.InferenceSession`` is shared by every connection
  (``InferenceSession.run`` is thread-safe). Each connection gets its own
  ``LiveInferenceStage`` that holds only per-feed state (window buffer, face
  tracker, rPPG buffer), so state is released when the connection closes.
* The ONNX window runner mirrors ``engine/edge_model/sliding_window.py``
  (softmax over the two logits, mean of the per-frame fake probabilities)
  without importing torch, which keeps the gateway image lean.
* ``process()`` is synchronous and CPU-bound. The gateway calls it through
  ``asyncio.to_thread`` so feeds are processed in parallel across cores
  (ONNX Runtime and OpenCV both release the GIL).

Enable in the gateway with ``AEGIS_LIVE_INFERENCE=1``. Optional knobs:

    AEGIS_EDGE_MODEL_PATH        ONNX file (default: INT8 MobileNetV3-Small)
    AEGIS_EDGE_ORT_THREADS       intra-op threads per inference call (default 1)
    AEGIS_FACE_REDETECT_EVERY    run the face detector every N frames (default 5)
    AEGIS_LIVE_FPS               nominal camera FPS for the rPPG window (default 25)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("aegis.ingestion.live_inference")

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EDGE_MODEL = _REPO_ROOT / "engine" / "edge_model" / "mobilenetv3_small_int8.onnx"

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# Fusion weights shared with engine/live_pipeline.py (LiveSurveillancePipeline).
WEIGHT_SPATIAL = 0.6
WEIGHT_RPPG = 0.4


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# Shared edge model (one ONNX session per process)
# ─────────────────────────────────────────────────────────────────────────────
class SharedEdgeModel:
    """Process-wide MobileNetV3-Small ONNX session shared by all feeds."""

    _instance: Optional["SharedEdgeModel"] = None
    _instance_lock = threading.Lock()

    def __init__(self, model_path: Optional[Path] = None, intra_op_threads: Optional[int] = None):
        import onnxruntime as ort

        self.model_path = Path(model_path or os.environ.get("AEGIS_EDGE_MODEL_PATH") or DEFAULT_EDGE_MODEL)
        if not self.model_path.exists():
            raise FileNotFoundError(f"Edge model not found at {self.model_path}")

        threads = intra_op_threads if intra_op_threads is not None else _env_int("AEGIS_EDGE_ORT_THREADS", 1)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, threads)
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(self.model_path), sess_options=opts, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.model_version = f"mobilenetv3-small-ffpp-{self.model_path.stem.rsplit('_', 1)[-1]}"
        logger.info("Edge model loaded: %s (intra_op_threads=%d)", self.model_path.name, opts.intra_op_num_threads)

    @classmethod
    def get(cls) -> "SharedEdgeModel":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_shared(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    def predict_fake_probs(self, batch: np.ndarray) -> np.ndarray:
        """batch: (B, 3, 224, 224) float32 -> (B,) P(fake)."""
        logits = self.session.run([self.output_name], {self.input_name: batch})[0]
        exp = np.exp(logits - np.max(logits, axis=1, keepdims=True))
        probs = exp / np.sum(exp, axis=1, keepdims=True)
        return probs[:, 1]


def preprocess_for_classifier(bgr_crop: np.ndarray) -> np.ndarray:
    """Resize + ImageNet-normalise a BGR crop -> (3, 224, 224) float32.

    Identical to ``engine/live_pipeline.py::_preprocess_frame_for_classifier``.
    """
    import cv2

    rgb = cv2.cvtColor(cv2.resize(bgr_crop, (224, 224)), cv2.COLOR_BGR2RGB)
    chw = rgb.astype(np.float32) / 255.0
    chw = (chw - _IMAGENET_MEAN) / _IMAGENET_STD
    return chw.transpose(2, 0, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Per-feed components
# ─────────────────────────────────────────────────────────────────────────────
class FaceTracker:
    """Haar-cascade face localiser that re-detects every ``redetect_every`` frames.

    Between detections the last box is reused (surveillance subjects move slowly
    relative to 25 FPS). A box that has not been confirmed for
    ``max_stale_detections`` consecutive detector runs is dropped, so rPPG
    correctly reports ``not_applicable`` when the subject leaves the frame.
    """

    def __init__(self, redetect_every: int = 5, max_stale_detections: int = 2, detect_width: int = 320):
        import cv2

        self._cv2 = cv2
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        self._cascade = cv2.CascadeClassifier(cascade_path)
        if self._cascade.empty():
            raise RuntimeError(f"Failed to load Haar cascade from {cascade_path}")
        self.redetect_every = max(1, redetect_every)
        self.max_stale = max(1, max_stale_detections)
        self.detect_width = detect_width
        self._frame_idx = 0
        self._box: Optional[Tuple[int, int, int, int]] = None
        self._misses = 0

    def update(self, frame_bgr: np.ndarray) -> Tuple[Optional[Tuple[int, int, int, int]], bool]:
        """Returns (face_box_xyxy or None, detector_ran)."""
        self._frame_idx += 1
        ran = False
        # Throttled even when no face is present, so an empty scene cannot force
        # a full detector pass on every frame (that would be a cheap CPU DoS).
        if (self._frame_idx - 1) % self.redetect_every == 0:
            ran = True
            h, w = frame_bgr.shape[:2]
            scale = self.detect_width / float(w) if w > self.detect_width else 1.0
            small = self._cv2.resize(frame_bgr, (int(w * scale), int(h * scale))) if scale < 1.0 else frame_bgr
            gray = self._cv2.cvtColor(small, self._cv2.COLOR_BGR2GRAY)
            faces = self._cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24))
            if len(faces) > 0:
                x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
                inv = 1.0 / scale
                self._box = (int(x * inv), int(y * inv), int((x + fw) * inv), int((y + fh) * inv))
                self._misses = 0
            else:
                self._misses += 1
                if self._misses >= self.max_stale:
                    self._box = None
        return self._box, ran


@dataclass
class InferenceResult:
    """Per-frame output of the live inference stage."""

    ai_score: float
    spatial_score: Optional[float]
    rppg_score: Optional[float]
    rppg_status: str
    face_detected: bool
    window_ran: bool
    face_detector_ran: bool
    warming_up: bool
    model_version: str
    decode_ms: float = 0.0
    face_ms: float = 0.0
    preprocess_ms: float = 0.0
    model_ms: float = 0.0
    rppg_ms: float = 0.0
    total_ms: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LiveInferenceStage:
    """Per-connection live inference pipeline (spatial CNN + streaming rPPG)."""

    def __init__(
        self,
        model: Optional[SharedEdgeModel] = None,
        window_size: int = 16,
        stride: int = 8,
        fps: Optional[float] = None,
        rppg_window_sec: float = 6.0,
        face_redetect_every: Optional[int] = None,
    ):
        # Imported lazily so the gateway does not pay for it when inference is off.
        try:
            from engine.edge_model.streaming_rppg import StreamingRppgDetector
        except ImportError:  # pragma: no cover - path plumbing for direct execution
            import sys

            sys.path.insert(0, str(_REPO_ROOT))
            from engine.edge_model.streaming_rppg import StreamingRppgDetector

        self.model = model or SharedEdgeModel.get()
        self.window_size = window_size
        self.stride = stride
        self._buffer: List[np.ndarray] = []
        self._last_spatial: Optional[float] = None
        self.fps = fps if fps is not None else _env_float("AEGIS_LIVE_FPS", 25.0)
        self.rppg = StreamingRppgDetector(fps=self.fps, window_seconds=rppg_window_sec)
        self.faces = FaceTracker(
            redetect_every=face_redetect_every if face_redetect_every is not None else _env_int("AEGIS_FACE_REDETECT_EVERY", 5)
        )
        self.frames_processed = 0
        self.windows_inferred = 0

    @staticmethod
    def decode(frame_bytes: bytes, width: Optional[int] = None, height: Optional[int] = None) -> Optional[np.ndarray]:
        """Decode an encoded (PNG/JPEG) or raw BGR frame to an (H, W, 3) array."""
        import cv2

        if width and height and len(frame_bytes) == int(width) * int(height) * 3:
            return np.frombuffer(frame_bytes, dtype=np.uint8).reshape((int(height), int(width), 3))
        arr = np.frombuffer(frame_bytes, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def process(self, frame_bytes: bytes, width: Optional[int] = None, height: Optional[int] = None) -> InferenceResult:
        t0 = time.perf_counter()
        frame = self.decode(frame_bytes, width, height)
        t_dec = time.perf_counter()
        if frame is None or frame.size == 0:
            return InferenceResult(
                ai_score=self._last_spatial if self._last_spatial is not None else 0.5,
                spatial_score=self._last_spatial, rppg_score=None, rppg_status="decode_error",
                face_detected=False, window_ran=False, face_detector_ran=False, warming_up=self._last_spatial is None,
                model_version=self.model.model_version, decode_ms=(t_dec - t0) * 1000.0,
                total_ms=(t_dec - t0) * 1000.0, error="frame_decode_failed",
            )

        box, detector_ran = self.faces.update(frame)
        t_face = time.perf_counter()

        h, w = frame.shape[:2]
        face_detected = box is not None
        crop = frame
        if face_detected:
            x1, y1, x2, y2 = max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3])
            if x2 > x1 and y2 > y1:
                crop = frame[y1:y2, x1:x2]
            else:
                face_detected = False

        normed = preprocess_for_classifier(crop)
        t_pre = time.perf_counter()

        # Sliding-window spatial inference (window 16, stride 8).
        self._buffer.append(normed)
        window_ran = False
        model_ms = 0.0
        if len(self._buffer) >= self.window_size:
            batch = np.stack(self._buffer[: self.window_size], axis=0).astype(np.float32, copy=False)
            tm0 = time.perf_counter()
            probs = self.model.predict_fake_probs(batch)
            model_ms = (time.perf_counter() - tm0) * 1000.0
            self._last_spatial = float(np.mean(probs))
            self._buffer = self._buffer[self.stride:]
            window_ran = True
            self.windows_inferred += 1
        t_model = time.perf_counter()

        mean_rgb = None
        if face_detected:
            import cv2

            mean_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).reshape(-1, 3).mean(axis=0).astype(np.float32)
        rppg = self.rppg.process_frame(mean_rgb, face_detected=face_detected)
        rppg_score = rppg.get("score")
        t_rppg = time.perf_counter()

        spatial = self._last_spatial
        spatial_for_fusion = spatial if spatial is not None else 0.5
        if rppg_score is not None and rppg.get("status") == "ok":
            ai_score = float(np.clip(WEIGHT_SPATIAL * spatial_for_fusion + WEIGHT_RPPG * float(rppg_score), 0.0, 1.0))
        else:
            ai_score = float(np.clip(spatial_for_fusion, 0.0, 1.0))

        self.frames_processed += 1
        return InferenceResult(
            ai_score=round(ai_score, 4),
            spatial_score=round(spatial, 4) if spatial is not None else None,
            rppg_score=round(float(rppg_score), 4) if rppg_score is not None else None,
            rppg_status=str(rppg.get("status")),
            face_detected=face_detected,
            window_ran=window_ran,
            face_detector_ran=detector_ran,
            warming_up=spatial is None,
            model_version=self.model.model_version,
            decode_ms=round((t_dec - t0) * 1000.0, 3),
            face_ms=round((t_face - t_dec) * 1000.0, 3),
            preprocess_ms=round((t_pre - t_face) * 1000.0, 3),
            model_ms=round(model_ms, 3),
            rppg_ms=round((t_rppg - t_model) * 1000.0, 3),
            total_ms=round((t_rppg - t0) * 1000.0, 3),
        )

    def close(self) -> None:
        self._buffer.clear()
        self.rppg.reset()


# ─────────────────────────────────────────────────────────────────────────────
# Per-frame metrics sink (used by the live-inference load test)
# ─────────────────────────────────────────────────────────────────────────────
class LiveMetricsSink:
    """Thread-safe JSONL writer for per-frame live-path metrics.

    Enabled with ``AEGIS_LIVE_METRICS_PATH``. ``AEGIS_LIVE_METRICS_SAMPLE=N``
    writes every Nth frame per stream (use N>1 for long soak runs).
    """

    def __init__(self, path: Optional[str], sample_every: int = 1):
        self.path = path
        self.sample_every = max(1, sample_every)
        self._lock = threading.Lock()
        self._fh = open(path, "a", encoding="utf-8", buffering=1 << 16) if path else None
        self._counters: Dict[str, int] = {}

    @classmethod
    def from_env(cls) -> "LiveMetricsSink":
        return cls(os.environ.get("AEGIS_LIVE_METRICS_PATH") or None, _env_int("AEGIS_LIVE_METRICS_SAMPLE", 1))

    @property
    def enabled(self) -> bool:
        return self._fh is not None

    def record(self, stream_id: str, row: Dict[str, Any]) -> None:
        if self._fh is None:
            return
        import json

        with self._lock:
            n = self._counters.get(stream_id, 0) + 1
            self._counters[stream_id] = n
            if (n - 1) % self.sample_every != 0:
                return
            self._fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    def forget(self, stream_id: str) -> None:
        with self._lock:
            self._counters.pop(stream_id, None)
            if self._fh is not None:
                self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
