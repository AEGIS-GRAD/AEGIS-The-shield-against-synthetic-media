"""
SyncNet PyTorch Model Architecture.
Based on Joon Son Chung & Andrew Zisserman:
"Out of Time: Automated Lip Sync in the Wild" (ACCV 2016).
"""
from __future__ import annotations

import logging
import os
import urllib.request
from typing import Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "weights", "syncnet_v2.model"
)
DEFAULT_WEIGHTS_URL = os.getenv(
    "SYNCNET_WEIGHTS_URL",
    "http://www.robots.ox.ac.uk/~vgg/software/lipsync/data/syncnet_v2.model"
)


class SyncNetModel(nn.Module):
    """Two-stream convolutional network for audio-to-video synchronization."""

    def __init__(self) -> None:
        super().__init__()

        # Audio stream: takes (B, 1, 13, 20) MFCC representations
        self.netcnnaud = nn.Sequential(
            nn.Conv2d(1, 64, kernel_size=(3, 3), stride=(1, 1), padding=(1, 1)),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(1, 1), stride=(1, 1)),

            nn.Conv2d(64, 192, kernel_size=(3, 3), stride=(1, 1), padding=(1, 1)),
            nn.BatchNorm2d(192),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(3, 3), stride=(1, 2), padding=(1, 1)),

            nn.Conv2d(192, 384, kernel_size=(3, 3), padding=(1, 1)),
            nn.BatchNorm2d(384),
            nn.ReLU(inplace=True),

            nn.Conv2d(384, 256, kernel_size=(3, 3), padding=(1, 1)),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),

            nn.Conv2d(256, 256, kernel_size=(3, 3), padding=(1, 1)),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(3, 3), stride=(2, 2), padding=(1, 1)),

            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Conv2d(256, 512, kernel_size=(1, 1)),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),
        )

        self.netfcaud = nn.Sequential(
            nn.Linear(512, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(inplace=True),
            nn.Linear(512, 1024),
        )

        # Video stream: takes (B, 15, H, W) representing 5 consecutive 3-channel lip frames
        self.netcnnvid = nn.Sequential(
            nn.Conv2d(15, 96, kernel_size=(5, 5), stride=(2, 2), padding=(1, 1)),
            nn.BatchNorm2d(96),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(3, 3), stride=(2, 2)),

            nn.Conv2d(96, 256, kernel_size=(5, 5), stride=(2, 2), padding=(1, 1)),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(3, 3), stride=(2, 2), padding=(1, 1)),

            nn.Conv2d(256, 512, kernel_size=(3, 3), padding=(1, 1)),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),

            nn.Conv2d(512, 512, kernel_size=(3, 3), padding=(1, 1)),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),

            nn.Conv2d(512, 512, kernel_size=(3, 3), padding=(1, 1)),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(3, 3), stride=(2, 2)),

            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Conv2d(512, 512, kernel_size=(1, 1)),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),
        )

        self.netfcvid = nn.Sequential(
            nn.Linear(512, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(inplace=True),
            nn.Linear(512, 1024),
        )

    def forward_aud(self, aud: torch.Tensor) -> torch.Tensor:
        """Extracts 1024-dim audio feature embedding.

        Args:
            aud: Audio MFCC tensor of shape (B, 1, 13, 20).

        Returns:
            L2-normalized audio embedding of shape (B, 1024).
        """
        mid = self.netcnnaud(aud)
        mid = mid.view((mid.size()[0], -1))
        out = self.netfcaud(mid)
        return F.normalize(out, p=2, dim=1)

    def forward_vid(self, vid: torch.Tensor) -> torch.Tensor:
        """Extracts 1024-dim video lip ROI feature embedding.

        Args:
            vid: Video frame tensor of shape (B, 15, H, W).

        Returns:
            L2-normalized video embedding of shape (B, 1024).
        """
        mid = self.netcnnvid(vid)
        mid = mid.view((mid.size()[0], -1))
        out = self.netfcvid(mid)
        return F.normalize(out, p=2, dim=1)

    def forward(
        self, aud: torch.Tensor, vid: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Runs dual-stream forward pass and returns L2-normalized embeddings."""
        out_aud = self.forward_aud(aud)
        out_vid = self.forward_vid(vid)
        return out_aud, out_vid


def load_syncnet_model(
    weights_path: str = DEFAULT_WEIGHTS_PATH,
    device: Optional[torch.device] = None,
    allow_download: bool = False,
) -> Tuple[SyncNetModel, torch.device]:
    """Loads and initializes the SyncNet model on target device.

    Args:
        weights_path: Local path to syncnet checkpoint (.model or .pth).
        device: PyTorch device (CPU or CUDA). Defaults to CUDA if available.
        allow_download: If True, attempts to fetch weights from DEFAULT_WEIGHTS_URL if missing.

    Returns:
        Tuple of (initialized SyncNetModel in eval mode, torch.device).
    """
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = SyncNetModel()

    loaded = False
    if os.path.exists(weights_path):
        try:
            logger.info(f"Loading SyncNet weights from: {weights_path}")
            state_dict = torch.load(weights_path, map_location=device)
            if isinstance(state_dict, dict) and "state_dict" in state_dict:
                state_dict = state_dict["state_dict"]
            model.load_state_dict(state_dict, strict=False)
            logger.info("SyncNet weights loaded successfully.")
            loaded = True
        except Exception as exc:
            logger.warning(f"Failed to load weights from {weights_path}: {exc}")

    if not loaded and allow_download and DEFAULT_WEIGHTS_URL:
        try:
            os.makedirs(os.path.dirname(weights_path), exist_ok=True)
            logger.info(f"Downloading SyncNet weights from {DEFAULT_WEIGHTS_URL} to {weights_path}...")
            urllib.request.urlretrieve(DEFAULT_WEIGHTS_URL, weights_path)
            state_dict = torch.load(weights_path, map_location=device)
            model.load_state_dict(state_dict, strict=False)
            logger.info("SyncNet weights downloaded and loaded successfully.")
            loaded = True
        except Exception as exc:
            logger.warning(f"Could not download SyncNet weights: {exc}")

    if not loaded:
        logger.warning(
            f"Weights not found at {weights_path}. SyncNet initialized with initialized parameters."
        )

    model.to(device)
    model.eval()
    return model, device
