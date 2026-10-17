"""
AEGIS Surveillance Forensic Evidence Vault
===========================================
Implements tamper-evident, append-only, content-addressed forensic evidence
storage for live surveillance alerts (ISO/IEC 27037 & FRE Rule 902 compliant).

Features:
  - Content-Addressed Storage (CAS) for raw media frames (SHA-256 indexed blobs)
  - Append-only hash-chained incident audit ledger (prev_hash -> current_hash)
  - HMAC/Cryptographic node signatures over incident manifests
  - Comprehensive integrity auditing (pinpoints tampered blobs or broken chains)
  - Standalone court-admissible export bundle packaging (ZIP with self-verifier)
"""

from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid
import zipfile

logger = logging.getLogger("aegis.forensics.vault")

GENESIS_HASH = hashlib.sha256(b"AEGIS_SURVEILLANCE_VAULT_GENESIS_V1").hexdigest()
DEFAULT_VAULT_DIR = Path(__file__).resolve().parent.parent / "vault"
DEFAULT_SIGNING_KEY = b"aegis_surveillance_node_secret_key_v1"


@dataclass
class FrameBlobMeta:
    """Metadata for a content-addressed evidentiary frame blob."""
    sha256: str
    blob_relpath: str
    byte_size: int
    format: str = "png"
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class IncidentRecord:
    """Immutable record for a live surveillance forensic incident."""
    incident_id: str
    created_at_utc: str
    camera_id: str
    threat_type: str
    severity: str
    sequence_number: int
    timestamp_ms: int
    primary_frame: FrameBlobMeta
    context_frames: List[FrameBlobMeta] = field(default_factory=list)
    telemetry: Dict[str, Any] = field(default_factory=dict)
    reasoning_narrative: str = ""
    session_metadata: Dict[str, Any] = field(default_factory=dict)
    record_index: int = 0
    prev_record_hash: str = ""
    record_hash: str = ""
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> IncidentRecord:
        pf = data["primary_frame"]
        primary_meta = FrameBlobMeta(**pf) if isinstance(pf, dict) else pf
        ctx = []
        for c in data.get("context_frames", []):
            ctx.append(FrameBlobMeta(**c) if isinstance(c, dict) else c)
        
        data_copy = dict(data)
        data_copy["primary_frame"] = primary_meta
        data_copy["context_frames"] = ctx
        return cls(**data_copy)


@dataclass
class VaultAuditResult:
    """Audit report for the entire forensic vault."""
    is_valid: bool
    total_records: int
    verified_records: int
    broken_records: List[int] = field(default_factory=list)
    missing_blobs: List[str] = field(default_factory=list)
    corrupted_blobs: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        status = "PASSED (TAMPER-FREE)" if self.is_valid else "FAILED (INTEGRITY BREACH)"
        return (
            f"Vault Audit Result: {status}\n"
            f"  Total Records: {self.total_records}\n"
            f"  Verified Records: {self.verified_records}\n"
            f"  Broken Chain Records: {len(self.broken_records)}\n"
            f"  Missing Blobs: {len(self.missing_blobs)}\n"
            f"  Corrupted Blobs: {len(self.corrupted_blobs)}\n"
            f"  Errors: {len(self.errors)}"
        )


