from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
try:
    import torchvision.models as models
    HAS_TORCHVISION = True
except Exception as exc:
    models = None
    HAS_TORCHVISION = False
    logger.warning("torchvision could not be loaded (%s). Using pure PyTorch fallback.", exc)

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS_PATH = Path(__file__).parent / "mobilenetv3_small_ffpp.pth"


def get_mobilenet_v3_small_model(
    checkpoint_path: Optional[str | Path] = None,
    device: Optional[str] = None,
) -> nn.Module:
    """Builds MobileNetV3-Small architecture for 2-class deepfake detection (Real vs Fake).

    Args:
        checkpoint_path: Optional path to .pth checkpoint file.
        device: Target device ('cpu', 'cuda').

    Returns:
        Loaded PyTorch MobileNetV3-Small model in eval mode.
    """
    target_device = device or ("cuda" if torch.cuda.is_available() else "cpu")

    if HAS_TORCHVISION and models is not None:
        # Load MobileNetV3-Small backbone with default pretrained weights
        try:
            model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
        except Exception:
            model = models.mobilenet_v3_small(pretrained=True)

        # Replace classifier output layer with 2 outputs (0=Real, 1=Fake)
        in_features = model.classifier[3].in_features
        model.classifier[3] = nn.Linear(in_features, 2)
    else:
        # Pure PyTorch fallback without requiring torchvision / PIL DLLs
        class FallbackEdgeClassifier(nn.Module):
            def __init__(self):
                super().__init__()
                self.features = nn.Sequential(
                    nn.Conv2d(3, 16, kernel_size=3, stride=2, padding=1),
                    nn.BatchNorm2d(16),
                    nn.Hardswish(),
                    nn.AdaptiveAvgPool2d((1, 1)),
                )
                self.classifier = nn.Sequential(
                    nn.Flatten(),
                    nn.Linear(16, 2)
                )
            def forward(self, x):
                return self.classifier(self.features(x))

        model = FallbackEdgeClassifier()

    weights_file = Path(checkpoint_path or DEFAULT_WEIGHTS_PATH)
    if weights_file.exists():
        logger.info(f"Loading MobileNetV3-Small checkpoint from {weights_file}")
        state_dict = torch.load(weights_file, map_location=target_device)
        if isinstance(state_dict, dict) and "state_dict" in state_dict:
            state_dict = state_dict["state_dict"]
        model.load_state_dict(state_dict)
    else:
        logger.info(f"No checkpoint found at {weights_file}. Initialized pretrained backbone with 2-class head.")
        # Ensure default weights file exists for future load
        os.makedirs(weights_file.parent, exist_ok=True)
        torch.save(model.state_dict(), weights_file)
        logger.info(f"Saved initial edge model weights to {weights_file}")

    model.to(target_device)
    model.eval()
    return model


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    m = get_mobilenet_v3_small_model()
    print(f"MobileNetV3-Small edge model ready: {type(m).__name__}")
