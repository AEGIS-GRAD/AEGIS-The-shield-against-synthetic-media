from __future__ import annotations

import importlib
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
        pil_image = importlib.import_module("PIL.Image")
        pil_exif_tags = importlib.import_module("PIL.ExifTags")

        with pil_image.open(file_path) as img:
            raw_exif = img.getexif() if hasattr(img, "getexif") else None
            out: Dict[str, Any] = {}
            if raw_exif:
                for tag_id, val in raw_exif.items():
                    name = str(pil_exif_tags.TAGS.get(tag_id, tag_id)).lower()
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


def _compute_visual_conditions(
    file_path: str,
    modality: str,
) -> tuple[Optional[float], Optional[bool]]:
    """
    Computes mean luminance (0-255 scale) and face presence from visual media.
    For audio or non-visual content, returns (None, False).
    """
    if modality == "audio":
        return None, False

    if not os.path.exists(file_path):
        return None, None

    try:
        import cv2

        face_cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        cascade = cv2.CascadeClassifier(face_cascade_path) if os.path.exists(face_cascade_path) else None

        if modality == "image":
            img = cv2.imread(os.path.abspath(file_path))
            if img is not None:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                lum = float(gray.mean())
                face_detected = False
                if cascade:
                    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3, minSize=(20, 20))
                    face_detected = len(faces) > 0
                return round(lum, 2), face_detected

        elif modality == "video":
            cap = cv2.VideoCapture(os.path.abspath(file_path))
            if cap.isOpened():
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                sample_count = 10
                if total_frames > 0:
                    step = max(1, total_frames // sample_count)
                    sample_indices = list(range(0, total_frames, step))[:sample_count]
                else:
                    sample_indices = list(range(sample_count))

                luminances: list[float] = []
                face_detected = False

                for idx in sample_indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        continue
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    luminances.append(float(gray.mean()))
                    if cascade and not face_detected:
                        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3, minSize=(20, 20))
                        if len(faces) > 0:
                            face_detected = True
                cap.release()
                if luminances:
                    return round(sum(luminances) / len(luminances), 2), face_detected
            cap.release()

    except Exception:
        pass

    return None, None


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
            if ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"):
                modality = "image"
            elif ext in (".txt", ".md", ".json", ".csv", ".doc", ".docx"):
                modality = "text"
            else:
                modality = "unknown"

    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        ext = os.path.splitext(file_path)[1].lower()
        video_exts = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
        audio_exts = {".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a"}
        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
        text_exts = {".txt", ".md", ".json", ".csv", ".doc", ".docx"}
        if ext in video_exts:
            modality = "video"
            has_audio = True
        elif ext in audio_exts:
            modality = "audio"
            has_audio = True
        elif ext in image_exts:
            modality = "image"
        elif ext in text_exts:
            modality = "text"
        else:
            modality = "unknown"

    merged_raw_tags = dict(ffprobe_tags)
    if raw_tags:
        merged_raw_tags.update(raw_tags)

    fn_res = sanitize_filename(original_filename or os.path.basename(file_path))
    safe_tags, tag_flags = extract_sanitized_media_tags(file_path, merged_raw_tags)
    all_flags = list(fn_res.flags) + tag_flags
    mean_lum, face_det = _compute_visual_conditions(file_path, modality)

    return InputMetadata(
        filename=fn_res.sanitized,
        modality=modality,
        has_audio=has_audio,
        duration_seconds=duration,
        resolution=resolution,
        metadata_tags=safe_tags,
        sanitization_flags=all_flags,
        mean_luminance=mean_lum,
        face_detected=face_det,
    )