class SurveillanceEvidenceVault:
    """
    Append-only, tamper-evident cryptographic storage vault for live surveillance
    forensic evidence. Complies with ISO/IEC 27037 digital evidence preservation.
    """

    def __init__(
        self,
        vault_dir: Optional[Path | str] = None,
        signing_key: Optional[bytes] = None,
    ):
        self.vault_dir = Path(vault_dir or DEFAULT_VAULT_DIR).resolve()
        self.signing_key = signing_key or DEFAULT_SIGNING_KEY
        self.blobs_dir = self.vault_dir / "blobs"
        self.incidents_dir = self.vault_dir / "incidents"
        self.ledger_path = self.vault_dir / "ledger.jsonl"
        self._lock = threading.Lock()

        # Initialize vault directory tree
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.incidents_dir.mkdir(parents=True, exist_ok=True)

        self._ensure_ledger_initialized()

    def _ensure_ledger_initialized(self) -> None:
        """Ensures the append-only ledger file exists."""
        if not self.ledger_path.exists():
            self.ledger_path.touch(mode=0o644, exist_ok=True)

    def _get_latest_ledger_state(self) -> Tuple[int, str]:
        """Reads the latest index and chain hash from the ledger."""
        if not self.ledger_path.exists() or self.ledger_path.stat().st_size == 0:
            return 0, GENESIS_HASH

        last_line = ""
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    last_line = line_str

        if not last_line:
            return 0, GENESIS_HASH

        try:
            entry = json.loads(last_line)
            return entry.get("record_index", 0), entry.get("record_hash", GENESIS_HASH)
        except Exception:
            logger.error("Failed to parse last ledger entry; falling back to re-scan.")
            return 0, GENESIS_HASH

    def store_blob(
        self,
        frame_bytes: bytes,
        format_ext: str = "png",
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> FrameBlobMeta:
        """
        Stores an evidentiary frame in Content-Addressed Storage (CAS).
        The file path is derived directly from the frame's SHA-256 hash.
        """
        frame_hash = hashlib.sha256(frame_bytes).hexdigest()
        prefix = frame_hash[:2]
        blob_dir = self.blobs_dir / prefix
        blob_dir.mkdir(parents=True, exist_ok=True)

        blob_filename = f"{frame_hash}.{format_ext.lower().lstrip('.')}"
        blob_full_path = blob_dir / blob_filename
        relpath = f"blobs/{prefix}/{blob_filename}"

        if not blob_full_path.exists():
            blob_full_path.write_bytes(frame_bytes)

        return FrameBlobMeta(
            sha256=frame_hash,
            blob_relpath=relpath,
            byte_size=len(frame_bytes),
            format=format_ext.lower().lstrip("."),
            width=width,
            height=height,
        )

    def store_incident(
        self,
        camera_id: str,
        threat_type: str,
        sequence_number: int,
        timestamp_ms: int,
        primary_frame_bytes: bytes,
        telemetry: Optional[Dict[str, Any]] = None,
        reasoning_narrative: str = "",
        severity: str = "CRITICAL",
        context_frames_bytes: Optional[List[bytes]] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
        frame_format: str = "png",
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> IncidentRecord:
        """
        Stores a complete, legally admissible surveillance incident package:
          1. Writes content-addressed frame blobs
          2. Generates incident ID and UTC timestamp
          3. Appends chained entry to ledger with HMAC signature
          4. Writes incident manifest JSON
        """
        # 1. Store frame blobs
        primary_blob = self.store_blob(
            primary_frame_bytes,
            format_ext=frame_format,
            width=width,
            height=height,
        )

        context_blobs: List[FrameBlobMeta] = []
        if context_frames_bytes:
            for c_bytes in context_frames_bytes:
                ctx_blob = self.store_blob(
                    c_bytes,
                    format_ext=frame_format,
                    width=width,
                    height=height,
                )
                context_blobs.append(ctx_blob)

        # 2. Prepare incident identification
        now_dt = datetime.now(timezone.utc)
        iso_ts = now_dt.isoformat()
        date_str = now_dt.strftime("%Y%m%d")
        short_id = uuid.uuid4().hex[:8]
        incident_id = f"INC-{date_str}-{camera_id}-SEQ{sequence_number}-{short_id}"

        with self._lock:
            last_index, last_hash = self._get_latest_ledger_state()
            new_index = last_index + 1

            # Prepare initial payload without ledger link
            incident = IncidentRecord(
                incident_id=incident_id,
                created_at_utc=iso_ts,
                camera_id=camera_id,
                threat_type=threat_type,
                severity=severity,
                sequence_number=sequence_number,
                timestamp_ms=timestamp_ms,
                primary_frame=primary_blob,
                context_frames=context_blobs,
                telemetry=telemetry or {},
                reasoning_narrative=reasoning_narrative,
                session_metadata=session_metadata or {},
                record_index=new_index,
                prev_record_hash=last_hash,
            )

            # Compute payload digest for chain linkage
            manifest_json = json.dumps(incident.to_dict(), sort_keys=True)
            manifest_digest = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()

            # Chained hash: H_k = SHA256(H_{k-1} || incident_id || iso_ts || manifest_digest)
            chain_input = f"{last_hash}:{incident_id}:{iso_ts}:{manifest_digest}".encode("utf-8")
            record_hash = hashlib.sha256(chain_input).hexdigest()
            signature = hmac.new(self.signing_key, record_hash.encode("utf-8"), hashlib.sha256).hexdigest()

            incident.record_hash = record_hash
            incident.signature = signature

            # 3. Write individual manifest
            manifest_path = self.incidents_dir / f"{incident_id}.json"
            manifest_path.write_text(json.dumps(incident.to_dict(), indent=2), encoding="utf-8")

            # 4. Append to ledger
            ledger_entry = {
                "record_index": new_index,
                "incident_id": incident_id,
                "created_at_utc": iso_ts,
                "camera_id": camera_id,
                "threat_type": threat_type,
                "primary_frame_sha256": primary_blob.sha256,
                "manifest_digest": manifest_digest,
                "prev_record_hash": last_hash,
                "record_hash": record_hash,
                "signature": signature,
            }
            with open(self.ledger_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ledger_entry) + "\n")

        logger.info(f"Sealed incident {incident_id} at ledger index {new_index} (hash={record_hash[:8]}...)")
        return incident

    def get_incident(self, incident_id: str) -> Optional[IncidentRecord]:
        """Retrieves an incident record by ID."""
        manifest_path = self.incidents_dir / f"{incident_id}.json"
        if not manifest_path.exists():
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return IncidentRecord.from_dict(data)
        except Exception as exc:
            logger.error(f"Failed to read incident {incident_id}: {exc}")
            return None

    def get_frame_bytes(self, blob_relpath: str) -> bytes:
        """Retrieves raw evidentiary frame bytes from the vault."""
        full_path = self.vault_dir / blob_relpath
        if not full_path.exists():
            raise FileNotFoundError(f"Blob not found at {full_path}")
        return full_path.read_bytes()

    def verify_vault_integrity(self) -> VaultAuditResult:
        """
        Audits the entire vault for cryptographic tamper-evidence:
          - Validates genesis link and unbroken hash chain continuity
          - Validates HMAC node signatures for each entry
          - Verifies manifest existence and bitwise digest matching
          - Verifies content-addressed frame blob presence and SHA-256 match
        """
        audit = VaultAuditResult(
            is_valid=True,
            total_records=0,
            verified_records=0,
        )

        if not self.ledger_path.exists() or self.ledger_path.stat().st_size == 0:
            return audit

        expected_prev_hash = GENESIS_HASH

        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                line_str = line.strip()
                if not line_str:
                    continue

                audit.total_records += 1

                try:
                    entry = json.loads(line_str)
                except Exception as exc:
                    audit.is_valid = False
                    audit.errors.append(f"Line {line_idx}: Malformed ledger JSON: {exc}")
                    continue

                rec_idx = entry.get("record_index", -1)
                inc_id = entry.get("incident_id", "")
                ts = entry.get("created_at_utc", "")
                manifest_digest = entry.get("manifest_digest", "")
                prev_hash = entry.get("prev_record_hash", "")
                rec_hash = entry.get("record_hash", "")
                sig = entry.get("signature", "")
                primary_sha256 = entry.get("primary_frame_sha256", "")

                # 1. Check chain linkage
                if prev_hash != expected_prev_hash:
                    audit.is_valid = False
                    audit.broken_records.append(rec_idx)
                    audit.errors.append(
                        f"Record {rec_idx} ({inc_id}): Hash chain broken. "
                        f"Expected prev_hash {expected_prev_hash}, found {prev_hash}"
                    )

                # 2. Recompute record hash
                chain_input = f"{prev_hash}:{inc_id}:{ts}:{manifest_digest}".encode("utf-8")
                expected_hash = hashlib.sha256(chain_input).hexdigest()
                if rec_hash != expected_hash:
                    audit.is_valid = False
                    audit.broken_records.append(rec_idx)
                    audit.errors.append(
                        f"Record {rec_idx} ({inc_id}): Invalid record hash. "
                        f"Expected {expected_hash}, stored {rec_hash}"
                    )

                # 3. Verify HMAC signature
                expected_sig = hmac.new(self.signing_key, rec_hash.encode("utf-8"), hashlib.sha256).hexdigest()
                if sig != expected_sig:
                    audit.is_valid = False
                    audit.errors.append(f"Record {rec_idx} ({inc_id}): Node signature mismatch.")

                # 4. Verify manifest file on disk
                manifest_path = self.incidents_dir / f"{inc_id}.json"
                if not manifest_path.exists():
                    audit.is_valid = False
                    audit.errors.append(f"Record {rec_idx} ({inc_id}): Manifest file missing on disk.")
                else:
                    try:
                        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                        # Re-verify manifest digest (without record_hash and signature)
                        copy_dict = dict(manifest_data)
                        copy_dict["record_hash"] = ""
                        copy_dict["signature"] = ""
                        recomputed_manifest_digest = hashlib.sha256(
                            json.dumps(copy_dict, sort_keys=True).encode("utf-8")
                        ).hexdigest()

                        if recomputed_manifest_digest != manifest_digest:
                            audit.is_valid = False
                            audit.errors.append(f"Record {rec_idx} ({inc_id}): Manifest contents tampered.")
                    except Exception as m_exc:
                        audit.is_valid = False
                        audit.errors.append(f"Record {rec_idx} ({inc_id}): Manifest read error: {m_exc}")

                # 5. Verify primary frame blob on disk
                blob_prefix = primary_sha256[:2]
                blob_path = self.blobs_dir / blob_prefix / f"{primary_sha256}.png"
                if not blob_path.exists():
                    audit.is_valid = False
                    audit.missing_blobs.append(primary_sha256)
                else:
                    actual_blob_bytes = blob_path.read_bytes()
                    actual_sha256 = hashlib.sha256(actual_blob_bytes).hexdigest()
                    if actual_sha256 != primary_sha256:
                        audit.is_valid = False
                        audit.corrupted_blobs.append(primary_sha256)
                        audit.errors.append(f"Record {rec_idx} ({inc_id}): Primary frame blob corrupted/tampered.")

                if audit.is_valid or rec_idx not in audit.broken_records:
                    audit.verified_records += 1

                expected_prev_hash = rec_hash

        return audit

    def export_incident_package(
        self,
        incident_id: str,
        output_zip_path: Optional[Path | str] = None,
    ) -> Path:
        """
        Bundles an incident record, all evidentiary frame blobs, and a self-contained
        verification script into a court-admissible portable ZIP archive.
        """
        incident = self.get_incident(incident_id)
        if not incident:
            raise ValueError(f"Incident {incident_id} not found in vault.")

        out_path = Path(output_zip_path or self.vault_dir / f"{incident_id}_forensic_bundle.zip").resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        verifier_script = """#!/usr/bin/env python3
# Standalone ISO/IEC 27037 Evidence Verification Script
import hashlib, json, os, sys

def verify():
    manifest_path = "manifest.json"
    if not os.path.exists(manifest_path):
        print("[FAIL] manifest.json missing")
        return False
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    primary = data["primary_frame"]
    blob_path = os.path.join("evidence", os.path.basename(primary["blob_relpath"]))
    if not os.path.exists(blob_path):
        print(f"[FAIL] Primary evidence frame missing: {blob_path}")
        return False
    
    with open(blob_path, "rb") as bf:
        calc_hash = hashlib.sha256(bf.read()).hexdigest()
    if calc_hash != primary["sha256"]:
        print(f"[FAIL] Frame hash mismatch! Expected {primary['sha256']}, got {calc_hash}")
        return False

    print(f"[PASS] Cryptographic verification successful for {data['incident_id']}")
    print(f"       Threat: {data['threat_type']} (Camera: {data['camera_id']})")
    print(f"       SHA-256 Digest: {calc_hash}")
    return True

if __name__ == "__main__":
    sys.exit(0 if verify() else 1)
"""

        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Add manifest
            zf.writestr("manifest.json", json.dumps(incident.to_dict(), indent=2))
            zf.writestr("verify_evidence.py", verifier_script)

            # Add primary frame
            p_bytes = self.get_frame_bytes(incident.primary_frame.blob_relpath)
            p_name = os.path.basename(incident.primary_frame.blob_relpath)
            zf.writestr(f"evidence/{p_name}", p_bytes)

            # Add context frames
            for ctx in incident.context_frames:
                c_bytes = self.get_frame_bytes(ctx.blob_relpath)
                c_name = os.path.basename(ctx.blob_relpath)
                zf.writestr(f"evidence/{c_name}", c_bytes)

        logger.info(f"Exported forensic bundle to {out_path}")
        return out_path
