"""
Tests for AEGIS Surveillance Forensic Evidence Vault
=====================================================
Validates ISO/IEC 27037 compliance, content-addressed blob storage,
append-only ledger chaining, tamper detection, and ZIP export.
"""

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
import pytest

from security.forensics.evidence_vault import (
    SurveillanceEvidenceVault,
    GENESIS_HASH,
)


@pytest.fixture
def temp_vault():
    temp_dir = tempfile.mkdtemp(prefix="aegis_test_vault_")
    vault = SurveillanceEvidenceVault(vault_dir=temp_dir)
    yield vault
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_vault_initialization(temp_vault):
    assert temp_vault.blobs_dir.exists()
    assert temp_vault.incidents_dir.exists()
    assert temp_vault.ledger_path.exists()
    # Ledger should be empty initially
    audit = temp_vault.verify_vault_integrity()
    assert audit.is_valid is True
    assert audit.total_records == 0


def test_store_and_retrieve_incident(temp_vault):
    dummy_frame = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRdummy_primary_frame_bytes_12345"
    ctx_frame = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRdummy_context_frame_bytes_67890"

    record = temp_vault.store_incident(
        camera_id="cam-north-01",
        threat_type="PRNU_SENSOR_MISMATCH",
        sequence_number=100,
        timestamp_ms=15000,
        primary_frame_bytes=dummy_frame,
        context_frames_bytes=[ctx_frame],
        telemetry={"prnu_pce": 14.2, "prnu_threshold": 50.0},
        reasoning_narrative="PRNU PCE dropped to 14.2 below enrolled 50.0 threshold.",
        severity="CRITICAL",
    )

    assert record.incident_id.startswith("INC-")
    assert record.camera_id == "cam-north-01"
    assert record.record_index == 1
    assert record.prev_record_hash == GENESIS_HASH
    assert record.record_hash != ""
    assert record.signature != ""

    # Check blob exists on disk
    retrieved_bytes = temp_vault.get_frame_bytes(record.primary_frame.blob_relpath)
    assert retrieved_bytes == dummy_frame

    # Check manifest retrieval
    fetched = temp_vault.get_incident(record.incident_id)
    assert fetched is not None
    assert fetched.incident_id == record.incident_id
    assert fetched.telemetry["prnu_pce"] == 14.2

    # Integrity audit must pass
    audit = temp_vault.verify_vault_integrity()
    assert audit.is_valid is True
    assert audit.total_records == 1
    assert audit.verified_records == 1


def test_multiple_incidents_hash_chain(temp_vault):
    rec1 = temp_vault.store_incident(
        camera_id="cam-01",
        threat_type="HASH_CHAIN_BREAK",
        sequence_number=10,
        timestamp_ms=3000,
        primary_frame_bytes=b"frame_1_data",
    )
    rec2 = temp_vault.store_incident(
        camera_id="cam-02",
        threat_type="SEQUENCE_ANOMALY",
        sequence_number=55,
        timestamp_ms=4500,
        primary_frame_bytes=b"frame_2_data",
    )
    rec3 = temp_vault.store_incident(
        camera_id="cam-01",
        threat_type="DEEPFAKE_ALERT",
        sequence_number=90,
        timestamp_ms=8000,
        primary_frame_bytes=b"frame_3_data",
    )

    assert rec1.record_index == 1
    assert rec1.prev_record_hash == GENESIS_HASH
    assert rec2.record_index == 2
    assert rec2.prev_record_hash == rec1.record_hash
    assert rec3.record_index == 3
    assert rec3.prev_record_hash == rec2.record_hash

    audit = temp_vault.verify_vault_integrity()
    assert audit.is_valid is True
    assert audit.total_records == 3
    assert audit.verified_records == 3


def test_tamper_detection_corrupted_blob(temp_vault):
    original_frame = b"legitimate_tamper_test_frame_123"
    rec = temp_vault.store_incident(
        camera_id="cam-01",
        threat_type="HASH_CHAIN_BREAK",
        sequence_number=42,
        timestamp_ms=1000,
        primary_frame_bytes=original_frame,
    )

    # Corrupt the stored frame blob by overwriting 1 byte on disk
    blob_path = temp_vault.vault_dir / rec.primary_frame.blob_relpath
    assert blob_path.exists()
    blob_path.write_bytes(b"tampered_frame_data_malicious_attacker")

    audit = temp_vault.verify_vault_integrity()
    assert audit.is_valid is False
    assert len(audit.corrupted_blobs) == 1
    assert rec.primary_frame.sha256 in audit.corrupted_blobs


def test_tamper_detection_modified_manifest(temp_vault):
    rec = temp_vault.store_incident(
        camera_id="cam-01",
        threat_type="HASH_CHAIN_BREAK",
        sequence_number=42,
        timestamp_ms=1000,
        primary_frame_bytes=b"clean_frame",
    )

    # Tamper with the manifest file JSON
    manifest_path = temp_vault.incidents_dir / f"{rec.incident_id}.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["threat_type"] = "BENIGN_MODIFIED_BY_ATTACKER"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    audit = temp_vault.verify_vault_integrity()
    assert audit.is_valid is False
    assert any("Manifest contents tampered" in err for err in audit.errors)


def test_tamper_detection_broken_chain(temp_vault):
    temp_vault.store_incident("cam-01", "ALERT1", 1, 100, b"frame1")
    temp_vault.store_incident("cam-01", "ALERT2", 2, 200, b"frame2")
    temp_vault.store_incident("cam-01", "ALERT3", 3, 300, b"frame3")

    # Tamper with the middle ledger entry's hash
    with open(temp_vault.ledger_path, "r", encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]

    # Corrupt record 2 hash
    lines[1]["record_hash"] = "0000000000000000000000000000000000000000000000000000000000000000"

    with open(temp_vault.ledger_path, "w", encoding="utf-8") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")

    audit = temp_vault.verify_vault_integrity()
    assert audit.is_valid is False
    assert 2 in audit.broken_records or 3 in audit.broken_records


def test_export_incident_package(temp_vault, tmp_path):
    primary = b"primary_export_test_frame_data"
    ctx = b"ctx_export_test_frame_data"
    rec = temp_vault.store_incident(
        camera_id="cam-gate-09",
        threat_type="PRNU_SENSOR_MISMATCH",
        sequence_number=105,
        timestamp_ms=25000,
        primary_frame_bytes=primary,
        context_frames_bytes=[ctx],
    )

    zip_target = tmp_path / "forensic_export.zip"
    exported_path = temp_vault.export_incident_package(rec.incident_id, zip_target)
    assert exported_path.exists()
    assert zipfile.is_zipfile(exported_path)

    with zipfile.ZipFile(exported_path, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "verify_evidence.py" in namelist
        # Verify frame is in evidence/
        assert any(n.startswith("evidence/") for n in namelist)
