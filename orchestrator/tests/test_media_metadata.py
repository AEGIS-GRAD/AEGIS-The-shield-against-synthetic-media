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


def test_ffprobe_uses_single_combined_show_entries_and_empty_stream_fallback(tmp_path, monkeypatch):
    """ffprobe overwrites repeated -show_entries flags; verify one combined flag and extension fallback."""
    import json
    import subprocess
    from unittest.mock import MagicMock

    wav = tmp_path / "dummy.wav"
    wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    captured_cmds = []

    def fake_run(cmd, **kwargs):
        captured_cmds.append(cmd)
        return MagicMock(stdout=json.dumps({"streams": [], "format": {"duration": "N/A"}}), returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    meta = get_input_metadata(str(wav))
    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert cmd.count("-show_entries") == 1
    entries = cmd[cmd.index("-show_entries") + 1]
    assert "stream=" in entries and "format=" in entries
    assert meta.modality == "audio"
    assert meta.has_audio is True
    assert meta.duration_seconds == 0.0


def test_ffprobe_still_image_stream_stays_image_modality(tmp_path, monkeypatch):
    """ffprobe labels JPEG/PNG files as codec_type=video; verify still images resolve to 'image'."""
    import json
    import subprocess
    from unittest.mock import MagicMock

    jpg = tmp_path / "sample.jpg"
    jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)

    def fake_run(cmd, **kwargs):
        return MagicMock(
            stdout=json.dumps({
                "streams": [{"codec_type": "video", "codec_name": "mjpeg", "width": 640, "height": 480}],
                "format": {"duration": "0.04"},
            }),
            returncode=0,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    meta = get_input_metadata(str(jpg), original_filename="sample.jpg")
    assert meta.modality == "image"
    assert meta.has_audio is False
    assert meta.duration_seconds == 0.0
    assert meta.resolution == [640, 480]

