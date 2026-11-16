"""
Central configuration for the AEGIS gateway upload validator.

Values here mirror the limits mandated by
shared/json-api-contracts-schema/SCHEMA.md Section 1 (Security Requirements).
Do not change MAX_UPLOAD_BYTES or ALLOWED_EXTENSIONS without updating that
schema doc first - this service exists to enforce it, not redefine it.
"""

import os

# SCHEMA.md: "Max Payload Size: 50 MB hard limit."
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# SCHEMA.md: "Explicit Allowlist & Magic Bytes: Only .mp4, .mov, .wav, .mp3,
# .jpg, .png, and .txt are permitted."
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".wav", ".mp3", ".jpg", ".jpeg", ".png", ".txt"}

# SCHEMA.md: "the Orchestrator MUST sanitize the input and ensure the path is
# strictly confined to the authorized /shared_volume/ directory."
SHARED_VOLUME_ROOT = os.getenv("SHARED_VOLUME_ROOT", "/shared_volume")

# Upstream detector services this validator forwards clean requests to.
VIDEO_DETECTOR_URL = os.getenv(
    "VIDEO_DETECTOR_URL", "http://aegis_detector_video_classifier:8000/detect"
)
AUDIO_DETECTOR_URL = os.getenv(
    "AUDIO_DETECTOR_URL", "http://aegis_detector_aasist:8000/detect"
)
IMAGE_DETECTOR_URL = os.getenv(
    "IMAGE_DETECTOR_URL", "http://aegis_detector_image:8000/detect"
)
TEXT_DETECTOR_URL = os.getenv(
    "TEXT_DETECTOR_URL", "http://aegis_detector_text:8000/detect"
)

# Deep inspection bounds for image and text payloads (DoS / decompression-bomb / prompt guards).
MAX_IMAGE_WIDTH = int(os.getenv("MAX_IMAGE_WIDTH", "16384"))
MAX_IMAGE_HEIGHT = int(os.getenv("MAX_IMAGE_HEIGHT", "16384"))
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", str(40_000_000)))
MAX_IMAGE_DECOMPRESSED_BYTES = int(
    os.getenv("MAX_IMAGE_DECOMPRESSED_BYTES", str(128 * 1024 * 1024))
)
MAX_PNG_COMPRESSION_RATIO = float(os.getenv("MAX_PNG_COMPRESSION_RATIO", "250.0"))
MAX_EXIF_BYTES = int(os.getenv("MAX_EXIF_BYTES", str(256 * 1024)))
MAX_ICC_BYTES = int(os.getenv("MAX_ICC_BYTES", str(512 * 1024)))
MAX_TEXT_BYTES = int(os.getenv("MAX_TEXT_BYTES", str(800_000)))
MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", "200000"))

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

# Per-key rate limiting is enforced by nginx (see ../nginx.conf.template).
# This service is only reachable from inside aegis_net, behind that gate.
UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "30"))
