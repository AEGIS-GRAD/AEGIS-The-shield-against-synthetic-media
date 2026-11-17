from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, List, Optional, Union

import torch
import torch.nn as nn
import torchvision.models as models
from huggingface_hub import hf_hub_download

logger = logging.getLogger(__name__)

DEFAULT_REPO_ID = os.getenv("MODEL_CHECKPOINT_REPO", "Xicor9/efficientnet-b0-ffpp-c23")
DEFAULT_REVISION = os.getenv("MODEL_CHECKPOINT_REVISION", "21aebf2d1c8a7ba85eb61734884c50c877c38ea3")
DEFAULT_FILENAME = "efficientnet_b0_ffpp_c23.pth"
DEFAULT_HF_SHA256 = "2a7963b787ece2594a79160f20e53d6bc621f6bfe34ee21d139efa81bcb70c84"
DEFAULT_LOCAL_CHECKPOINT = Path(__file__).resolve().parent / "models" / "efficientnet_b0_ffpp_finetuned.pth"
DEFAULT_LOCAL_SHA256 = "5622d78b079927a84a86f8d8545ac76e11130e6d3cbaf7c517ac90e2740f271a"


def _verify_sha256(file_path: str | Path, expected_sha256: str) -> None:
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
            f"Video classifier weights integrity check failed for {file_path}: "
            f"expected {expected_sha256}, got {actual}"
        )


def load_model(
    checkpoint_repo: Optional[str] = None,
    filename: str = DEFAULT_FILENAME,
    device: Optional[str] = None,
    checkpoint_path: Optional[Union[str, Path]] = None,
) -> Any:
    """Loads EfficientNet-B0 checkpoint from local path, env var, or HuggingFace Hub.

    Args:
        checkpoint_repo: HuggingFace repository ID (defaults to MODEL_CHECKPOINT_REPO env var or 'Xicor9/efficientnet-b0-ffpp-c23').
        filename: Checkpoint filename in repo (default 'efficientnet_b0_ffpp_c23.pth').
        device: Device to place the model on ('cpu', 'cuda', etc.).
        checkpoint_path: Optional explicit local checkpoint path (or via MODEL_CHECKPOINT_PATH env var).

    Returns:
        Loaded PyTorch model in eval mode.
    """
    repo_id = checkpoint_repo or os.getenv("MODEL_CHECKPOINT_REPO", DEFAULT_REPO_ID)
    target_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    explicit_local = str(checkpoint_path or os.getenv("MODEL_CHECKPOINT_PATH", "")).strip()
    allow_fallback = os.getenv("ALLOW_LOCAL_CHECKPOINT_FALLBACK", "0").strip().lower() in {"1", "true", "yes"}

    resolved_ckpt_path: Optional[str] = None
    if explicit_local:
        if os.path.exists(explicit_local):
            resolved_ckpt_path = explicit_local
            logger.info(f"Loading local checkpoint from MODEL_CHECKPOINT_PATH: {resolved_ckpt_path}")
        else:
            logger.warning(f"Specified local checkpoint path does not exist: {explicit_local}")

    if resolved_ckpt_path is None:
        logger.info(f"Fetching model checkpoint '{filename}' (rev={DEFAULT_REVISION}) from HuggingFace repo '{repo_id}'...")
        try:
            resolved_ckpt_path = hf_hub_download(repo_id=repo_id, filename=filename, revision=DEFAULT_REVISION)
            if repo_id == "Xicor9/efficientnet-b0-ffpp-c23" and filename == DEFAULT_FILENAME:
                _verify_sha256(resolved_ckpt_path, DEFAULT_HF_SHA256)
            logger.info(f"Loaded checkpoint file path: {resolved_ckpt_path}")
        except Exception as exc:
            if allow_fallback and DEFAULT_LOCAL_CHECKPOINT.is_file():
                resolved_ckpt_path = str(DEFAULT_LOCAL_CHECKPOINT)
                _verify_sha256(resolved_ckpt_path, DEFAULT_LOCAL_SHA256)
                logger.info(
                    f"HuggingFace unavailable ({exc}); using verified local fallback checkpoint: {resolved_ckpt_path}"
                )
            else:
                logger.warning(
                    f"Could not download checkpoint from HuggingFace ({exc}). Using randomly initialized model fallback for offline evaluation."
                )
                resolved_ckpt_path = None

    # Build EfficientNet-B0 architecture
    try:
        model = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT)
    except AttributeError:
        model = models.efficientnet_b0(pretrained=True)

    # Replace final classification layer with 2 outputs (0=Real, 1=Fake)
    in_features = model.classifier[1].in_features
    model.classifier[1] = nn.Linear(in_features, 2)

    if resolved_ckpt_path and os.path.exists(resolved_ckpt_path):
        expected_ckpt_sha = os.getenv("VIDEO_CLASSIFIER_SHA256", "").strip().lower()
        if not expected_ckpt_sha and Path(resolved_ckpt_path).resolve() == DEFAULT_LOCAL_CHECKPOINT.resolve():
            expected_ckpt_sha = DEFAULT_LOCAL_SHA256
        if expected_ckpt_sha:
            _verify_sha256(resolved_ckpt_path, expected_ckpt_sha)
        # Strictly enforce safe tensor deserialization (no arbitrary pickle deserialization fallback)
        state_dict = torch.load(resolved_ckpt_path, map_location=target_device, weights_only=True)

        # Handle state dict wrapped under keys like "state_dict" or "model"
        if isinstance(state_dict, dict):
            if "state_dict" in state_dict:
                state_dict = state_dict["state_dict"]
            elif "model" in state_dict:
                state_dict = state_dict["model"]

        try:
            model.load_state_dict(state_dict)
        except RuntimeError:
            # Try stripping 'module.' prefix if saved with DataParallel
            new_state_dict = {}
            for k, v in state_dict.items():
                name = k[7:] if k.startswith("module.") else k
                new_state_dict[name] = v
            model.load_state_dict(new_state_dict)

    model.to(target_device)
    model.eval()
    logger.info("Successfully initialized EfficientNet-B0 model in eval mode.")
    return model


