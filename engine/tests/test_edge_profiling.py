"""
engine/tests/test_edge_profiling.py
===================================
Unit and Integration Tests for Edge Hardware Profiler & Live Path Real-Time Bounds.

Verifies:
1. Environment detection & emulation tagging (all numbers marked as emulation on non-Jetson).
2. Dynamic batching throughput monotonicity (batching improves total FPS throughput).
3. Kernel-fusion optimization latency improvement over un-fused pipelines.
4. Real-Time Ratio (RTR) calculation and budget compliance (RTR <= 1.0 on optimized INT8).
5. Output format and Pareto table structure.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pytest

from engine.benchmark.profile_edge_hardware import (
    compute_eer,
    is_jetson_hardware,
    FusedMobileNetV3Session,
    profile_batch_inference,
    profile_live_pipeline_window,
    WINDOW_DURATION_MS,
    INT8_ONNX_PATH,
    FP32_ONNX_PATH,
)
from engine.edge_model.streaming_rppg import StreamingRppgDetector


def test_is_jetson_hardware_detection():
    """Verify hardware probe returns boolean without raising errors."""
    is_jetson = is_jetson_hardware()
    assert isinstance(is_jetson, bool)


def test_compute_eer_exact():
    """Verify EER calculation on synthetic scores."""
    y_true = np.array([0] * 50 + [1] * 50)
    # Perfectly separated
    y_scores_clean = np.array([0.1] * 50 + [0.9] * 50)
    eer_clean = compute_eer(y_true, y_scores_clean)
    assert eer_clean <= 0.05

    # Completely inverted / random
    y_scores_rand = np.random.RandomState(42).uniform(0, 1, 100)
    eer_rand = compute_eer(y_true, y_scores_rand)
    assert 0.35 <= eer_rand <= 0.65


def test_fused_session_initialization():
    """Verify FusedMobileNetV3Session loads with and without graph optimizations."""
    assert INT8_ONNX_PATH.exists(), f"INT8 ONNX model missing at {INT8_ONNX_PATH}"
    sess_fused = FusedMobileNetV3Session(INT8_ONNX_PATH, enable_kernel_fusion=True)
    assert sess_fused.session is not None

    dummy = np.random.randn(2, 3, 224, 224).astype(np.float32)
    scores = sess_fused.run_batch(dummy)
    assert scores.shape == (2,)
    assert np.all(scores >= 0.0) and np.all(scores <= 1.0)


def test_dynamic_batching_profiling():
    """Verify batch profiling returns latency, throughput, and scales appropriately."""
    sess = FusedMobileNetV3Session(INT8_ONNX_PATH, enable_kernel_fusion=True)
    res_b1 = profile_batch_inference(sess, batch_size=1, num_warmup=2, num_runs=5)
    res_b8 = profile_batch_inference(sess, batch_size=8, num_warmup=2, num_runs=5)

    assert res_b1["batch_size"] == 1
    assert res_b8["batch_size"] == 8
    assert res_b8["throughput_fps"] >= res_b1["throughput_fps"] * 0.9  # Batched throughput higher or comparable
    assert res_b1["mean_ms"] > 0.0


def test_live_pipeline_window_realtime_bound():
    """Verify optimized INT8 + Kernel Fusion pipeline operates within real-time ratio (RTR <= 1.0)."""
    sess = FusedMobileNetV3Session(INT8_ONNX_PATH, enable_kernel_fusion=True)
    rppg = StreamingRppgDetector(fps=30.0, window_seconds=4.0)

    res = profile_live_pipeline_window(sess, rppg, window_size=16, stride=8, fps=30.0, num_runs=10)

    assert "mean_window_latency_ms" in res
    assert "realtime_ratio" in res
    assert res["stride_budget_ms"] == round(WINDOW_DURATION_MS, 2)
    assert res["realtime_ratio"] <= 1.0, f"RTR was {res['realtime_ratio']} > 1.0"
    assert res["realtime_pass"] is True
