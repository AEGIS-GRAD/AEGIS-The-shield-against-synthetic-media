from pathlib import Path
import numpy as np
import pytest
import torch
import onnxruntime as ort

from engine.edge_model.build_edge_model import get_mobilenet_v3_small_model
from engine.edge_model.export_onnx import FP32_ONNX_PATH, INT8_ONNX_PATH, export_to_onnx, quantize_to_int8


def test_export_and_quantization_files_exist():
    fp32_path = export_to_onnx()
    assert fp32_path.exists()
    assert fp32_path.stat().st_size > 0

    int8_path = quantize_to_int8(input_fp32_path=fp32_path)
    assert int8_path.exists()
    assert int8_path.stat().st_size > 0


def test_onnx_fp32_numerical_consistency():
    model = get_mobilenet_v3_small_model()
    model.eval()

    dummy_tensor = torch.randn(1, 3, 224, 224, dtype=torch.float32)
    with torch.no_grad():
        pt_logits = model(dummy_tensor).numpy()

    sess = ort.InferenceSession(str(FP32_ONNX_PATH), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    ort_logits = sess.run(None, {input_name: dummy_tensor.numpy()})[0]

    np.testing.assert_allclose(pt_logits, ort_logits, rtol=1e-3, atol=1e-4)
