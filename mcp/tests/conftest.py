"""
Pytest configuration and shared fixtures for the AEGIS MCP test suite.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Keep per-call MCP audit records out of the shared security/vault during tests.
os.environ.setdefault("AEGIS_MCP_AUDIT_VAULT_DIR", tempfile.mkdtemp(prefix="aegis_mcp_audit_"))

# Ensure repo root and mcp dir are on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MCP_DIR = _REPO_ROOT / "mcp"

for _p in [str(_REPO_ROOT), str(_MCP_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server  # Import the AEGIS MCP server module


@pytest.fixture
def sample_video_classifier_synthetic() -> Dict[str, Any]:
    return {
        "job_id": "test-job-e2e-001",
        "detector_id": "video-classifier",
        "model_version": "xception-ff++-v1",
        "domain": "spatial_pixel",
        "polarity": "SYNTHETIC",
        "confidence": 0.94,
        "raw_score": 0.94,
        "claim": "Frame-level analysis found strong spatial face manipulation evidence.",
        "flags": ["high_fake_probability"],
    }


@pytest.fixture
def sample_rppg_authentic() -> Dict[str, Any]:
    return {
        "job_id": "test-job-e2e-001",
        "detector_id": "rppg",
        "model_version": "rppg-toolbox-physnet-v1",
        "domain": "physiological_bvp",
        "polarity": "AUTHENTIC",
        "confidence": 0.15,
        "raw_score": 0.15,
        "claim": "A stable periodic pulse consistent with a live face was detected.",
        "flags": ["stable_pulse_detected"],
    }


@pytest.fixture
def sample_rppg_synthetic() -> Dict[str, Any]:
    return {
        "job_id": "test-job-e2e-001",
        "detector_id": "rppg",
        "model_version": "rppg-toolbox-physnet-v1",
        "domain": "physiological_bvp",
        "polarity": "SYNTHETIC",
        "confidence": 0.85,
        "raw_score": 0.85,
        "claim": "No stable heartbeat signal found in the facial skin region.",
        "flags": ["insufficient_lighting", "low_light_attenuation"],
    }


@pytest.fixture
def sample_syncnet_desync() -> Dict[str, Any]:
    return {
        "job_id": "test-job-e2e-001",
        "detector_id": "syncnet",
        "model_version": "syncnet-v1",
        "domain": "audiovisual_sync",
        "polarity": "SYNTHETIC",
        "confidence": 0.88,
        "raw_score": 6.0,
        "claim": "Severe lip-sync mismatch: audio leads video by 6 frames.",
        "flags": ["audio_visual_mismatch"],
    }


@pytest.fixture
def sample_syncnet_authentic() -> Dict[str, Any]:
    return {
        "job_id": "test-job-e2e-001",
        "detector_id": "syncnet",
        "model_version": "syncnet-v1",
        "domain": "audiovisual_sync",
        "polarity": "AUTHENTIC",
        "confidence": 0.18,
        "raw_score": 0.0,
        "claim": "Lip movements are tightly synchronized with speech.",
        "flags": ["lip_sync_verified"],
    }


@pytest.fixture
def sample_aasist_synthetic() -> Dict[str, Any]:
    return {
        "job_id": "test-job-e2e-001",
        "detector_id": "aasist",
        "model_version": "aasist-v1.2",
        "domain": "audio_acoustic",
        "polarity": "SYNTHETIC",
        "confidence": 0.91,
        "raw_score": 0.91,
        "claim": "Acoustic graph attention detected cloned speech patterns.",
        "flags": ["voice_cloning_suspected"],
    }


@pytest.fixture
def sample_nominal_conditions() -> Dict[str, Any]:
    return {
        "duration_seconds": 8.0,
        "mean_luminance": 120.0,
        "face_detected": True,
        "audio_present": True,
        "video_bitrate_kbps": 2500.0,
    }
