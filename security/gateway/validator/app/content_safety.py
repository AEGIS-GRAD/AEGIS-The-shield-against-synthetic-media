"""
Deep content inspection for image and text uploads in the AEGIS gateway validator.

Performs self-contained (zero C-decoder exposure) verification prior to forwarding:
  1. Image inspection (PNG / JPEG):
     - Container framing verification and polyglot rejection (trailing bytes after
       IEND/EOI, embedded ZIP/ELF/PE/PDF/archive/script/HTML signatures).
     - Header pixel-dimension and decompression-bomb limits (bounded streaming zlib
       inflation for PNG IDAT/zTXt/iTXt/iCCP and pixel-memory bounds for JPEG SOF).
     - EXIF / XMP / ICC profile / PNG text-chunk structural bounds and inspection.
  2. Text inspection:
     - Strict UTF-8 decoding, NUL rejection, BOM stripping, length limits, and Unicode
       NFKC normalization.
     - Removal of control (`Cc`, preserving tab/newline spacing) and zero-width /
       bidi formatting characters (`Cf`).
  3. Prompt-injection / instruction-string flagging:
     - Scans normalized text and extracted image metadata/EXIF/ICC strings for
       instruction-like directives before payloads ever reach downstream LLM judges.
"""

from __future__ import annotations

import math
import re
import struct
import unicodedata
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import config
from .magic_bytes import _is_jpeg, _is_png

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_COLOR_CHANNELS = {
    0: 1,  # grayscale
    2: 3,  # RGB
    3: 1,  # palette index
    4: 2,  # grayscale + alpha
    6: 4,  # RGBA
}

_JPEG_STANDALONE_MARKERS = {0x00, 0x01, 0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9}
_JPEG_SOF_MARKERS = {
    0xC0, 0xC1, 0xC2, 0xC3,
    0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB,
    0xCD, 0xCE, 0xCF,
}

# Binary & active-document signatures used to spot polyglot files disguised as media/text.
_POLYGLOT_BINARY_SIGNATURES: Tuple[Tuple[str, bytes], ...] = (
    ("zip_archive", b"PK\x03\x04"),
    ("zip_eocd", b"PK\x05\x06"),
    ("elf_binary", b"\x7fELF"),
    ("pdf_document", b"%PDF-"),
    ("rar_archive", b"Rar!\x1a\x07"),
    ("sevenzip_archive", b"7z\xbc\xaf'\x1c"),
    ("shebang_script", b"#!"),
)

_POLYGLOT_TEXT_RE = re.compile(
    rb"(?:<\?php|<!doctype\s+html|<script\b|<html\b|<svg\b)",
    re.IGNORECASE,
)

# Instruction-like / prompt-injection signatures (aligned with debate/prompt_security.py).
_INJECTION_RULES: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass|discard)\b"
            r"(?:[^.\n]{0,40})\b(?:previous|prior|above|system|rules?|instructions?|precedence|guard(?:rail)?s?|analysis)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_role_spoof",
        re.compile(
            r"(?:\[\s*system\s*\]|<\s*/?\s*system\s*>|<<\s*/?sys\s*>>|<\|im_(?:start|end)\|>|"
            r"\[/?inst\]|\bsystem\s+override\b|\b(?:system|developer|assistant)\s*:)",
            re.IGNORECASE,
        ),
    ),
    (
        "verdict_coercion_authentic",
        re.compile(
            r"\b(?:answer|reply|respond|output|return|rule|judge|classify|certify|conclude|set|mark|treat|declare|say)\b"
            r"(?:[^.\n]{0,45})\b(?:as\s+|to\s+)?authentic\b"
            r"|\b(?:final_verdict|verdict)\b[\"']?\s*[:=]\s*[\"']?authentic[\"']?",
            re.IGNORECASE,
        ),
    ),
    (
        "planner_sabotage",
        re.compile(
            r"\b(?:skip|disable|omit|drop)\s+(?:all\s+)?(?:detectors?|stages?|checks?)\b"
            r"|\bmark\s+all\s+detectors?\s+(?:as\s+)?degraded\b"
            r"|\bset\s+plan_version\b",
            re.IGNORECASE,
        ),
    ),
    (
        "persona_hijack",
        re.compile(
            r"\b(?:you\s+are\s+now|act\s+as\s+(?:a|an|the)?\s*(?:judge|system|admin|root)|new\s+instructions?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter_escape",
        re.compile(r"</?\s*(?:untrusted_)?evidence(?:_data)?[^>]*>|boundary\s*=", re.IGNORECASE),
    ),
    (
        "canary_exfiltration",
        re.compile(
            r"(?:\b(?:reveal|print|echo|repeat|output|leak|expose)\b.{0,35}\b(?:system\s+prompt|instructions?|canary)\b"
            r"|aegis[-_]canary)",
            re.IGNORECASE,
        ),
    ),
)


