"""
File-signature ("magic bytes") sniffing.

Extensions are what a client *claims* a file is; magic bytes are what the
file's own leading byte pattern says it actually is. An attacker can rename
any executable to `payload.mp4`, so the allowlist in config.py is only the
first gate - this module is the one that catches a spoofed extension.

Detection here is intentionally self-contained (no libmagic dependency) so
the validator image stays small and the checks stay auditable in one file.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SniffResult:
    valid: bool
    detected_type: str
    reason: str


def _is_mp4_or_mov(content: bytes) -> bool:
    # ISO base media file format (MP4/MOV/M4A/...) stores a 4-byte size
    # followed by an 'ftyp' box at byte offset 4. Covers both extensions
    # since QuickTime .mov commonly uses the same container box.
    return len(content) >= 8 and content[4:8] == b"ftyp"


def _is_wav(content: bytes) -> bool:
    return len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"WAVE"


def _is_mp3(content: bytes) -> bool:
    if len(content) >= 3 and content[0:3] == b"ID3":
        return True
    # Frameless MP3: 11-bit frame sync (0xFFE0 mask) at the start.
    return len(content) >= 2 and content[0] == 0xFF and (content[1] & 0xE0) == 0xE0


def _is_jpeg(content: bytes) -> bool:
    return len(content) >= 3 and content[0:3] == b"\xff\xd8\xff"


def _is_png(content: bytes) -> bool:
    return len(content) >= 8 and content[0:8] == b"\x89PNG\r\n\x1a\n"


def _looks_like_text(content: bytes) -> bool:
    if b"\x00" in content:
        return False
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


# Maps an allowed extension to the check(s) that must pass for content
# claiming that extension. `.jpg`/`.jpeg` share a signature; `.txt` has no
# fixed magic number so it's checked structurally instead.
_CHECKS = {
    ".mp4": _is_mp4_or_mov,
    ".mov": _is_mp4_or_mov,
    ".wav": _is_wav,
    ".mp3": _is_mp3,
    ".jpg": _is_jpeg,
    ".jpeg": _is_jpeg,
    ".png": _is_png,
    ".txt": _looks_like_text,
}

_BINARY_SIGNATURE_CHECKS = (
    ("mp4/mov", _is_mp4_or_mov),
    ("wav", _is_wav),
    ("mp3", _is_mp3),
    ("jpeg", _is_jpeg),
    ("png", _is_png),
)


def sniff_extension(extension: str, content: bytes) -> SniffResult:
    """Check that `content`'s magic bytes match what `extension` claims."""
    ext = extension.lower()
    check = _CHECKS.get(ext)
    if check is None:
        return SniffResult(False, "unknown", f"Extension '{ext}' is not allowlisted")

    if not check(content):
        return SniffResult(
            False,
            ext,
            f"Content does not match the file signature expected for '{ext}'",
        )
    return SniffResult(True, ext, "Magic bytes match declared extension")


def sniff_audio_payload(content: bytes) -> SniffResult:
    """
    Audio ingestion has no client-supplied filename/extension (see
    DetectorRequest in SCHEMA.md - only job_id/modality/payload). Instead of
    trusting the declared `modality`, confirm the decoded bytes are actually
    one of the allowed audio containers (WAV or MP3).
    """
    if _is_wav(content):
        return SniffResult(True, ".wav", "Magic bytes match WAV")
    if _is_mp3(content):
        return SniffResult(True, ".mp3", "Magic bytes match MP3")
    return SniffResult(
        False, "unknown", "Decoded payload does not match WAV or MP3 signatures"
    )
