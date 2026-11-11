from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from debate.prompt_security import sanitize_exif_metadata, sanitize_filename
from models import InputMetadata


def _extract_image_exif(file_path: str) -> Dict[str, Any]:
    """Best-effort EXIF tag extraction for image files when Pillow is available."""
    try:
        from PIL import ExifTags, Image

        with Image.open(file_path) as img:
            raw_exif = img.getexif() if hasattr(img, "getexif") else None
            out: Dict[str, Any] = {}
            if raw_exif:
                for tag_id, val in raw_exif.items():
                    name = str(ExifTags.TAGS.get(tag_id, tag_id)).lower()
                    out[name] = val
            for k, v in getattr(img, "info", {}).items():
                if isinstance(v, (str, int, float)):
                    out[str(k).lower()] = v
            return out
    except Exception:
        return {}


def extract_sanitized_media_tags(
    file_path: str,
    raw_tags: Dict[str, Any] | None = None,
) -> tuple[Dict[str, str], list[str]]:
    """Extracts and sanitizes EXIF / container metadata before entering orchestrator state."""
    combined: Dict[str, Any] = {}
    if raw_tags:
        combined.update(raw_tags)
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tiff"):
        combined.update(_extract_image_exif(file_path))
    return sanitize_exif_metadata(combined)


def get_input_metadata(
    file_path: str,
    original_filename: str | None = None,
    raw_tags: Dict[str, Any] | None = None,
) -> InputMetadata:
    """
    Run ffprobe to extract stream/format metadata and sanitize untrusted filename / EXIF tags.
    Falls back to extension-based modality guessing if ffprobe is unavailable or fails.
    """
    has_audio = False
    video_stream = None
    duration = 0.0
    resolution = None
    modality = "unknown"
    ffprobe_tags: Dict[str, Any] = {}

    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "stream=codec_type,width,height",
                "-show_entries", "format=duration:format_tags",
                "-of", "json", file_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(probe.stdout) if probe.stdout.strip() else {}

        streams = info.get("streams", [])
        fmt = info.get("format", {})
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        duration = float(fmt.get("duration", 0.0))
        if isinstance(fmt.get("tags"), dict):
            ffprobe_tags.update(fmt["tags"])

        if video_stream:
            w = video_stream.get("width")
            h = video_stream.get("height")
            if w and h:
                resolution = [int(w), int(h)]
            modality = "video"
        elif has_audio:
            modality = "audio"
        else:
            ext = os.path.splitext(file_path)[1].lower()
            modality = "image" if ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif") else "unknown"

    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        ext = os.path.splitext(file_path)[1].lower()
        video_exts = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
        audio_exts = {".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a"}
        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
        if ext in video_exts:
            modality = "video"
            has_audio = True
        elif ext in audio_exts:
            modality = "audio"
            has_audio = True
        elif ext in image_exts:
            modality = "image"
        else:
            modality = "unknown"

    merged_raw_tags = dict(ffprobe_tags)
    if raw_tags:
        merged_raw_tags.update(raw_tags)

    fn_res = sanitize_filename(original_filename or os.path.basename(file_path))
    safe_tags, tag_flags = extract_sanitized_media_tags(file_path, merged_raw_tags)
    all_flags = list(fn_res.flags) + tag_flags

    return InputMetadata(
        filename=fn_res.sanitized,
        modality=modality,
        has_audio=has_audio,
        duration_seconds=duration,
        resolution=resolution,
        metadata_tags=safe_tags,
        sanitization_flags=all_flags,
    )
