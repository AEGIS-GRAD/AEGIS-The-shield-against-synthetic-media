from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Tuple, Union

if TYPE_CHECKING:
    import numpy as np

import torch
import torch.nn as nn
import torchvision.models as models
try:
    from huggingface_hub import hf_hub_download
except ImportError:  # Allow local checkpoint loading when huggingface_hub is omitted
    hf_hub_download = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DEFAULT_REPO_ID = os.getenv("MODEL_CHECKPOINT_REPO", "Xicor9/efficientnet-b0-ffpp-c23")
DEFAULT_REVISION = os.getenv("MODEL_CHECKPOINT_REVISION", "21aebf2d1c8a7ba85eb61734884c50c877c38ea3")
DEFAULT_FILENAME = "efficientnet_b0_df40_finetuned.pth"
DEFAULT_HF_SHA256 = "2a7963b787ece2594a79160f20e53d6bc621f6bfe34ee21d139efa81bcb70c84"

DEFAULT_LOCAL_CHECKPOINT = Path(__file__).resolve().parent / "models" / "efficientnet_b0_df40_finetuned.pth"
DEFAULT_LOCAL_SHA256 = "cc6b8550d1fc86f6962bfe4593f1ab2df39650f93f1683035d44609e9adc537e"

LEGACY_LOCAL_CHECKPOINT = Path(__file__).resolve().parent / "models" / "ffpp_legacy_baseline" / "efficientnet_b0_ffpp_finetuned.pth"
LEGACY_LOCAL_SHA256 = "5622d78b079927a84a86f8d8545ac76e11130e6d3cbaf7c517ac90e2740f271a"


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
        filename: Checkpoint filename in repo (default 'efficientnet_b0_df40_finetuned.pth').
        device: Device to place the model on ('cpu', 'cuda', etc.).
        checkpoint_path: Optional explicit local checkpoint path (or via MODEL_CHECKPOINT_PATH env var).

    Returns:
        Loaded PyTorch model in eval mode.
    """
    repo_id = checkpoint_repo or os.getenv("MODEL_CHECKPOINT_REPO", DEFAULT_REPO_ID)
    target_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    explicit_local = str(checkpoint_path or os.getenv("MODEL_CHECKPOINT_PATH", "")).strip()

    resolved_ckpt_path: Optional[str] = None
    if explicit_local:
        if os.path.exists(explicit_local):
            resolved_ckpt_path = explicit_local
            logger.info(f"Loading local checkpoint from explicit path / MODEL_CHECKPOINT_PATH: {resolved_ckpt_path}")
        else:
            logger.warning(f"Specified local checkpoint path does not exist: {explicit_local}")

    # Prioritize the primary local fine-tuned DF40 model
    if resolved_ckpt_path is None and DEFAULT_LOCAL_CHECKPOINT.is_file():
        resolved_ckpt_path = str(DEFAULT_LOCAL_CHECKPOINT)
        logger.info(f"Loading primary local DF40 fine-tuned checkpoint: {resolved_ckpt_path}")

    # Fallback to legacy baseline if primary DF40 model is absent
    if resolved_ckpt_path is None and LEGACY_LOCAL_CHECKPOINT.is_file():
        resolved_ckpt_path = str(LEGACY_LOCAL_CHECKPOINT)
        logger.info(f"Loading legacy FF++ baseline checkpoint: {resolved_ckpt_path}")

    # Remote fallback from HuggingFace if no local model file exists
    if resolved_ckpt_path is None:
        logger.info(f"No local model found. Fetching model checkpoint '{filename}' (rev={DEFAULT_REVISION}) from HuggingFace repo '{repo_id}'...")
        try:
            if hf_hub_download is None:
                raise ImportError("huggingface_hub is not installed")
            resolved_ckpt_path = hf_hub_download(repo_id=repo_id, filename=filename, revision=DEFAULT_REVISION)
            if repo_id == "Xicor9/efficientnet-b0-ffpp-c23" and filename == "efficientnet_b0_ffpp_c23.pth":
                _verify_sha256(resolved_ckpt_path, DEFAULT_HF_SHA256)
            logger.info(f"Loaded checkpoint file path: {resolved_ckpt_path}")
        except Exception as exc:
            logger.warning(
                f"Could not load local weights or download from HuggingFace ({exc}). "
                "Using ImageNet-initialized backbone fallback."
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
        elif not expected_ckpt_sha and Path(resolved_ckpt_path).resolve() == LEGACY_LOCAL_CHECKPOINT.resolve():
            expected_ckpt_sha = LEGACY_LOCAL_SHA256
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

def gradcam_heatmap(
    model: Any,
    frame_tensor: Any,
    device: Optional[str] = None,
    target_layer_name: str = "features",
) -> np.ndarray:
    """
    Computes a Grad-CAM heatmap for a single frame tensor.

    Args:
        model:             Pre-loaded EfficientNet-B0 in eval mode.
        frame_tensor:      Pre-processed tensor of shape (3, 224, 224) or (1, 3, 224, 224).
        device:            Inference device; defaults to model's device.
        target_layer_name: Sub-module name whose gradients to hook.
                           EfficientNet-B0's last conv block is 'features'.

    Returns:
        heatmap_uint8: np.ndarray of shape (224, 224), dtype uint8, values 0-255.
                       High values = regions that most influenced the FAKE decision.
    """
    import cv2
    import numpy as np

    if not isinstance(frame_tensor, torch.Tensor):
        frame_tensor = torch.tensor(frame_tensor, dtype=torch.float32)
    if frame_tensor.ndim == 3:
        frame_tensor = frame_tensor.unsqueeze(0)

    target_device = device or next(model.parameters()).device
    frame_tensor = frame_tensor.to(target_device).requires_grad_(False)

    # Storage for forward activations and backward gradients
    activations: list = []
    gradients: list = []

    target_layer = dict(model.named_modules()).get(target_layer_name)
    if target_layer is None:
        # Fallback: use the last Sequential child of features
        target_layer = list(model.features.children())[-1]

    def _save_activation(module, input, output):
        activations.append(output.detach())

    def _save_gradient(module, grad_in, grad_out):
        gradients.append(grad_out[0].detach())

    fwd_hook = target_layer.register_forward_hook(_save_activation)
    bwd_hook = target_layer.register_full_backward_hook(_save_gradient)

    try:
        # Forward pass — need gradient tracking for the backward pass
        frame_tensor.requires_grad_(True)
        logits = model(frame_tensor)
        # Target class: 1 = FAKE
        score = logits[0, 1]
        model.zero_grad()
        score.backward()
    finally:
        fwd_hook.remove()
        bwd_hook.remove()

    if not activations or not gradients:
        # Return blank heatmap if hooks failed
        return np.zeros((224, 224), dtype=np.uint8)

    # Grad-CAM formula: global-average-pool the gradients over H×W
    act = activations[0].squeeze(0)       # (C, H, W)
    grad = gradients[0].squeeze(0)        # (C, H, W)
    weights = grad.mean(dim=(1, 2))       # (C,)
    cam = (weights[:, None, None] * act).sum(dim=0)  # (H, W)
    cam = torch.relu(cam).cpu().numpy()

    # Resize to 224×224 and normalise to uint8
    if cam.max() > 0:
        cam = cam / cam.max()
    cam_resized = cv2.resize(cam, (224, 224), interpolation=cv2.INTER_LINEAR)
    return (cam_resized * 255).astype(np.uint8)


def gradcam_to_base64(heatmap_uint8: np.ndarray) -> str:
    """
    Converts a uint8 Grad-CAM heatmap to a base64-encoded PNG string
    suitable for embedding in JSON responses.

    Args:
        heatmap_uint8: np.ndarray of shape (224, 224), dtype uint8.

    Returns:
        Base64-encoded PNG string (no data-URI prefix).
    """
    import base64
    import cv2
    coloured = cv2.applyColorMap(heatmap_uint8, cv2.COLORMAP_JET)
    _, buf = cv2.imencode(".png", coloured)
    return base64.b64encode(buf.tobytes()).decode("utf-8")

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
