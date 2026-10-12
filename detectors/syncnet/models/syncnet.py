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
            nn.MaxPool2d(kernel_size=(3, 3), stride=(1, 2)),

            nn.Conv2d(192, 384, kernel_size=(3, 3), padding=(1, 1)),
            nn.BatchNorm2d(384),
            nn.ReLU(inplace=True),

            nn.Conv2d(384, 256, kernel_size=(3, 3), padding=(1, 1)),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),

            nn.Conv2d(256, 256, kernel_size=(3, 3), padding=(1, 1)),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(3, 3), stride=(2, 2)),

            nn.Conv2d(256, 512, kernel_size=(5, 4), padding=(0, 0)),
            nn.BatchNorm2d(512),
            nn.ReLU(),
        )

        self.netfcaud = nn.Sequential(
            nn.Linear(512, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.Linear(512, 1024),
        )

        # Video stream: 3D Lip CNN
        self.netcnnlip = nn.Sequential(
            nn.Conv3d(3, 96, kernel_size=(5, 7, 7), stride=(1, 2, 2), padding=0),
            nn.BatchNorm3d(96),
            nn.ReLU(inplace=True),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 2, 2)),

            nn.Conv3d(96, 256, kernel_size=(1, 5, 5), stride=(1, 2, 2), padding=(0, 1, 1)),
            nn.BatchNorm3d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 2, 2), padding=(0, 1, 1)),

            nn.Conv3d(256, 256, kernel_size=(1, 3, 3), padding=(0, 1, 1)),
            nn.BatchNorm3d(256),
            nn.ReLU(inplace=True),

            nn.Conv3d(256, 256, kernel_size=(1, 3, 3), padding=(0, 1, 1)),
            nn.BatchNorm3d(256),
            nn.ReLU(inplace=True),

            nn.Conv3d(256, 256, kernel_size=(1, 3, 3), padding=(0, 1, 1)),
            nn.BatchNorm3d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 2, 2)),

            nn.Conv3d(256, 512, kernel_size=(1, 6, 6), padding=0),
            nn.BatchNorm3d(512),
            nn.ReLU(inplace=True),
        )

        self.netfclip = nn.Sequential(
            nn.Linear(512, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.Linear(512, 1024),
        )

    def forward_aud(self, aud: torch.Tensor) -> torch.Tensor:
        """Extracts 1024-dim audio feature embedding."""
        mid = self.netcnnaud(aud)
        mid = mid.view((mid.size(0), -1))
        out = self.netfcaud(mid)
        return F.normalize(out, p=2, dim=1)

    def forward_vid(self, vid: torch.Tensor) -> torch.Tensor:
        """Extracts 1024-dim video lip ROI feature embedding."""
        if vid.dim() == 4 and vid.size(1) == 15:
            # Convert (B, 15, H, W) -> (B, 3, 5, H, W)
            b, _, h, w = vid.shape
            vid = vid.view(b, 5, 3, h, w).permute(0, 2, 1, 3, 4)
        if vid.size(-1) != 224 or vid.size(-2) != 224:
            vid = F.interpolate(vid, size=(5, 224, 224), mode="trilinear", align_corners=False)
        mid = self.netcnnlip(vid)
        mid = mid.view((mid.size(0), -1))
        out = self.netfclip(mid)
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
    """Loads and initializes the SyncNet model on target device."""
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
            model.load_state_dict(state_dict, strict=True)
            logger.info("SyncNet weights loaded successfully with strict=True.")
            loaded = True
        except Exception as exc:
            logger.warning(f"Failed to load weights from {weights_path}: {exc}")

    if not loaded and allow_download and DEFAULT_WEIGHTS_URL:
        try:
            os.makedirs(os.path.dirname(weights_path), exist_ok=True)
            logger.info(f"Downloading SyncNet weights from {DEFAULT_WEIGHTS_URL} to {weights_path}...")
            urllib.request.urlretrieve(DEFAULT_WEIGHTS_URL, weights_path)
            state_dict = torch.load(weights_path, map_location=device)
            model.load_state_dict(state_dict, strict=True)
            logger.info("SyncNet weights downloaded and loaded successfully.")
            loaded = True
        except Exception as exc:
            logger.warning(f"Could not download SyncNet weights: {exc}")

    if not loaded:
        logger.warning(
            f"Weights not found at {weights_path}. SyncNet initialized with random parameters."
        )

    model.to(device)
    model.eval()
    return model, device
