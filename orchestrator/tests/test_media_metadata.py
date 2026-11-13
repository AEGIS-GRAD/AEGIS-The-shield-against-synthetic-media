"""
Unit tests for orchestrator/app/media_metadata.py.
Verifies runtime luminance, face presence extraction, duration, audio presence,
and operating conditions derivation.
"""

import os
import sys
from pathlib import Path
import pytest

_APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from media_metadata import get_input_metadata, _compute_visual_conditions
from judge_bridge import build_operating_conditions


def test_audio_metadata_conditions():
    """Audio files should report audio presence, no luminance, and no face."""
    wav_fixture = Path(__file__).resolve().parent.parent.parent / "detectors" / "aasist" / "tests" / "fixtures" / "clean_sample.wav"
    if not wav_fixture.exists():
        pytest.skip("Fixture clean_sample.wav not found")

    meta = get_input_metadata(str(wav_fixture))
    assert meta.has_audio is True
    assert meta.modality == "audio"
    assert meta.mean_luminance is None
    assert meta.face_detected is False

    cond = build_operating_conditions(meta)
    assert cond.audio_present is True
    assert cond.mean_luminance is None
    assert cond.face_detected is False


def test_video_metadata_conditions():
    """Video files should compute real luminance and face detection."""
    vid_fixture = Path(__file__).resolve().parent.parent.parent / "web" / "public" / "sample_videos" / "authentic_feed.mp4"
    if not vid_fixture.exists():
        vid_fixture = Path(__file__).resolve().parent.parent.parent / "detectors" / "video-classifier" / "tests" / "fixtures" / "clean_sample.mp4"
    if not vid_fixture.exists():
        pytest.skip("No video fixture available")

    meta = get_input_metadata(str(vid_fixture))
    assert meta.modality == "video"
    assert meta.mean_luminance is not None
    assert meta.mean_luminance > 0.0

    cond = build_operating_conditions(meta)
    assert cond.mean_luminance == meta.mean_luminance
    assert cond.duration_seconds == meta.duration_seconds

