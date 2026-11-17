"""
Loads Community Forensics ViT-Small model in fp16.
Backbone: ViT-Small / Patch 16 / 384x384 resolution
Weights: detectors/image/weights/model.safetensors
"""

import os
import hashlib
import logging
import torch
import timm
from safetensors.torch import load_file

logger = logging.getLogger(__name__)

MODEL_VERSION = "commfor-model-384-fp16"
COMMFOR_HF_REPO = "OwensLab/commfor-model-384"
COMMFOR_HF_REVISION = "6076002bf0d9dd37537f965ee2f06f826c333b61"
COMMFOR_SAFETENSORS_SHA256 = "b89f36275f3bf5e2b040eee36597a8f19db051bff9a473a9cf7b2466284fb387"
DEFAULT_WEIGHTS_DIR = os.path.join(os.path.dirname(__file__), "..", "weights")


def _verify_sha256(file_path: str, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    actual = digest.hexdigest().lower()
    if actual != expected_sha256.lower():
        raise RuntimeError(
            f"Image model integrity check failed for {file_path}: "
            f"expected {expected_sha256}, got {actual}"
        )


def load_model(weights_dir: str = DEFAULT_WEIGHTS_DIR):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Loading Community Forensics model on device: {device}")

    weights_path = os.path.join(weights_dir, "model.safetensors")
    if not os.path.exists(weights_path):
        raise FileNotFoundError(
            f"Weights not found at '{weights_path}'. "
            "Please download OwensLab/commfor-model-384 into weights/ first."
        )

    expected_sha256 = os.getenv("COMMFOR_WEIGHTS_SHA256", COMMFOR_SAFETENSORS_SHA256).strip().lower()
    if expected_sha256 and os.getenv("AEGIS_ALLOW_UNVERIFIED_WEIGHTS", "0") != "1":
        _verify_sha256(weights_path, expected_sha256)

    # Initialize ViT-Small backbone (num_classes=1 for binary fake logit)
    model = timm.create_model(
        "vit_small_patch16_384",
        pretrained=False,
        num_classes=1
    )

    logger.info(f"Loading weights from: {weights_path}")
    state_dict = load_file(weights_path, device=str(device))
    clean_sd = {k.replace("vit.", ""): v for k, v in state_dict.items()}
    model.load_state_dict(clean_sd, strict=False)
    logger.info("Community Forensics weights loaded successfully.")

    # Cast to fp16 for 8 GB GPU VRAM efficiency
    model = model.half().to(device).eval()

    return model, device