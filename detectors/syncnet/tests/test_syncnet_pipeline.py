import os
import numpy as np
import pytest
import torch

from models.syncnet import SyncNetModel, load_syncnet_model
from preprocess import SyncNetPreprocessor
from infer import SyncNetInference


def test_syncnet_model_forward():
    """Validates PyTorch tensor shapes through audio and video branches."""
    model = SyncNetModel()
    model.eval()

    # Video input: (B, 15, 112, 112)
    vid_in = torch.randn(2, 15, 112, 112)
    vid_emb = model.forward_vid(vid_in)
    assert vid_emb.shape == (2, 1024)
    # Check L2 normalization
    norms = torch.norm(vid_emb, p=2, dim=1)
    assert torch.allclose(norms, torch.ones_like(norms), atol=1e-4)

    # Audio input: (B, 1, 13, 20)
    aud_in = torch.randn(2, 1, 13, 20)
    aud_emb = model.forward_aud(aud_in)
    assert aud_emb.shape == (2, 1024)
    norms = torch.norm(aud_emb, p=2, dim=1)
    assert torch.allclose(norms, torch.ones_like(norms), atol=1e-4)


def test_preprocessing_mfcc():
    """Validates MFCC feature computation from audio array."""
    sr = 16000
    duration = 1.0  # 1 second of audio
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    sig = np.sin(2 * np.pi * 440 * t).astype(np.float32)

    mfcc = SyncNetPreprocessor.compute_mfcc(sig, sample_rate=sr, n_mfcc=13)
    assert mfcc.shape[1] == 13
    # At 100 Hz hop (10ms), 1 second should yield ~98-100 frames
    assert 90 <= mfcc.shape[0] <= 105


def test_preprocessor_silent_video(sample_clips):
    """Ensures preprocessor explicitly identifies videos with no audio track."""
    pre = SyncNetPreprocessor()
    silent_clip = sample_clips["silent"]

    vid_seqs, aud_seqs, has_audio = pre.preprocess(silent_clip)
    assert has_audio is False
    assert aud_seqs is None
    assert len(vid_seqs) > 0
    # Each video sequence tensor should be 5 frames * 3 channels = 15 channels
    assert vid_seqs[0].shape == (15, 112, 112)


def test_score_silent_video_returns_not_applicable():
    """Validates that silent videos cleanly return not_applicable without error."""
    inference = SyncNetInference()
    dummy_vid_tensors = [torch.randn(15, 112, 112) for _ in range(10)]

    score, raw, evidence = inference.score_video(
        vid_tensors=dummy_vid_tensors,
        aud_tensors=None,
        has_audio=False,
    )
    assert score == 0.5
    assert raw == 0.0
    assert "not_applicable" in evidence.flags
    assert "No audio track" in evidence.claim


def test_offset_scoring_sensitivity():
    """Verifies that temporal audio shift changes optimal offset and confidence."""
    inference = SyncNetInference()

    # Generate synthetic synchronized embeddings
    num_steps = 30
    shared_features = np.random.randn(num_steps, 1024).astype(np.float32)
    # L2 normalize
    shared_features /= np.linalg.norm(shared_features, axis=1, keepdims=True)

    # In-sync: vid and aud match exactly
    vid_sync = shared_features.copy()
    aud_sync = shared_features.copy()

    profile_sync = inference.compute_offset_profile(vid_sync, aud_sync)
    assert profile_sync["optimal_offset"] == 0
    assert profile_sync["min_distance"] < 0.01

    # Shifted / Dubbed: audio is shifted by 5 steps
    aud_shifted = np.roll(shared_features, 5, axis=0)
    profile_shifted = inference.compute_offset_profile(vid_sync, aud_shifted)
    assert profile_shifted["optimal_offset"] != 0
