"""
Loads Community Forensics ViT-Small model in fp16.
Backbone: ViT-Small / Patch 16 / 384x384 resolution
Weights: detectors/image/weights/model.safetensors
"""

import os
import logging
import torch
import timm
from safetensors.torch import load_file

logger = logging.getLogger(__name__)

MODEL_VERSION = "commfor-model-384-fp16"
DEFAULT_WEIGHTS_DIR = os.path.join(os.path.dirname(__file__), "..", "weights")


def load_model(weights_dir: str = DEFAULT_WEIGHTS_DIR):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Loading Community Forensics model on device: {device}")

    weights_path = os.path.join(weights_dir, "model.safetensors")
    if not os.path.exists(weights_path):
        raise FileNotFoundError(
            f"Weights not found at '{weights_path}'. "
            "Please download OwensLab/commfor-model-384 into weights/ first."
        )

    # Initialize ViT-Small backbone (num_classes=1 for binary fake logit)
    model = timm.create_model(
        "vit_small_patch16_384",
        pretrained=False,
        num_classes=1
    )

    logger.info(f"Loading weights from: {weights_path}")
    state_dict = load_file(weights_path, device=str(device))
    model.load_state_dict(state_dict, strict=True)
    logger.info("Community Forensics weights loaded successfully.")

    # Cast to fp16 for 8 GB GPU VRAM efficiency
    model = model.half().to(device).eval()

    return model, device