def predict_frame(model: Any, frame_tensor: Any, device: Optional[str] = None) -> float:
    """Predicts frame authenticity score using model forward pass.

    Args:
        model: Pre-loaded PyTorch model in eval mode.
        frame_tensor: Preprocessed frame tensor of shape (3, 224, 224) or (1, 3, 224, 224).
        device: Device to perform inference on.

    Returns:
        Authenticity score float in range [0.0, 1.0] (probability of class 1 = Fake).
    """
    if model is None:
        raise ValueError("Model must be loaded before calling predict_frame.")

    if not isinstance(frame_tensor, torch.Tensor):
        frame_tensor = torch.tensor(frame_tensor, dtype=torch.float32)

    if frame_tensor.ndim == 3:
        frame_tensor = frame_tensor.unsqueeze(0)

    target_device = device or next(model.parameters()).device
    frame_tensor = frame_tensor.to(target_device)

    with torch.no_grad():
        logits = model(frame_tensor)
        probs = torch.softmax(logits, dim=1)
        fake_prob = probs[0, 1].item()

    return float(fake_prob)


def aggregate_scores(frame_scores: List[float]) -> float:
    """Aggregates per-frame authenticity scores using mean pooling.

    Args:
        frame_scores: List of float scores in range [0.0, 1.0] per video frame.

    Returns:
        Aggregated video-level authenticity score float in range [0.0, 1.0].
        Returns 0.5 default score if frame_scores list is empty.
    """
    if not frame_scores:
        logger.warning("Empty frame_scores list provided for score aggregation. Returning default score 0.5.")
        return 0.5

    mean_score = sum(frame_scores) / len(frame_scores)
    # Ensure score is strictly clamped to [0.0, 1.0] range
    return float(max(0.0, min(1.0, mean_score)))
