"""
SyncNet Inference & Audio-Visual Alignment Scoring Pipeline.

Computes:
- Cross-correlation / Euclidean or Cosine distance across temporal offsets (e.g. [-15, +15] frames).
- Optimal offset (arg min distance) and sync confidence.
- Maps sync mismatch to AEGIS normalized confidence (0.0 = Authentic, 1.0 = Synthetic/Dubbed).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F

from models.syncnet import SyncNetModel, load_syncnet_model
from schemas import Evidence

logger = logging.getLogger(__name__)

MODEL_VERSION = "syncnet-v1.3"


class SyncNetInference:
    """Runs temporal synchronization analysis between audio and video lip embeddings."""

    def __init__(
        self,
        model: Optional[SyncNetModel] = None,
        device: Optional[torch.device] = None,
        v_shift: int = 15,
    ) -> None:
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if model is not None:
            self.model = model
        else:
            self.model, self.device = load_syncnet_model(device=self.device)
        self.v_shift = v_shift

    def compute_embeddings(
        self,
        vid_tensors: List[torch.Tensor],
        aud_tensors: List[torch.Tensor],
        batch_size: int = 20,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Computes normalized 1024-d embeddings for video lip windows and audio MFCC slices."""
        vid_embeds: List[np.ndarray] = []
        aud_embeds: List[np.ndarray] = []

        with torch.no_grad():
            # Process video batches
            for i in range(0, len(vid_tensors), batch_size):
                batch = torch.stack(vid_tensors[i : i + batch_size]).to(self.device)
                emb = self.model.forward_vid(batch)
                vid_embeds.append(emb.cpu().numpy())

            # Process audio batches
            for i in range(0, len(aud_tensors), batch_size):
                batch = torch.stack(aud_tensors[i : i + batch_size]).to(self.device)
                emb = self.model.forward_aud(batch)
                aud_embeds.append(emb.cpu().numpy())

        vid_arr = np.concatenate(vid_embeds, axis=0) if vid_embeds else np.zeros((0, 1024))
        aud_arr = np.concatenate(aud_embeds, axis=0) if aud_embeds else np.zeros((0, 1024))
        return vid_arr, aud_arr

    def compute_offset_profile(
        self,
        vid_embeds: np.ndarray,
        aud_embeds: np.ndarray,
    ) -> Dict[str, Any]:
        """Computes distance profile across candidate temporal shifts [-v_shift, +v_shift].

        Distance at offset v is:
            d(v) = mean_i || aud_embeds[i] - vid_embeds[i + v] ||_2
        """
        min_len = min(len(vid_embeds), len(aud_embeds))
        if min_len <= 1:
            return {
                "optimal_offset": 0,
                "min_distance": 0.0,
                "confidence_score": 0.0,
                "dists": [],
            }

        # Search range
        v_shift = min(self.v_shift, (min_len - 1) // 2)
        if v_shift < 1:
            v_shift = 1

        dists = []
        shifts = list(range(-v_shift, v_shift + 1))

        for shift in shifts:
            if shift < 0:
                # Video leads audio
                a = aud_embeds[-shift:min_len]
                v = vid_embeds[0 : min_len + shift]
            elif shift > 0:
                # Audio leads video
                a = aud_embeds[0 : min_len - shift]
                v = vid_embeds[shift:min_len]
            else:
                a = aud_embeds[0:min_len]
                v = vid_embeds[0:min_len]

            # Cosine distance or Euclidean distance
            # For L2-normalized embeddings, ||a - v||_2^2 = 2 - 2*(a . v)
            cos_sim = np.sum(a * v, axis=1)
            dist = np.mean(1.0 - cos_sim)
            dists.append(float(dist))

        dists_arr = np.array(dists)
        min_idx = int(np.argmin(dists_arr))
        optimal_offset = shifts[min_idx]
        min_dist = float(dists_arr[min_idx])
        median_dist = float(np.median(dists_arr))

        # Peak distinction confidence: how much lower min_dist is compared to median
        sync_confidence = max(0.0, median_dist - min_dist)

        return {
            "optimal_offset": optimal_offset,
            "min_distance": min_dist,
            "sync_confidence": sync_confidence,
            "dists": dists,
        }

    def score_video(
        self,
        vid_tensors: List[torch.Tensor],
        aud_tensors: Optional[List[torch.Tensor]],
        has_audio: bool,
    ) -> Tuple[float, float, Evidence]:
        """Calculates normalized P(synthetic) score and contextual debate evidence.

        Returns:
            Tuple of (confidence [0.0, 1.0], raw_score, Evidence).
        """
        if not has_audio or aud_tensors is None or len(aud_tensors) == 0:
            return (
                0.5,
                0.0,
                Evidence(
                    claim="No audio track detected in submitted file — lip-sync analysis skipped.",
                    flags=["not_applicable"],
                ),
            )

        if len(vid_tensors) == 0:
            return (
                0.5,
                0.0,
                Evidence(
                    claim="No valid face or mouth region detected in video — lip-sync analysis skipped.",
                    flags=["not_applicable"],
                ),
            )

        vid_embeds, aud_embeds = self.compute_embeddings(vid_tensors, aud_tensors)
        profile = self.compute_offset_profile(vid_embeds, aud_embeds)

        offset = profile["optimal_offset"]
        min_dist = profile["min_distance"]
        sync_conf = profile.get("sync_confidence", 0.0)

        # Decision contract:
        # Authentic: offset is near 0 (|offset| <= 1 frame) and min_dist is small
        # Synthetic / Dubbed: offset is large (|offset| >= 2) or audio-visual correlation is flat
        abs_offset = abs(offset)
        raw_score = float(offset)

        flags = []
        if abs_offset == 0 and min_dist < 0.35:
            # Strong authentic synchronization
            p_synthetic = 0.12
            claim = f"Lip movements tightly synchronized with audio phonemes (offset: {offset} frames, dist: {min_dist:.2f})."
            flags.append("lip_sync_verified")
        elif abs_offset <= 1 and min_dist < 0.45:
            # Acceptable natural variation
            p_synthetic = 0.28
            claim = f"Lip-sync alignment is within natural speech variation limits (offset: {offset} frames)."
            flags.append("in_sync")
        elif abs_offset <= 3:
            # Noticeable offset
            p_synthetic = 0.65
            claim = f"Mild lip-audio offset detected ({offset} frames), slightly above natural variation range."
            flags.extend(["sync_offset_detected"])
        else:
            # Severe desync / dubbing
            p_synthetic = 0.92
            direction = "leads" if offset > 0 else "lags"
            claim = (
                f"Severe lip-sync discrepancy detected: audio {direction} video by {abs_offset} frames "
                f"({abs_offset * 40}ms), strongly indicating dubbed audio or synthetic generation."
            )
            flags.extend(["sync_offset_detected", "audio_visual_mismatch"])

        return round(p_synthetic, 4), round(raw_score, 4), Evidence(claim=claim, flags=flags)
