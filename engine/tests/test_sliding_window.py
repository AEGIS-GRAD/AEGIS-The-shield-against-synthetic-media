import numpy as np
import pytest
import torch

from engine.edge_model.sliding_window import SlidingWindowDetector


def test_sliding_window_buffer_fill_and_stride():
    detector = SlidingWindowDetector(backend="pytorch", window_size=4, stride=2)
    dummy_frame = np.zeros((3, 224, 224), dtype=np.float32)

    # First 3 frames: window not full yet
    assert detector.push_frame(dummy_frame) is None
    assert detector.push_frame(dummy_frame) is None
    assert detector.push_frame(dummy_frame) is None

    # 4th frame: window full -> returns score
    score1 = detector.push_frame(dummy_frame)
    assert score1 is not None
    assert 0.0 <= score1 <= 1.0

    # Stride is 2, so buffer has 2 frames remaining. Adding 1 frame -> 3 frames (None)
    assert detector.push_frame(dummy_frame) is None

    # Adding 2nd frame -> window full again -> returns score
    score2 = detector.push_frame(dummy_frame)
    assert score2 is not None
    assert 0.0 <= score2 <= 1.0


def test_sliding_window_onnx_int8():
    detector = SlidingWindowDetector(backend="onnx_int8", window_size=4, stride=2)
    frames = [torch.randn(3, 224, 224) for _ in range(4)]
    score = detector.predict_window(frames)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0
