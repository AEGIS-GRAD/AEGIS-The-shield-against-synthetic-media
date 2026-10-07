from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Union, Tuple

import numpy as np
import torch

try:
    import onnxruntime as ort
    HAS_ORT = True
except ImportError:
    ort = None
    HAS_ORT = False

from engine.edge_model.build_edge_model import get_mobilenet_v3_small_model
from engine.edge_model.export_onnx import FP32_ONNX_PATH, INT8_ONNX_PATH

logger = logging.getLogger(__name__)


class SlidingWindowDetector:
    """Live surveillance rolling-window deepfake detector using MobileNetV3-Small edge model.

    Supports PyTorch FP32, ONNX FP32, and ONNX INT8 quantized backends.
    """

    def __init__(
        self,
        backend: str = "onnx_int8",
        window_size: int = 16,
        stride: int = 8,
        custom_model_path: Optional[Union[str, Path]] = None,
        device: str = "cpu",
    ):
        """Initializes rolling-window detector.

        Args:
            backend: One of 'pytorch', 'onnx_fp32', or 'onnx_int8'.
            window_size: Number of frames in rolling temporal window (e.g. 16).
            stride: Step size (frames) before emitting next window prediction (e.g. 8).
            custom_model_path: Optional path to override default model checkpoint/ONNX file.
            device: Target device ('cpu', 'cuda').
        """
        self.backend = backend.lower()
        self.window_size = window_size
        self.stride = stride
        self.device = device
        self.buffer: List[np.ndarray] = []

        if self.backend == "pytorch":
            self.model = get_mobilenet_v3_small_model(checkpoint_path=custom_model_path, device=device)
            self.model.eval()
            self.ort_session = None
        elif self.backend in ("onnx_fp32", "onnx_int8"):
            if not HAS_ORT:
                raise RuntimeError("onnxruntime is required for ONNX backends.")
            default_path = INT8_ONNX_PATH if self.backend == "onnx_int8" else FP32_ONNX_PATH
            onnx_path = Path(custom_model_path or default_path)
            if not onnx_path.exists():
                raise FileNotFoundError(f"ONNX model file not found at {onnx_path}. Run export_onnx module first.")
            
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device == "cuda" else ["CPUExecutionProvider"]
            self.ort_session = ort.InferenceSession(str(onnx_path), providers=providers)
            self.input_name = self.ort_session.get_inputs()[0].name
            self.output_name = self.ort_session.get_outputs()[0].name
            self.model = None
        else:
            raise ValueError(f"Unknown backend '{backend}'. Supported: 'pytorch', 'onnx_fp32', 'onnx_int8'.")

        logger.info(f"Initialized SlidingWindowDetector (backend={self.backend}, window_size={window_size}, stride={stride})")

    def _predict_batch_array(self, batch_np: np.ndarray) -> np.ndarray:
        """Executes inference on a batch of normalized frames (B, 3, 224, 224).

        Returns:
            NumPy array of shape (B,) containing fake probability scores [0.0, 1.0].
        """
        if self.backend == "pytorch":
            tensor_input = torch.from_numpy(batch_np).to(self.device)
            with torch.no_grad():
                logits = self.model(tensor_input)
                probs = torch.softmax(logits, dim=1)
                fake_probs = probs[:, 1].cpu().numpy()
            return fake_probs
        else:
            # ONNX Runtime inference
            outputs = self.ort_session.run([self.output_name], {self.input_name: batch_np})[0]
            # Manual softmax over logits output shape (B, 2)
            exp_logits = np.exp(outputs - np.max(outputs, axis=1, keepdims=True))
            probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
            return probs[:, 1]

    def predict_window(self, frames: List[Union[torch.Tensor, np.ndarray]]) -> float:
        """Emits aggregated fake probability score across a list of window frames.

        Args:
            frames: List of preprocessed frame tensors/arrays (shape 3, 224, 224).

        Returns:
            Window fake probability score [0.0, 1.0].
        """
        if not frames:
            return 0.5

        # Format frames as (B, 3, 224, 224) numpy array
        np_frames = []
        for f in frames:
            if isinstance(f, torch.Tensor):
                f = f.detach().cpu().numpy()
            if f.ndim == 3:
                np_frames.append(f)

        if not np_frames:
            return 0.5

        batch_np = np.stack(np_frames, axis=0).astype(np.float32)
        frame_scores = self._predict_batch_array(batch_np)
        return float(np.mean(frame_scores))

    def push_frame(self, frame: Union[torch.Tensor, np.ndarray]) -> Optional[float]:
        """Pushes single frame to buffer and returns rolling window verdict when window fills.

        Args:
            frame: Single preprocessed frame tensor/array (3, 224, 224).

        Returns:
            Float score [0.0, 1.0] if window is full and prediction triggered, else None.
        """
        if isinstance(frame, torch.Tensor):
            frame = frame.detach().cpu().numpy()

        self.buffer.append(frame)

        if len(self.buffer) >= self.window_size:
            window_frames = self.buffer[: self.window_size]
            score = self.predict_window(window_frames)

            # Advance buffer by stride
            self.buffer = self.buffer[self.stride :]
            return score

        return None
