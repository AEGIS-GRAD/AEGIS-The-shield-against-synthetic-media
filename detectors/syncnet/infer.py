"""
SyncNet Inference & Audio-Visual Alignment Scoring Pipeline.

Computes:
- Cross-correlation / Euclidean or Cosine distance across temporal offsets (e.g. [-15, +15] frames).
- Optimal offset (arg min distance) and sync confidence.
- Maps sync mismatch to AEGIS normalized confidence (0.0 = Authentic, 1.0 = Synthetic/Dubbed).
- Applies dubbing-awareness discount to prevent false-fake verdicts on legitimately dubbed content.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F

from models.syncnet import SyncNetModel, load_syncnet_model
from schemas import Evidence, DubbingMetadata

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
        audio_waveform: Optional[np.ndarray] = None,
        audio_sample_rate: int = 16000,
        audio_path: Optional[str] = None,
    ) -> Tuple[float, float, Evidence]:
        """Calculates normalized P(synthetic) score and contextual debate evidence.

        Parameters
        ----------
        vid_tensors:        Pre-extracted lip video window tensors.
        aud_tensors:        Pre-extracted audio MFCC tensors.
        has_audio:          Whether the video has an audio track at all.
        audio_waveform:     Raw mono float32 waveform (optional) for dubbing analysis.
        audio_sample_rate:  Sample rate of ``audio_waveform``.
        audio_path:         File path of the source video (optional, for manifest lookup).

        Returns
        -------
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
                    flags=["not_applicable", "insufficient_signal"],
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

        # ── Dubbing Awareness Discount ─────────────────────────────────────────
        dubbing_meta: Optional[DubbingMetadata] = None
        try:
            from dubbing_awareness import estimate_dubbing_confidence

            # Build waveform from aud_tensors if no explicit waveform provided
            wav = audio_waveform
            if wav is None and aud_tensors:
                # Rough proxy: concatenate MFCC tensors back into a 1-D signal
                # (we just need something for the acoustic features)
                try:
                    concat = torch.cat(aud_tensors, dim=0).cpu().numpy()
                    wav = concat.flatten().astype(np.float32)
                    audio_sample_rate = 16000
                except Exception:
                    wav = np.zeros(16000, dtype=np.float32)

            dub_result = estimate_dubbing_confidence(
                waveform=wav if wav is not None else np.zeros(16000, dtype=np.float32),
                sample_rate=audio_sample_rate,
                audio_path=audio_path,
            )

            raw_p_synthetic = p_synthetic
            p_synthetic = dub_result.apply_discount(p_synthetic)

            dubbing_meta = DubbingMetadata(
                is_dubbed=dub_result.is_dubbed,
                dubbing_confidence=dub_result.dubbing_confidence,
                language_mismatch_prob=dub_result.language_mismatch_prob,
                discount_factor=dub_result.discount_factor,
                raw_syncnet_confidence=round(raw_p_synthetic, 4),
                backend_used=dub_result.backend_used,
                extra=dub_result.metadata if dub_result.metadata else None,
            )

            # Merge dubbing flags into the main flags list
            for f in dub_result.dubbing_flags:
                if f not in flags:
                    flags.append(f)

            if dub_result.is_dubbed and dub_result.dubbing_confidence >= 0.55:
                claim += (
                    f" Note: dubbing-awareness step detected possible dubbed content "
                    f"(confidence {dub_result.dubbing_confidence:.2f}); "
                    f"SyncNet confidence down-weighted by factor {dub_result.discount_factor:.2f}."
                )

        except Exception as dub_exc:
            logger.warning("Dubbing awareness step failed: %s", dub_exc)

        return (
            round(p_synthetic, 4),
            round(raw_score, 4),
            Evidence(claim=claim, flags=flags, dubbing_metadata=dubbing_meta),
        )
