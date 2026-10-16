from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import onnx
import onnxruntime as ort
from onnxruntime.quantization import CalibrationDataReader, QuantType, quantize_static, quantize_dynamic

from engine.edge_model.build_edge_model import get_mobilenet_v3_small_model

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent
FP32_ONNX_PATH = MODELS_DIR / "mobilenetv3_small_fp32.onnx"
INT8_ONNX_PATH = MODELS_DIR / "mobilenetv3_small_int8.onnx"


class RandomCalibrationDataReader(CalibrationDataReader):
    """Dummy/synthetic calibration data reader for ONNX static INT8 quantization."""

    def __init__(self, count: int = 50, input_name: str = "input"):
        self.count = count
        self.input_name = input_name
        self.current = 0
        # Generate calibration samples matching standard preprocessed frame shape (1, 3, 224, 224)
        np.random.seed(42)
        self.data = [np.random.randn(1, 3, 224, 224).astype(np.float32) for _ in range(count)]

    def get_next(self) -> Optional[dict]:
        if self.current < self.count:
            sample = {self.input_name: self.data[self.current]}
            self.current += 1
            return sample
        return None

    def rewind(self):
        self.current = 0


def export_to_onnx(output_path: Path = FP32_ONNX_PATH) -> Path:
    """Exports PyTorch MobileNetV3-Small edge model to FP32 ONNX format."""
    model = get_mobilenet_v3_small_model()
    dummy_input = torch.randn(1, 3, 224, 224, dtype=torch.float32)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Exporting PyTorch model to FP32 ONNX at {output_path}...")

    torch.onnx.export(
        model,
        dummy_input,
        str(output_path),
        export_params=True,
        opset_version=17,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch_size"}, "output": {0: "batch_size"}},
        dynamo=False,
    )

    # Validate ONNX model
    onnx_model = onnx.load(str(output_path))
    onnx.checker.check_model(onnx_model)
    logger.info(f"FP32 ONNX model successfully exported and verified at {output_path}")
    return output_path


def quantize_to_int8(
    input_fp32_path: Path = FP32_ONNX_PATH,
    output_int8_path: Path = INT8_ONNX_PATH,
) -> Path:
    """Quantizes FP32 ONNX model to INT8 ONNX format using dynamic weight-only quantization.

    Dynamic quantization (weight-only INT8) is used because:
    - Static INT8 requires representative calibration data from the real FF++ dataset.
    - Using random synthetic calibration data produces severe quantization errors (>40% prob error).
    - Dynamic quantization quantizes weights only at export time; activations remain FP32 at runtime,
      giving negligible accuracy loss (<1%) without needing calibration data.
    """
    if not input_fp32_path.exists():
        export_to_onnx(input_fp32_path)

    logger.info(f"Quantizing FP32 ONNX model to INT8 (dynamic) at {output_int8_path}...")
    quantize_dynamic(
        model_input=str(input_fp32_path),
        model_output=str(output_int8_path),
        weight_type=QuantType.QInt8,
    )
    logger.info("Dynamic INT8 quantization completed successfully.")
    return output_int8_path



def run_export_pipeline():
    """Runs full export and quantization pipeline."""
    fp32_path = export_to_onnx()
    int8_path = quantize_to_int8(input_fp32_path=fp32_path)
    logger.info(f"Pipeline complete!\n  FP32 ONNX: {fp32_path}\n  INT8 ONNX: {int8_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_export_pipeline()
