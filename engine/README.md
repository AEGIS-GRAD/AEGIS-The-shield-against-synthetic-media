# AEGIS Engine — Hardware-Aware Edge Model & Quantization

The `engine` package provides the live surveillance edge detection capability and ONNX / INT8 optimization pipeline for AEGIS.

## Modules

- `edge_model/build_edge_model.py` — MobileNetV3-Small deepfake classifier initialization and weight management.
- `edge_model/export_onnx.py` — PyTorch to ONNX export + static INT8 quantization.
- `edge_model/sliding_window.py` — Real-time rolling-window detector for live surveillance frame streams.
- `benchmark/run_benchmark.py` — Latency & accuracy benchmark comparing PyTorch FP32 vs ONNX FP32 vs ONNX INT8.

## Usage

```bash
# Export and Quantize Edge Model
python -m engine.edge_model.export_onnx

# Run Latency & Accuracy Benchmark
python -m engine.benchmark.run_benchmark
```
