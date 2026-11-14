"""Text ingestion, shared-volume path confinement, base64 decoding, and Unicode normalization."""
from __future__ import annotations

import base64
import binascii
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

ALLOWED_TEXT_EXTENSIONS = {".txt", ".md"}
_DATA_URI_PREFIX_RE = re.compile(r"^data:text/[a-zA-Z0-9.+-]+(?:;[a-zA-Z0-9=_-]+)*;base64,", re.I)


class IngestionError(ValueError):
    """Base error raised when request payload cannot be ingested cleanly."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class PayloadTooLargeError(IngestionError):
    """Raised when payload exceeds configured byte or character limits."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=413)


class PathSecurityError(IngestionError):
    """Raised when a filesystem path escapes the permitted shared volume root."""


@dataclass(frozen=True)
class IngestedText:
    """Normalized text payload plus surface statistics."""

    text: str
    source_kind: str
    char_count: int
    word_count: int
    line_count: int
    paragraph_count: int
    stripped_control_chars: int


def _looks_like_filepath(payload: str) -> bool:
    """Identify Unix, Windows drive/UNC, or file:// paths rather than base64 strings."""
    if payload.startswith(("file://", "/", "\\\\", "./", "../", ".\\", "..\\")):
        return True
    if len(payload) >= 3 and payload[1] == ":" and payload[2] in ("/", "\\"):
        return True
    return False


def _resolve_confined_path(raw_path: str, shared_root: Path) -> Path:
    """Resolve filepath and verify it stays strictly within shared_root."""
    if "\x00" in raw_path:
        raise PathSecurityError("Null byte rejected in filepath.", status_code=400)

    cleaned = raw_path[7:] if raw_path.startswith("file://") else raw_path
    candidate_raw = Path(cleaned)
    if not candidate_raw.is_absolute():
        raise PathSecurityError("Filepath payload must be an absolute path.", status_code=400)

    root_resolved = shared_root.resolve()
    try:
        resolved = candidate_raw.resolve()
    except OSError as exc:
        raise PathSecurityError(f"Unresolvable filepath: {exc}", status_code=400) from exc

    if not resolved.is_relative_to(root_resolved):
        raise PathSecurityError(
            f"Filepath escapes allowed shared volume root ({shared_root}).", status_code=400
        )

    if resolved.suffix.lower() not in ALLOWED_TEXT_EXTENSIONS:
        raise IngestionError(
            f"Unsupported text file extension '{resolved.suffix}'; expected {sorted(ALLOWED_TEXT_EXTENSIONS)}.",
            status_code=400,
        )

    if not resolved.exists() or not resolved.is_file():
        raise IngestionError(f"Text file not found: {resolved.name}", status_code=404)

    return resolved


def _read_raw_text_from_payload(
    payload: str, shared_root: Path, max_chars: int
) -> Tuple[str, str]:
    """Read UTF-8 text either from a confined file or strict base64 string."""
    max_bytes = max_chars * 4  # Upper bound for valid UTF-8 encoding
    if _looks_like_filepath(payload):
        resolved = _resolve_confined_path(payload, shared_root)
        file_size = resolved.stat().st_size
        if file_size > max_bytes:
            raise PayloadTooLargeError(
                f"Text file ({file_size} bytes) exceeds maximum allowed limit ({max_bytes} bytes)."
            )
        raw_bytes = resolved.read_bytes()
        source_kind = "filepath"
    else:
        b64_body = _DATA_URI_PREFIX_RE.sub("", payload)
        b64_compact = "".join(b64_body.split())
        if not b64_compact:
            raise IngestionError("Base64 payload is empty.", status_code=400)
        # Estimate decoded byte size before full allocation on oversized requests
        est_bytes = (len(b64_compact) * 3) // 4
        if est_bytes > max_bytes + 4:
            raise PayloadTooLargeError(
                f"Encoded payload (~{est_bytes} bytes) exceeds maximum limit ({max_bytes} bytes)."
            )
        try:
            raw_bytes = base64.b64decode(b64_compact, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise IngestionError(f"Invalid base64 text payload: {exc}", status_code=400) from exc
        if len(raw_bytes) > max_bytes:
            raise PayloadTooLargeError(
                f"Decoded payload ({len(raw_bytes)} bytes) exceeds maximum limit ({max_bytes} bytes)."
            )
        source_kind = "base64"

    try:
        decoded = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestionError(f"Payload is not valid UTF-8 text: {exc}", status_code=400) from exc

    return decoded, source_kind


def normalize_text(raw_text: str, max_chars: int) -> Tuple[str, int]:
    """Apply BOM strip, char cap check, NFKC normalization, and hidden-char sanitization."""
    text = raw_text.lstrip("\ufeff")
    if len(text) > max_chars:
        raise PayloadTooLargeError(
            f"Text length ({len(text)} chars) exceeds MAX_CHARS ({max_chars})."
        )

    text = unicodedata.normalize("NFKC", text)

    stripped_count = 0
    cleaned_chars = []
    for ch in text:
        if ch in ("\n", "\r", "\t"):
            cleaned_chars.append(ch)
            continue
        cat = unicodedata.category(ch)
        # Strip non-printable control (Cc) and format/bidi/zero-width chars (Cf)
        if cat in ("Cc", "Cf"):
            stripped_count += 1
            continue
        cleaned_chars.append(ch)

    sanitized = "".join(cleaned_chars)
    sanitized = sanitized.replace("\r\n", "\n").replace("\r", "\n")
    sanitized = re.sub(r"[ \t]+", " ", sanitized)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
    sanitized = sanitized.strip()
    return sanitized, stripped_count


def count_words(text: str) -> int:
    """Count whitespace/punctuation-delimited word tokens consistently across stylometry and gating."""
    return len(re.findall(r"\b\w+(?:['’-]\w+)*\b", text))


def ingest_payload(
    payload: str,
    shared_root: Path | None = None,
    max_chars: int = 200_000,
) -> IngestedText:
    """Ingest, validate, decode, and normalize a contract `payload` into structured text stats."""
    if not isinstance(payload, str) or not payload.strip():
        raise IngestionError("Payload must be a non-empty string.", status_code=400)

    root = shared_root or Path(os.getenv("AEGIS_SHARED_VOLUME", "/shared_volume"))
    decoded, source_kind = _read_raw_text_from_payload(payload.strip(), root, max_chars)
    return prepare_raw_text(decoded, source_kind=source_kind, max_chars=max_chars)


def prepare_raw_text(
    raw_text: str,
    source_kind: str = "raw",
    max_chars: int = 200_000,
) -> IngestedText:
    """Normalize an already-decoded string (shared by `/detect` and legacy `/analyze`)."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise IngestionError("Decoded text is empty.", status_code=400)

    normalized, stripped_count = normalize_text(raw_text, max_chars=max_chars)
    word_count = count_words(normalized)
    if not normalized or word_count == 0:
        raise IngestionError("Text contains no scorable words after normalization.", status_code=400)

    lines = [line for line in normalized.splitlines() if line.strip()]
    paragraphs = [p for p in normalized.split("\n\n") if p.strip()]
    return IngestedText(
        text=normalized,
        source_kind=source_kind,
        char_count=len(normalized),
        word_count=word_count,
        line_count=len(lines),
        paragraph_count=len(paragraphs),
        stripped_control_chars=stripped_count,
    )