class ContentValidationError(ValueError):
    """Raised when uploaded content violates security or structural bounds."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class TextInspectionResult:
    normalized_text: str
    normalized_bytes: bytes
    stripped_control_chars: int
    had_invisible_unicode: bool
    instruction_flags: List[str] = field(default_factory=list)

    @property
    def security_flags(self) -> List[str]:
        flags = list(self.instruction_flags)
        if self.stripped_control_chars > 0:
            flags.append("control_or_zero_width_chars_stripped")
        return flags


@dataclass(frozen=True)
class ImageInspectionResult:
    format_name: str
    width: int
    height: int
    exif_present: bool
    icc_present: bool
    metadata_flags: List[str] = field(default_factory=list)
    instruction_flags: List[str] = field(default_factory=list)

    @property
    def security_flags(self) -> List[str]:
        return list(dict.fromkeys(self.instruction_flags))


def _strip_unicode_controls(text: str, *, preserve_newlines: bool) -> Tuple[str, int, bool]:
    """Normalize NFKC and strip Cc/Cf control and invisible zero-width/bidi characters."""
    normalized = unicodedata.normalize("NFKC", text)
    out: List[str] = []
    stripped_count = 0
    saw_invisible = False

    for ch in normalized:
        cat = unicodedata.category(ch)
        if cat == "Cf":
            stripped_count += 1
            saw_invisible = True
            continue
        if cat == "Cc":
            if preserve_newlines and ch in ("\n", "\r", "\t"):
                out.append(ch)
                continue
            stripped_count += 1
            continue
        out.append(ch)

    joined = "".join(out)
    if preserve_newlines:
        joined = joined.replace("\r\n", "\n").replace("\r", "\n")
    else:
        joined = " ".join(joined.split())
    return joined, stripped_count, saw_invisible


def detect_instruction_strings(text: str) -> List[str]:
    """Return matching instruction/prompt-injection rule IDs on normalized text."""
    if not text:
        return []
    collapsed, _, _ = _strip_unicode_controls(text, preserve_newlines=False)
    return [name for name, pattern in _INJECTION_RULES if pattern.search(collapsed)]


def _check_polyglot_blob(blob: bytes, *, context: str, reject_pe: bool = False) -> None:
    """Reject trailing or metadata blobs embedding foreign executable/archive/script payloads."""
    if not blob:
        return
    if reject_pe and blob.startswith(b"MZ"):
        raise ContentValidationError(
            415, f"Polyglot payload detected ({context}): embedded PE/MZ header"
        )
    for label, sig in _POLYGLOT_BINARY_SIGNATURES:
        if sig in blob:
            raise ContentValidationError(
                415, f"Polyglot payload detected ({context}): embedded {label} signature"
            )
    if _POLYGLOT_TEXT_RE.search(blob):
        raise ContentValidationError(
            415, f"Polyglot payload detected ({context}): embedded active script/HTML markup"
        )


def _inflate_zlib_bounded(data: bytes, max_bytes: int, label: str) -> bytes:
    """Decompress a single zlib stream with strict output memory bounds."""
    decomp = zlib.decompressobj()
    try:
        out = decomp.decompress(data, max_bytes)
        if decomp.unconsumed_tail:
            raise ContentValidationError(
                413, f"Decompression bomb detected in {label}: exceeds {max_bytes} byte limit"
            )
        tail = decomp.flush()
    except zlib.error as exc:
        raise ContentValidationError(400, f"Malformed compressed stream in {label}: {exc}") from exc

    total = len(out) + len(tail)
    if total > max_bytes:
        raise ContentValidationError(
            413, f"Decompression bomb detected in {label}: exceeds {max_bytes} byte limit"
        )
    return out + tail


def _validate_icc_profile(icc: bytes) -> List[str]:
    """Validate minimal ICC binary header and scan embedded ASCII/UTF-16 tags for directives."""
    if len(icc) > config.MAX_ICC_BYTES:
        raise ContentValidationError(
            413, f"ICC profile exceeds {config.MAX_ICC_BYTES} byte metadata limit"
        )
    if len(icc) < 128 or icc[36:40] != b"acsp":
        raise ContentValidationError(415, "Malformed or spoofed ICC profile header (missing 'acsp')")

    declared_size = struct.unpack(">I", icc[0:4])[0]
    if declared_size < 128 or declared_size > len(icc) + 64:
        raise ContentValidationError(415, "Malformed ICC profile declared length")

    _check_polyglot_blob(icc, context="icc_profile")
    return _scan_binary_metadata_text(icc, prefix="icc")


def _extract_tiff_ascii_strings(tiff: bytes) -> List[str]:
    """Safely extract ASCII/UTF-8 string runs and IFD tag strings from a TIFF/EXIF header."""
    if len(tiff) < 8:
        return []
    endian_tag = tiff[:2]
    if endian_tag == b"II":
        endian = "<"
    elif endian_tag == b"MM":
        endian = ">"
    else:
        return []

    magic = struct.unpack(endian + "H", tiff[2:4])[0]
    if magic != 42:
        return []

    ifd_offset = struct.unpack(endian + "I", tiff[4:8])[0]
    strings: List[str] = []
    if 8 <= ifd_offset <= len(tiff) - 2:
        entry_count = struct.unpack(endian + "H", tiff[ifd_offset : ifd_offset + 2])[0]
        entry_count = min(entry_count, 256)
        cursor = ifd_offset + 2
        for _ in range(entry_count):
            if cursor + 12 > len(tiff):
                break
            _, field_type, count, val_or_off = struct.unpack(
                endian + "HHII", tiff[cursor : cursor + 12]
            )
            cursor += 12
            # Type 2 = ASCII, Type 7 = UNDEFINED (often UserComment)
            if field_type in (2, 7) and 0 < count <= 65536:
                if count <= 4:
                    raw = tiff[cursor - 4 : cursor - 4 + count]
                elif val_or_off + count <= len(tiff):
                    raw = tiff[val_or_off : val_or_off + count]
                else:
                    raw = b""
                if raw:
                    strings.append(raw.decode("utf-8", errors="ignore"))
    return strings


def _scan_binary_metadata_text(blob: bytes, *, prefix: str) -> List[str]:
    """Inspect printable/UTF-8 strings in binary metadata blobs for instruction-like text."""
    candidates: List[str] = []
    # Also scan printable ASCII sequences >= 6 bytes so non-IFD metadata can't slip past.
    for match in re.finditer(rb"[\x20-\x7e\xc2-\xf4][\x09\x20-\x7e\x80-\xf4]{5,}", blob):
        candidates.append(match.group(0).decode("utf-8", errors="ignore"))

    joined = "\n".join(candidates)
    hits = detect_instruction_strings(joined)
    return [f"{prefix}:{rule}" for rule in hits]


def _inspect_exif_blob(exif_payload: bytes) -> List[str]:
    """Validate EXIF payload size, polyglot safety, and scan IFD/text tags for directives."""
    if len(exif_payload) > config.MAX_EXIF_BYTES:
        raise ContentValidationError(
            413, f"EXIF metadata exceeds {config.MAX_EXIF_BYTES} byte limit"
        )
    _check_polyglot_blob(exif_payload, context="exif_metadata")

    flags: List[str] = []
    if exif_payload.startswith(b"Exif\x00\x00"):
        tiff = exif_payload[6:]
    else:
        tiff = exif_payload

    extracted = _extract_tiff_ascii_strings(tiff)
    if extracted:
        for hit in detect_instruction_strings("\n".join(extracted)):
            flags.append(f"exif:{hit}")
    for hit_flag in _scan_binary_metadata_text(tiff, prefix="exif"):
        if hit_flag not in flags:
            flags.append(hit_flag)
    return flags


def _check_image_dimensions(width: int, height: int, channels: int = 4, bit_depth: int = 8) -> None:
    """Enforce dimension and decompression-bomb pixel/byte bounds."""
    if width <= 0 or height <= 0:
        raise ContentValidationError(400, f"Invalid zero image dimensions: {width}x{height}")
    if width > config.MAX_IMAGE_WIDTH or height > config.MAX_IMAGE_HEIGHT:
        raise ContentValidationError(
            413,
            f"Image dimensions {width}x{height} exceed {config.MAX_IMAGE_WIDTH}x{config.MAX_IMAGE_HEIGHT} limit",
        )
    pixels = width * height
    if pixels > config.MAX_IMAGE_PIXELS:
        raise ContentValidationError(
            413, f"Image pixel count ({pixels}) exceeds {config.MAX_IMAGE_PIXELS} decompression-bomb limit"
        )
    row_bytes = 1 + math.ceil(width * channels * bit_depth / 8)
    est_bytes = height * row_bytes
    if est_bytes > config.MAX_IMAGE_DECOMPRESSED_BYTES:
        raise ContentValidationError(
            413,
            f"Estimated uncompressed image size ({est_bytes} bytes) exceeds {config.MAX_IMAGE_DECOMPRESSED_BYTES} limit",
        )


def _inspect_png(content: bytes) -> ImageInspectionResult:
    pos = len(PNG_SIGNATURE)
    width = 0
    height = 0
    seen_ihdr = False
    seen_idat = False
    seen_iend = False
    exif_present = False
    icc_present = False
    metadata_flags: List[str] = []
    instruction_flags: List[str] = []

    idat_decomp = zlib.decompressobj()
    total_idat_compressed = 0
    total_idat_decompressed = 0

    while pos + 12 <= len(content):
        chunk_len = struct.unpack(">I", content[pos : pos + 4])[0]
        chunk_type = content[pos + 4 : pos + 8]
        data_start = pos + 8
        data_end = data_start + chunk_len
        if data_end + 4 > len(content):
            raise ContentValidationError(400, "Truncated or malformed PNG chunk length")
        chunk_data = content[data_start:data_end]
        pos = data_end + 4

        if not seen_ihdr:
            if chunk_type != b"IHDR" or chunk_len != 13:
                raise ContentValidationError(415, "PNG missing valid leading IHDR chunk")
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk_data[:10])
            channels = _PNG_COLOR_CHANNELS.get(color_type, 4)
            _check_image_dimensions(width, height, channels=channels, bit_depth=bit_depth or 8)
            seen_ihdr = True
            continue

        if chunk_type == b"IDAT":
            seen_idat = True
            total_idat_compressed += chunk_len
            remaining = config.MAX_IMAGE_DECOMPRESSED_BYTES - total_idat_decompressed
            try:
                chunk_out = idat_decomp.decompress(chunk_data, remaining + 1)
            except zlib.error as exc:
                raise ContentValidationError(400, f"Malformed PNG IDAT zlib stream: {exc}") from exc
            total_idat_decompressed += len(chunk_out)
            if total_idat_decompressed > config.MAX_IMAGE_DECOMPRESSED_BYTES or idat_decomp.unconsumed_tail:
                raise ContentValidationError(
                    413,
                    f"PNG decompression bomb detected: IDAT stream exceeds {config.MAX_IMAGE_DECOMPRESSED_BYTES} bytes",
                )
            if total_idat_decompressed > 1_048_576:
                ratio = total_idat_decompressed / max(1, total_idat_compressed)
                if ratio > config.MAX_PNG_COMPRESSION_RATIO:
                    raise ContentValidationError(
                        413,
                        f"PNG decompression bomb detected: compression ratio {ratio:.1f}x exceeds limit",
                    )
        elif chunk_type == b"eXIf":
            exif_present = True
            metadata_flags.append("exif_present")
            instruction_flags.extend(_inspect_exif_blob(chunk_data))
        elif chunk_type == b"iCCP":
            icc_present = True
            metadata_flags.append("icc_present")
            nul_idx = chunk_data.find(b"\x00")
            if nul_idx <= 0 or nul_idx + 2 > len(chunk_data):
                raise ContentValidationError(415, "Malformed PNG iCCP chunk")
            profile_name = chunk_data[:nul_idx].decode("latin-1", errors="ignore")
            for hit in detect_instruction_strings(profile_name):
                instruction_flags.append(f"icc:{hit}")
            icc_bytes = _inflate_zlib_bounded(
                chunk_data[nul_idx + 2 :], config.MAX_ICC_BYTES, "PNG iCCP"
            )
            instruction_flags.extend(_validate_icc_profile(icc_bytes))
            metadata_flags.append("icc_valid")
        elif chunk_type in (b"tEXt", b"zTXt", b"iTXt"):
            _inspect_png_text_chunk(chunk_type, chunk_data, instruction_flags)
        elif chunk_type == b"IEND":
            seen_iend = True
            break
        else:
            # Ancillary or custom chunks: guard against hidden polyglots
            _check_polyglot_blob(chunk_data, context=f"png_chunk_{chunk_type.decode('latin-1', errors='replace')}")

    if not seen_ihdr or not seen_iend or not seen_idat:
        raise ContentValidationError(415, "Incomplete or malformed PNG container")

    try:
        flushed = idat_decomp.flush()
    except zlib.error as exc:
        raise ContentValidationError(400, f"Truncated PNG IDAT zlib stream: {exc}") from exc
    if total_idat_decompressed + len(flushed) > config.MAX_IMAGE_DECOMPRESSED_BYTES:
        raise ContentValidationError(413, "PNG decompression bomb detected during IDAT flush")

    trailing = content[pos:]
    if trailing:
        _check_polyglot_blob(trailing, context="png_post_iend", reject_pe=True)
        raise ContentValidationError(
            415, f"Polyglot/trailing payload rejected after PNG IEND ({len(trailing)} trailing bytes)"
        )

    return ImageInspectionResult(
        format_name="png",
        width=width,
        height=height,
        exif_present=exif_present,
        icc_present=icc_present,
        metadata_flags=sorted(set(metadata_flags)),
        instruction_flags=sorted(set(instruction_flags)),
    )


def _inspect_png_text_chunk(chunk_type: bytes, chunk_data: bytes, flags_out: List[str]) -> None:
    if len(chunk_data) > config.MAX_EXIF_BYTES:
        raise ContentValidationError(413, f"PNG {chunk_type.decode()} chunk exceeds metadata size limit")

    _check_polyglot_blob(chunk_data, context=f"png_{chunk_type.decode()}")
    text_value = ""
    if chunk_type == b"tEXt":
        text_value = chunk_data.replace(b"\x00", b" ").decode("utf-8", errors="ignore")
    elif chunk_type == b"zTXt":
        nul_idx = chunk_data.find(b"\x00")
        if nul_idx > 0 and nul_idx + 2 <= len(chunk_data):
            key = chunk_data[:nul_idx].decode("utf-8", errors="ignore")
            inflated = _inflate_zlib_bounded(
                chunk_data[nul_idx + 2 :], config.MAX_EXIF_BYTES, "PNG zTXt"
            )
            _check_polyglot_blob(inflated, context="png_zTXt_inflated")
            text_value = f"{key} {inflated.decode('utf-8', errors='ignore')}"
    elif chunk_type == b"iTXt":
        # keyword\0compression_flag compression_method lang\0 translated_kw\0 text
        parts = chunk_data.split(b"\x00", 1)
        if len(parts) == 2 and len(parts[1]) >= 2:
            comp_flag = parts[1][0]
            rest = parts[1][2:]
            subparts = rest.split(b"\x00", 2)
            body_raw = subparts[2] if len(subparts) == 3 else rest
            if comp_flag == 1:
                body_raw = _inflate_zlib_bounded(body_raw, config.MAX_EXIF_BYTES, "PNG iTXt")
                _check_polyglot_blob(body_raw, context="png_iTXt_inflated")
            text_value = f"{parts[0].decode('utf-8', errors='ignore')} {body_raw.decode('utf-8', errors='ignore')}"

    for hit in detect_instruction_strings(text_value):
        flags_out.append(f"png_text:{hit}")


def _inspect_jpeg(content: bytes) -> ImageInspectionResult:
    if len(content) < 4 or content[:2] != b"\xff\xd8":
        raise ContentValidationError(415, "Invalid JPEG SOI header")

    pos = 2
    width = 0
    height = 0
    seen_sof = False
    seen_eoi = False
    exif_present = False
    total_exif_bytes = 0
    icc_chunks: Dict[int, bytes] = {}
    icc_expected_count: Optional[int] = None
    metadata_flags: List[str] = []
    instruction_flags: List[str] = []

    while pos < len(content):
        if content[pos] != 0xFF:
            raise ContentValidationError(415, "Malformed JPEG marker alignment")
        while pos < len(content) and content[pos] == 0xFF:
            pos += 1
        if pos >= len(content):
            break
        marker = content[pos]
        pos += 1

        if marker == 0xD9:  # EOI
            seen_eoi = True
            break
        if marker in _JPEG_STANDALONE_MARKERS:
            continue

        if pos + 2 > len(content):
            raise ContentValidationError(400, "Truncated JPEG segment length")
        seg_len = struct.unpack(">H", content[pos : pos + 2])[0]
        if seg_len < 2 or pos + seg_len > len(content):
            raise ContentValidationError(400, "Malformed or truncated JPEG segment")
        seg_data = content[pos + 2 : pos + seg_len]
        pos += seg_len

        if marker in _JPEG_SOF_MARKERS:
            if len(seg_data) < 6:
                raise ContentValidationError(400, "Malformed JPEG SOF header")
            _, height, width, components = struct.unpack(">BHHB", seg_data[:6])
            _check_image_dimensions(width, height, channels=max(1, components), bit_depth=8)
            seen_sof = True
        elif marker == 0xE1:  # APP1 (EXIF / XMP)
            if seg_data.startswith(b"Exif\x00\x00"):
                exif_present = True
                if "exif_present" not in metadata_flags:
                    metadata_flags.append("exif_present")
                total_exif_bytes += len(seg_data)
                if total_exif_bytes > config.MAX_EXIF_BYTES:
                    raise ContentValidationError(
                        413, f"EXIF metadata exceeds {config.MAX_EXIF_BYTES} byte limit"
                    )
                instruction_flags.extend(_inspect_exif_blob(seg_data))
            elif seg_data.startswith(b"http://ns.adobe.com/xap/1.0/\x00"):
                total_exif_bytes += len(seg_data)
                if total_exif_bytes > config.MAX_EXIF_BYTES:
                    raise ContentValidationError(413, "XMP metadata exceeds size limit")
                _check_polyglot_blob(seg_data, context="jpeg_xmp")
                xmp_text = seg_data.decode("utf-8", errors="ignore")
                for hit in detect_instruction_strings(xmp_text):
                    instruction_flags.append(f"xmp:{hit}")
            else:
                _check_polyglot_blob(seg_data, context="jpeg_app1")
        elif marker == 0xE2:  # APP2 (ICC_PROFILE)
            if seg_data.startswith(b"ICC_PROFILE\x00"):
                if len(seg_data) < 14:
                    raise ContentValidationError(415, "Malformed JPEG ICC_PROFILE header")
                seq_no, num_markers = seg_data[12], seg_data[13]
                if seq_no == 0 or num_markers == 0 or seq_no > num_markers:
                    raise ContentValidationError(415, "Invalid JPEG ICC chunk sequence numbers")
                if icc_expected_count is not None and icc_expected_count != num_markers:
                    raise ContentValidationError(415, "Inconsistent JPEG ICC chunk count")
                icc_expected_count = num_markers
                icc_chunks[seq_no] = seg_data[14:]
                if sum(len(v) for v in icc_chunks.values()) > config.MAX_ICC_BYTES:
                    raise ContentValidationError(
                        413, f"ICC profile exceeds {config.MAX_ICC_BYTES} byte limit"
                    )
            else:
                _check_polyglot_blob(seg_data, context="jpeg_app2")
        elif marker == 0xFE:  # COM
            _check_polyglot_blob(seg_data, context="jpeg_comment")
            comment_text = seg_data.decode("utf-8", errors="ignore")
            for hit in detect_instruction_strings(comment_text):
                instruction_flags.append(f"comment:{hit}")
        elif 0xE0 <= marker <= 0xEF:
            _check_polyglot_blob(seg_data, context=f"jpeg_app_{marker:02x}")
        elif marker == 0xDA:  # SOS: scan until EOI or next non-RST marker
            while pos < len(content):
                if content[pos] != 0xFF:
                    pos += 1
                    continue
                if pos + 1 >= len(content):
                    break
                nxt = content[pos + 1]
                if nxt == 0x00 or (0xD0 <= nxt <= 0xD7):
                    pos += 2
                    continue
                if nxt == 0xFF:
                    pos += 1
                    continue
                # Reached next JPEG marker (e.g., EOI 0xD9 or another scan marker)
                break

    if not seen_sof or not seen_eoi:
        raise ContentValidationError(415, "Incomplete or malformed JPEG container")

    icc_present = bool(icc_chunks)
    if icc_chunks:
        metadata_flags.append("icc_present")
        if icc_expected_count is None or len(icc_chunks) != icc_expected_count:
            raise ContentValidationError(415, "Incomplete multi-chunk ICC profile")
        ordered = b"".join(icc_chunks[i] for i in range(1, icc_expected_count + 1))
        instruction_flags.extend(_validate_icc_profile(ordered))
        metadata_flags.append("icc_valid")

    trailing = content[pos:]
    if trailing:
        _check_polyglot_blob(trailing, context="jpeg_post_eoi", reject_pe=True)
        raise ContentValidationError(
            415, f"Polyglot/trailing payload rejected after JPEG EOI ({len(trailing)} trailing bytes)"
        )

    return ImageInspectionResult(
        format_name="jpeg",
        width=width,
        height=height,
        exif_present=exif_present,
        icc_present=icc_present,
        metadata_flags=sorted(set(metadata_flags)),
        instruction_flags=sorted(set(instruction_flags)),
    )


def inspect_image_bytes(
    content: bytes, expected_ext: Optional[str] = None
) -> ImageInspectionResult:
    """Validate image magic bytes, polyglot resistance, bounds, and EXIF/ICC metadata."""
    if not content:
        raise ContentValidationError(400, "Empty image upload")
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise ContentValidationError(
            413, f"File exceeds the {config.MAX_UPLOAD_BYTES} byte upload limit"
        )

    ext = (expected_ext or "").lower()
    if ext == ".png":
        if not _is_png(content):
            raise ContentValidationError(415, "Content does not match PNG magic signature")
        return _inspect_png(content)
    if ext in (".jpg", ".jpeg"):
        if not _is_jpeg(content):
            raise ContentValidationError(415, "Content does not match JPEG magic signature")
        return _inspect_jpeg(content)

    if _is_png(content):
        return _inspect_png(content)
    if _is_jpeg(content):
        return _inspect_jpeg(content)
    raise ContentValidationError(415, "Decoded payload does not match JPEG or PNG signatures")


def validate_and_normalize_text(raw_bytes: bytes) -> TextInspectionResult:
    """Validate UTF-8 text payload, strip control/zero-width chars, NFKC normalize, and flag injections."""
    if not raw_bytes:
        raise ContentValidationError(400, "Empty text payload")
    if len(raw_bytes) > config.MAX_UPLOAD_BYTES or len(raw_bytes) > config.MAX_TEXT_BYTES:
        limit = min(config.MAX_UPLOAD_BYTES, config.MAX_TEXT_BYTES)
        raise ContentValidationError(413, f"Text payload exceeds {limit} byte limit")

    if _is_png(raw_bytes) or _is_jpeg(raw_bytes) or raw_bytes.startswith(b"MZ"):
        raise ContentValidationError(415, "Binary file signature rejected for text upload")
    _check_polyglot_blob(raw_bytes[:2048], context="text_header", reject_pe=True)

    if b"\x00" in raw_bytes:
        raise ContentValidationError(415, "NUL byte rejected in text upload")

    try:
        decoded = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContentValidationError(415, f"Payload is not valid UTF-8 text: {exc}") from exc

    decoded = decoded.lstrip("\ufeff")
    if len(decoded) > config.MAX_TEXT_CHARS:
        raise ContentValidationError(
            413, f"Text length ({len(decoded)} chars) exceeds {config.MAX_TEXT_CHARS} char limit"
        )

    normalized, stripped_count, had_invisible = _strip_unicode_controls(
        decoded, preserve_newlines=True
    )
    if not normalized.strip():
        raise ContentValidationError(400, "Text payload contains no usable text after normalization")

    if len(normalized) > config.MAX_TEXT_CHARS:
        raise ContentValidationError(
            413, f"Normalized text length exceeds {config.MAX_TEXT_CHARS} char limit"
        )

    hits = detect_instruction_strings(normalized)
    return TextInspectionResult(
        normalized_text=normalized,
        normalized_bytes=normalized.encode("utf-8"),
        stripped_control_chars=stripped_count,
        had_invisible_unicode=had_invisible,
        instruction_flags=[f"prompt:{rule}" for rule in hits],
    )
