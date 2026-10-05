from __future__ import annotations
import subprocess
import json
import os
from models import InputMetadata


def get_input_metadata(file_path: str, original_filename: str | None = None) -> InputMetadata:
    """
    Run ffprobe to extract stream/format metadata.
    Falls back to extension-based modality guessing if ffprobe is unavailable or fails.
    """
    has_audio = False
    video_stream = None
    duration = 0.0
    resolution = None
    modality = "unknown"

    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "stream=codec_type,width,height",
                "-show_entries", "format=duration",
                "-of", "json", file_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(probe.stdout) if probe.stdout.strip() else {}

        streams = info.get("streams", [])
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        duration = float(info.get("format", {}).get("duration", 0.0))

        if video_stream:
            w = video_stream.get("width")
            h = video_stream.get("height")
            if w and h:
                resolution = [int(w), int(h)]
            modality = "video"
        elif has_audio:
            modality = "audio"
        else:
            # ffprobe found no recognised streams — fall back to extension
            ext = os.path.splitext(file_path)[1].lower()
            modality = "image" if ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif") else "unknown"

    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        # ffprobe not on PATH or timed out — fall back to extension heuristic
        ext = os.path.splitext(file_path)[1].lower()
        video_exts = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
        audio_exts = {".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a"}
        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
        if ext in video_exts:
            modality = "video"
            has_audio = True   # assume audio present; rules will still work conservatively
        elif ext in audio_exts:
            modality = "audio"
            has_audio = True
        elif ext in image_exts:
            modality = "image"
        else:
            modality = "unknown"

    return InputMetadata(
        filename=original_filename or os.path.basename(file_path),
        modality=modality,
        has_audio=has_audio,
        duration_seconds=duration,
        resolution=resolution,
    )