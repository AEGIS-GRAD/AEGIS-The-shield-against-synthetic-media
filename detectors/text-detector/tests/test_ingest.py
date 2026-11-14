"""Unit tests for base64 decoding, shared-volume path confinement, limits, and Unicode hygiene."""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from ingest import IngestionError, PathSecurityError, PayloadTooLargeError, ingest_payload
from conftest import b64


def test_ingest_base64_and_data_uri_roundtrip(shared_dir: Path):
    sample = "\ufeffHello\u200b\u202e world!\r\n\r\n\r\nFull-width ＡＢＣ."
    loaded = ingest_payload(b64(sample), shared_root=shared_dir)
    assert loaded.source_kind == "base64"
    # BOM and zero-width / bidi characters stripped; NFKC maps full-width letters
    assert loaded.stripped_control_chars == 2
    assert "ABC" in loaded.text
    assert "\u202e" not in loaded.text
    assert loaded.paragraph_count == 2

    data_uri = f"data:text/plain;charset=utf-8;base64,{b64('Valid sample text here.')}"
    loaded_uri = ingest_payload(data_uri, shared_root=shared_dir)
    assert loaded_uri.text == "Valid sample text here."


def test_ingest_confined_txt_and_md_files(shared_dir: Path):
    target = shared_dir / "nested" / "essay.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("First paragraph.\n\nSecond paragraph has words.", encoding="utf-8")

    res = ingest_payload(str(target), shared_root=shared_dir)
    assert res.source_kind == "filepath"
    assert res.word_count == 6
    assert res.paragraph_count == 2


def test_ingest_rejects_traversal_and_outside_paths(shared_dir: Path, tmp_path: Path):
    outside = tmp_path / "secret.txt"
    outside.write_text("do not read", encoding="utf-8")

    with pytest.raises(PathSecurityError) as exc:
        ingest_payload(str(outside), shared_root=shared_dir)
    assert exc.value.status_code == 400

    traversal = str(shared_dir / ".." / "secret.txt")
    with pytest.raises(PathSecurityError):
        ingest_payload(traversal, shared_root=shared_dir)

    with pytest.raises(PathSecurityError):
        ingest_payload("/etc/passwd", shared_root=shared_dir)

    with pytest.raises(PathSecurityError):
        ingest_payload(f"{shared_dir}/bad\x00.txt", shared_root=shared_dir)


def test_ingest_rejects_bad_extensions_missing_files_and_invalid_encoding(shared_dir: Path):
    video = shared_dir / "clip.mp4"
    video.write_bytes(b"fake")
    with pytest.raises(IngestionError) as exc_ext:
        ingest_payload(str(video), shared_root=shared_dir)
    assert exc_ext.value.status_code == 400

    with pytest.raises(IngestionError) as exc_missing:
        ingest_payload(str(shared_dir / "missing.txt"), shared_root=shared_dir)
    assert exc_missing.value.status_code == 404

    with pytest.raises(IngestionError):
        ingest_payload("not!valid!base64", shared_root=shared_dir)

    binary_b64 = base64.b64encode(b"\xff\xfe\xfa\xfb").decode("ascii")
    with pytest.raises(IngestionError):
        ingest_payload(binary_b64, shared_root=shared_dir)


def test_ingest_enforces_size_limits_and_empty_text(shared_dir: Path):
    oversized = b64("a " * 300)
    with pytest.raises(PayloadTooLargeError) as exc_big:
        ingest_payload(oversized, shared_root=shared_dir, max_chars=200)
    assert exc_big.value.status_code == 413

    with pytest.raises(IngestionError) as exc_empty:
        ingest_payload(b64("   \n\t\u200b  "), shared_root=shared_dir)
    assert exc_empty.value.status_code == 400

