"""
Tests for Grad-CAM heatmap generation (Task 4).

Run:  python -m pytest detectors/video-classifier/tests/test_gradcam.py -v
      (from repo root; needs torch + cv2 + numpy)
"""
import sys
import os
import numpy as np
import pytest
import torch
import torch.nn as nn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from infer import gradcam_heatmap, gradcam_to_base64, load_model


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def dummy_model():
    """Tiny 2-class EfficientNet-like model (uses ImageNet init for speed)."""
    import torchvision.models as models
    model = models.efficientnet_b0(weights=None)
    in_f = model.classifier[1].in_features
    model.classifier[1] = nn.Linear(in_f, 2)
    
    model.eval()
    return model


@pytest.fixture
def random_frame_tensor():
    """Random (3, 224, 224) tensor in ImageNet-normalised range."""
    return torch.randn(3, 224, 224)


# ── Unit tests ───────────────────────────────────────────────────────────────

class TestGradcamHeatmap:
    def test_output_shape_is_224x224(self, dummy_model, random_frame_tensor):
        hmap = gradcam_heatmap(dummy_model, random_frame_tensor)
        assert hmap.shape == (224, 224), f"Expected (224,224), got {hmap.shape}"

    def test_output_dtype_is_uint8(self, dummy_model, random_frame_tensor):
        hmap = gradcam_heatmap(dummy_model, random_frame_tensor)
        assert hmap.dtype == np.uint8

    def test_output_values_in_0_255(self, dummy_model, random_frame_tensor):
        hmap = gradcam_heatmap(dummy_model, random_frame_tensor)
        assert hmap.min() >= 0 and hmap.max() <= 255

    def test_batched_input_also_works(self, dummy_model, random_frame_tensor):
        """Shape (1, 3, 224, 224) must be handled the same as (3, 224, 224)."""
        batched = random_frame_tensor.unsqueeze(0)
        hmap = gradcam_heatmap(dummy_model, batched)
        assert hmap.shape == (224, 224)

    def test_all_zero_frame_gives_blank_heatmap(self, dummy_model):
        """A fully-zero tensor may produce zero activations — must not crash."""
        zero_tensor = torch.zeros(3, 224, 224)
        hmap = gradcam_heatmap(dummy_model, zero_tensor)
        assert hmap.shape == (224, 224)
        assert hmap.dtype == np.uint8

    def test_heatmap_is_not_entirely_zero_for_nonzero_input(self, dummy_model, random_frame_tensor):
        """A non-trivial input should produce at least some non-zero activation."""
        hmap = gradcam_heatmap(dummy_model, random_frame_tensor)
        assert hmap.max() > 0, "Grad-CAM heatmap is all zeros — hooks may have failed"

    def test_different_frames_give_different_heatmaps(self, dummy_model):
        """Two different frames should (almost certainly) give different heatmaps."""
        t1 = torch.randn(3, 224, 224)
        t2 = torch.randn(3, 224, 224)
        h1 = gradcam_heatmap(dummy_model, t1)
        h2 = gradcam_heatmap(dummy_model, t2)
        assert not np.array_equal(h1, h2), "Heatmaps are identical — suspect hook failure"


class TestGradcamToBase64:
    def test_returns_non_empty_string(self, dummy_model, random_frame_tensor):
        hmap = gradcam_heatmap(dummy_model, random_frame_tensor)
        b64 = gradcam_to_base64(hmap)
        assert isinstance(b64, str) and len(b64) > 100

    def test_output_is_valid_base64(self, dummy_model, random_frame_tensor):
        import base64
        hmap = gradcam_heatmap(dummy_model, random_frame_tensor)
        b64 = gradcam_to_base64(hmap)
        # Must not raise
        decoded = base64.b64decode(b64)
        assert len(decoded) > 0

    def test_output_decodes_to_valid_png(self, dummy_model, random_frame_tensor):
        import base64, cv2
        hmap = gradcam_heatmap(dummy_model, random_frame_tensor)
        b64 = gradcam_to_base64(hmap)
        decoded = base64.b64decode(b64)
        arr = np.frombuffer(decoded, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        assert img is not None, "Decoded bytes are not a valid image"
        assert img.shape == (224, 224, 3)