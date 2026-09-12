import pytest
import numpy as np
import torch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from preprocess import VideoPreprocessor

EXPECTED_TENSOR_SHAPE = (3, 224, 224)  # PyTorch format: (Channels, Height, Width)

@pytest.fixture
def preprocessor():
    return VideoPreprocessor(target_size=(224, 224))


def test_extract_frames_returns_nonempty_list(preprocessor, clean_video):
    frames = preprocessor.extract_frames(clean_video)
    assert isinstance(frames, list)
    assert len(frames) > 0


def test_extracted_frame_is_numpy_array(preprocessor, clean_video):
    frames = preprocessor.extract_frames(clean_video)
    assert isinstance(frames[0], np.ndarray)


def test_normalized_frame_has_correct_shape(preprocessor, clean_video):
    frames = preprocessor.extract_frames(clean_video)
    face_crop = preprocessor.crop_face(frames[0])
    normalized = preprocessor.normalize_frame(face_crop)
    assert normalized.shape == EXPECTED_TENSOR_SHAPE


def test_normalized_frame_value_range(preprocessor, clean_video):
    frames = preprocessor.extract_frames(clean_video)
    face_crop = preprocessor.crop_face(frames[0])
    normalized = preprocessor.normalize_frame(face_crop)

    # Check bounds for ImageNet normalized tensors
    if isinstance(normalized, torch.Tensor):
        normalized = normalized.numpy()
    assert normalized.min() >= -3.0
    assert normalized.max() <= 3.0


def test_compressed_video_still_extracts_frames(preprocessor, compressed_video):
    frames = preprocessor.extract_frames(compressed_video)
    assert len(frames) > 0


def test_no_face_video_handled_gracefully(preprocessor, no_face_video):
    # Preprocessor uses center-crop fallback if no face is detected
    tensors = preprocessor.preprocess_video(no_face_video)
    assert isinstance(tensors, list)
    assert len(tensors) > 0
    assert tensors[0].shape == EXPECTED_TENSOR_SHAPE


def test_end_to_end_preprocess_video(preprocessor, clean_video):
    tensors = preprocessor.preprocess_video(clean_video)
    assert isinstance(tensors, list)
    assert len(tensors) > 0
    assert tensors[0].shape == EXPECTED_TENSOR_SHAPE