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

import contextlib
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
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
import uuid
import zipfile

logger = logging.getLogger("aegis.forensics.vault")

GENESIS_HASH = hashlib.sha256(b"AEGIS_SURVEILLANCE_VAULT_GENESIS_V1").hexdigest()
DEFAULT_VAULT_DIR = Path(__file__).resolve().parent.parent / "vault"
# Legacy HMAC integrity key. It is public (committed to the repo), so it only
# detects accidental corruption, never deliberate tampering. Authenticity comes
# from Ed25519 seals (sealing.py). Override with AEGIS_VAULT_SIGNING_KEY.
DEFAULT_SIGNING_KEY = b"aegis_surveillance_node_secret_key_v1"


def _resolve_hmac_key(explicit: Optional[bytes]) -> bytes:
    if explicit:
        return explicit
    env_key = os.environ.get("AEGIS_VAULT_SIGNING_KEY")
    if env_key:
        return env_key.encode("utf-8")
    return DEFAULT_SIGNING_KEY


def _write_new_manifest(path: Path, data: Dict[str, Any]) -> None:
    """Append-only manifest write: refuses to overwrite an existing record."""
    with open(path, "x", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=2))


@contextlib.contextmanager
def _interprocess_lock(lock_path: Path) -> Iterator[None]:
    """Exclusive lock shared by every vault instance and process on this vault_dir.

    Without it, two writers (e.g. the ingestion gateway and the alert router,
    which each open their own vault instance) can read the same ledger head and
    append two records with the same ``prev_record_hash``, forking the chain.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    continue
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


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
class VerificationRecord:
    """Immutable record for a file-based or multimodal forensic verification."""
    verification_id: str
    job_id: str
    created_at_utc: str
    modality: str  # video | audio | image | text | multimodal
    input_filename: str
    input_hash: str
    input_blob: FrameBlobMeta
    verdict: str
    calibrated_score: float
    siem_alert_tier: str
    detector_outputs: List[Dict[str, Any]] = field(default_factory=list)
    model_versions: Dict[str, str] = field(default_factory=dict)
    calibration_version: str = "aegis-calibrator-v1.0"
    judge_transcript: Dict[str, Any] = field(default_factory=dict)
    # SHA-256 of the weight files that produced the detector outputs. A version
    # string alone does not prove which weights ran (they can be swapped on disk).
    model_fingerprints: Dict[str, str] = field(default_factory=dict)
    record_index: int = 0
    prev_record_hash: str = ""
    record_hash: str = ""
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VerificationRecord:
        ib = data["input_blob"]
        blob_meta = FrameBlobMeta(**ib) if isinstance(ib, dict) else ib
        data_copy = dict(data)
        data_copy["input_blob"] = blob_meta
        return cls(**data_copy)


@dataclass
class MCPAuditRecord:
    """Immutable, hash-chained audit record for an MCP server tool invocation."""
    audit_id: str
    record_index: int
    created_at_utc: str
    tool_name: str
    principal_id: str
    scopes: List[str]
    status: str  # ok | pending | completed | error | denied | rate_limited
    args_sha256: str
    result_sha256: str
    security_flags: List[str] = field(default_factory=list)
    error_code: Optional[str] = None
    latency_ms: float = 0.0
    payload_blob: Optional[FrameBlobMeta] = None
    prev_record_hash: str = ""
    record_hash: str = ""
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MCPAuditRecord:
        data_copy = dict(data)
        pb = data_copy.get("payload_blob")
        if isinstance(pb, dict):
            data_copy["payload_blob"] = FrameBlobMeta(**pb)
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
    sealed_records: int = 0
    unsealed_records: int = 0
    checkpoints_verified: int = 0
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        status = "PASSED (TAMPER-FREE)" if self.is_valid else "FAILED (INTEGRITY BREACH)"
        return (
            f"Vault Audit Result: {status}\n"
            f"  Total Records: {self.total_records}\n"
            f"  Verified Records: {self.verified_records}\n"
            f"  Sealed / Unsealed Records: {self.sealed_records} / {self.unsealed_records}\n"
            f"  Checkpoints Verified: {self.checkpoints_verified}\n"
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
        sealer: Optional[Any] = None,
    ):
        """
        Args:
            vault_dir: Vault root directory.
            signing_key: Legacy HMAC key (integrity only; see DEFAULT_SIGNING_KEY).
            sealer: Optional ``sealing.EvidenceSealer``. When set, every record and
                checkpoint gets an Ed25519 seal with an RFC 3161 timestamp.
        """
        self.vault_dir = Path(vault_dir or DEFAULT_VAULT_DIR).resolve()
        self.signing_key = _resolve_hmac_key(signing_key)
        if sealer is None and os.environ.get("AEGIS_VAULT_KEYRING_DIR"):
            from .sealing import sealer_from_env

            sealer = sealer_from_env()
        self.sealer = sealer
        self.blobs_dir = self.vault_dir / "blobs"
        self.incidents_dir = self.vault_dir / "incidents"
        self.verifications_dir = self.vault_dir / "verifications"
        self.mcp_audits_dir = self.vault_dir / "mcp_audits"
        self.ledger_path = self.vault_dir / "ledger.jsonl"
        self.checkpoints_path = self.vault_dir / "checkpoints.jsonl"
        self.lock_path = self.vault_dir / "ledger.lock"
        self._lock = threading.Lock()

        # Initialize vault directory tree
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.incidents_dir.mkdir(parents=True, exist_ok=True)
        self.verifications_dir.mkdir(parents=True, exist_ok=True)
        self.mcp_audits_dir.mkdir(parents=True, exist_ok=True)

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

        with self._lock, _interprocess_lock(self.lock_path):
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
            _write_new_manifest(manifest_path, incident.to_dict())

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
            if self.sealer is not None:
                ledger_entry["seal"] = self.sealer.seal(incident_id, record_hash)
            with open(self.ledger_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ledger_entry) + "\n")

        logger.info(f"Sealed incident {incident_id} at ledger index {new_index} (hash={record_hash[:8]}...)")
        return incident

    def store_verification(
        self,
        job_id: str,
        modality: str,
        input_filename: str,
        input_bytes: bytes,
        verdict: str,
        calibrated_score: float,
        detector_outputs: List[Dict[str, Any]],
        model_versions: Dict[str, str],
        calibration_version: str = "aegis-calibrator-v1.0",
        judge_transcript: Optional[Dict[str, Any]] = None,
        siem_alert_tier: str = "P4_INFORMATIONAL",
        model_fingerprints: Optional[Dict[str, str]] = None,
    ) -> VerificationRecord:
        """
        Stores a complete, tamper-evident verification record for any modality
        (video, audio, image, text, multimodal) including input hash, detector outputs,
        model versions, calibration version, and full judge debate transcript.
        """
        ext = os.path.splitext(input_filename)[1].lstrip(".").lower() or "bin"
        input_blob = self.store_blob(input_bytes, format_ext=ext)
        input_hash = input_blob.sha256

        now_dt = datetime.now(timezone.utc)
        iso_ts = now_dt.isoformat()
        date_str = now_dt.strftime("%Y%m%d")
        # Random suffix: date + modality + job prefix alone collides when the same job
        # is verified twice in a day, and the second write used to overwrite the first
        # record's manifest (silently breaking the append-only guarantee).
        verification_id = f"VER-{date_str}-{modality.lower()}-{job_id[:8]}-{uuid.uuid4().hex[:8]}"

        with self._lock, _interprocess_lock(self.lock_path):
            last_index, last_hash = self._get_latest_ledger_state()
            new_index = last_index + 1

            record = VerificationRecord(
                verification_id=verification_id,
                job_id=job_id,
                created_at_utc=iso_ts,
                modality=modality.lower(),
                input_filename=input_filename,
                input_hash=input_hash,
                input_blob=input_blob,
                verdict=verdict,
                calibrated_score=float(calibrated_score),
                siem_alert_tier=siem_alert_tier,
                detector_outputs=detector_outputs,
                model_versions=model_versions,
                calibration_version=calibration_version,
                judge_transcript=judge_transcript or {},
                model_fingerprints=dict(model_fingerprints or {}),
                record_index=new_index,
                prev_record_hash=last_hash,
            )

            manifest_json = json.dumps(record.to_dict(), sort_keys=True)
            manifest_digest = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()

            chain_input = f"{last_hash}:{verification_id}:{iso_ts}:{manifest_digest}".encode("utf-8")
            record_hash = hashlib.sha256(chain_input).hexdigest()
            signature = hmac.new(self.signing_key, record_hash.encode("utf-8"), hashlib.sha256).hexdigest()

            record.record_hash = record_hash
            record.signature = signature

            manifest_path = self.verifications_dir / f"{verification_id}.json"
            _write_new_manifest(manifest_path, record.to_dict())

            ledger_entry = {
                "record_index": new_index,
                "record_type": "VERIFICATION",
                "incident_id": verification_id,
                "job_id": job_id,
                "modality": modality.lower(),
                "created_at_utc": iso_ts,
                "primary_frame_sha256": input_hash,
                "blob_relpath": input_blob.blob_relpath,
                "manifest_digest": manifest_digest,
                "prev_record_hash": last_hash,
                "record_hash": record_hash,
                "signature": signature,
            }
            if self.sealer is not None:
                ledger_entry["seal"] = self.sealer.seal(verification_id, record_hash)
            with open(self.ledger_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ledger_entry) + "\n")

        logger.info(f"Sealed verification {verification_id} ({modality}) at ledger index {new_index} (hash={record_hash[:8]}...)")
        return record

    def get_verification(self, verification_id: str) -> Optional[VerificationRecord]:
        """Retrieves a verification record by verification_id."""
        manifest_path = self.verifications_dir / f"{verification_id}.json"
        if not manifest_path.exists():
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return VerificationRecord.from_dict(data)
        except Exception as exc:
            logger.error(f"Failed to read verification {verification_id}: {exc}")
            return None

    def get_verification_by_job_id(self, job_id: str) -> Optional[VerificationRecord]:
        """Finds a verification record matching a given orchestrator job_id."""
        if not self.verifications_dir.exists():
            return None
        for path in self.verifications_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("job_id") == job_id or data.get("verification_id") == job_id:
                    return VerificationRecord.from_dict(data)
            except Exception:
                continue
        return None

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

    def store_mcp_audit(
        self,
        tool_name: str,
        principal_id: str,
        scopes: List[str],
        status: str,
        args_sha256: str,
        result_sha256: str,
        sanitized_args: Optional[Dict[str, Any]] = None,
        security_flags: Optional[List[str]] = None,
        error_code: Optional[str] = None,
        latency_ms: float = 0.0,
    ) -> MCPAuditRecord:
        """
        Records an immutable, tamper-evident MCP tool call audit entry in the vault ledger.
        """
        now_dt = datetime.now(timezone.utc)
        iso_ts = now_dt.isoformat()
        audit_id = f"MCP-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

        payload_obj = {
            "audit_id": audit_id,
            "created_at_utc": iso_ts,
            "tool_name": tool_name,
            "principal_id": principal_id,
            "scopes": sorted(set(scopes)),
            "status": status,
            "args_sha256": args_sha256,
            "result_sha256": result_sha256,
            "sanitized_args": sanitized_args or {},
            "security_flags": list(security_flags or []),
            "error_code": error_code,
            "latency_ms": round(float(latency_ms), 3),
        }
        payload_bytes = json.dumps(payload_obj, sort_keys=True, default=str).encode("utf-8")
        payload_blob = self.store_blob(payload_bytes, format_ext="json")

        with self._lock:
            last_index, last_hash = self._get_latest_ledger_state()
            new_index = last_index + 1

            record = MCPAuditRecord(
                audit_id=audit_id,
                record_index=new_index,
                created_at_utc=iso_ts,
                tool_name=tool_name,
                principal_id=principal_id,
                scopes=sorted(set(scopes)),
                status=status,
                args_sha256=args_sha256,
                result_sha256=result_sha256,
                security_flags=list(security_flags or []),
                error_code=error_code,
                latency_ms=round(float(latency_ms), 3),
                payload_blob=payload_blob,
                prev_record_hash=last_hash,
            )

            manifest_json = json.dumps(record.to_dict(), sort_keys=True)
            manifest_digest = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()

            chain_input = f"{last_hash}:{audit_id}:{iso_ts}:{manifest_digest}".encode("utf-8")
            record_hash = hashlib.sha256(chain_input).hexdigest()
            signature = hmac.new(self.signing_key, record_hash.encode("utf-8"), hashlib.sha256).hexdigest()

            record.record_hash = record_hash
            record.signature = signature

            manifest_path = self.mcp_audits_dir / f"{audit_id}.json"
            manifest_path.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")

            ledger_entry = {
                "record_index": new_index,
                "record_type": "MCP_AUDIT",
                "incident_id": audit_id,
                "tool_name": tool_name,
                "principal_id": principal_id,
                "status": status,
                "created_at_utc": iso_ts,
                "primary_frame_sha256": payload_blob.sha256,
                "blob_relpath": payload_blob.blob_relpath,
                "manifest_digest": manifest_digest,
                "prev_record_hash": last_hash,
                "record_hash": record_hash,
                "signature": signature,
            }
            with open(self.ledger_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ledger_entry) + "\n")

        return record

    def get_mcp_audit(self, audit_id: str) -> Optional[MCPAuditRecord]:
        """Retrieves an MCP audit record by audit_id."""
        manifest_path = self.mcp_audits_dir / f"{audit_id}.json"
        if not manifest_path.exists():
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return MCPAuditRecord.from_dict(data)
        except Exception as exc:
            logger.error(f"Failed to read MCP audit {audit_id}: {exc}")
            return None

    def list_mcp_audits(self) -> List[MCPAuditRecord]:
        """Returns all MCP audit records ordered by record_index."""
        if not self.mcp_audits_dir.exists():
            return []
        records: List[MCPAuditRecord] = []
        for path in self.mcp_audits_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                records.append(MCPAuditRecord.from_dict(data))
            except Exception:
                continue
        records.sort(key=lambda r: r.record_index)
        return records

    def get_frame_bytes(self, blob_relpath: str) -> bytes:
        """Retrieves raw evidentiary frame bytes from the vault."""
        full_path = self.vault_dir / blob_relpath
        if not full_path.exists():
            raise FileNotFoundError(f"Blob not found at {full_path}")
        return full_path.read_bytes()

    def verify_vault_integrity(
        self,
        trusted_keys: Optional[Any] = None,
        tsa_trust: Optional[Sequence[Any]] = None,
        checkpoints: Optional[List[Dict[str, Any]]] = None,
        require_seals: Optional[bool] = None,
        max_clock_skew_s: float = 120.0,
    ) -> VaultAuditResult:
        """
        Audits the entire vault for cryptographic tamper-evidence:
          - Validates genesis link and unbroken hash chain continuity
          - Validates HMAC node signatures for each entry (legacy integrity check)
          - Verifies manifest existence and bitwise digest matching
          - Verifies content-addressed frame blob presence and SHA-256 match
          - (trusted_keys) Verifies each record's Ed25519 seal and RFC 3161 time,
            and flags records whose claimed time disagrees with the trusted time
          - (checkpoints) Detects tail truncation or rewriting against signed
            ledger checkpoints that were published outside the vault

        Args:
            trusted_keys: ``keyring.TrustedKeys`` (public keyring) — enables seal checks.
            tsa_trust: Trusted TSA certificates for RFC 3161 tokens.
            checkpoints: Externally retained checkpoints (e.g. from the SIEM). Defaults
                to none; the local ``checkpoints.jsonl`` can be truncated by the same
                attacker who truncates the ledger, so pass the external copy.
            require_seals: Fail unsealed records (default: True when trusted_keys given).
        """
        audit = VaultAuditResult(
            is_valid=True,
            total_records=0,
            verified_records=0,
        )
        if require_seals is None:
            require_seals = trusted_keys is not None
        heads: List[Tuple[str, str]] = []  # (record_hash, record_id) by ledger position

        if not self.ledger_path.exists() or self.ledger_path.stat().st_size == 0:
            self._verify_checkpoints(audit, heads, checkpoints, trusted_keys, tsa_trust)
            return audit

        expected_prev_hash = GENESIS_HASH

        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                line_str = line.strip()
                if not line_str:
                    continue

                audit.total_records += 1
                errors_before = len(audit.errors) + len(audit.missing_blobs)

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

                # 3b. Ed25519 seal + trusted timestamp (authenticity, non-repudiation)
                seal = entry.get("seal")
                if seal:
                    audit.sealed_records += 1
                else:
                    audit.unsealed_records += 1
                if trusted_keys is not None and (seal or require_seals):
                    from .sealing import verify_record_seal

                    chk = verify_record_seal(
                        seal, inc_id, rec_hash, trusted_keys,
                        tsa_trust=tsa_trust, require_timestamp=bool(tsa_trust),
                        claimed_time=ts, max_clock_skew_s=max_clock_skew_s,
                    )
                    if not chk.ok:
                        audit.is_valid = False
                        audit.errors.append(f"Record {rec_idx} ({inc_id}): Seal verification failed: {chk.reason}")
                    elif chk.warnings:
                        audit.warnings.extend(f"Record {rec_idx} ({inc_id}): {w}" for w in chk.warnings)

                # 4. Verify manifest file on disk (supports INCIDENT, VERIFICATION, and MCP_AUDIT records)
                rec_type = entry.get("record_type", "INCIDENT")
                if rec_type == "VERIFICATION":
                    manifest_path = self.verifications_dir / f"{inc_id}.json"
                elif rec_type == "MCP_AUDIT":
                    manifest_path = self.mcp_audits_dir / f"{inc_id}.json"
                else:
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

                # 5. Verify primary payload/frame blob on disk
                blob_rel = entry.get("blob_relpath")
                if blob_rel:
                    blob_path = self.vault_dir / blob_rel
                else:
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

                if len(audit.errors) + len(audit.missing_blobs) == errors_before:
                    audit.verified_records += 1

                heads.append((rec_hash, inc_id))
                expected_prev_hash = rec_hash

        self._verify_checkpoints(audit, heads, checkpoints, trusted_keys, tsa_trust)
        return audit

    # ── Signed ledger checkpoints (truncation / rewrite detection) ─────────────
    def _read_ledger_entries(self) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        if self.ledger_path.exists():
            with open(self.ledger_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            entries.append({})
        return entries

    def get_ledger_entry(self, record_id: str) -> Optional[Dict[str, Any]]:
        for entry in self._read_ledger_entries():
            if entry.get("incident_id") == record_id:
                return entry
        return None

    def create_checkpoint(self) -> Dict[str, Any]:
        """Commits to the current ledger head (size + head hash), sealed and timestamped.

        Publish the returned checkpoint outside the vault host (SIEM, write-once
        storage, a witness log, or a newspaper-of-record style transparency log).
        An attacker who deletes records from the end of the ledger cannot also
        delete the copies the verifier already holds.
        """
        with self._lock, _interprocess_lock(self.lock_path):
            entries = self._read_ledger_entries()
            head = entries[-1] if entries else {}
            cp: Dict[str, Any] = {
                "v": 1,
                "ledger_size": len(entries),
                "head_record_id": head.get("incident_id", ""),
                "head_hash": head.get("record_hash", GENESIS_HASH),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            if self.sealer is not None:
                cp["seal"] = self.sealer.seal_checkpoint(cp["ledger_size"], cp["head_hash"], cp["head_record_id"])
            with open(self.checkpoints_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(cp) + "\n")
        return cp

    def load_checkpoints(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if self.checkpoints_path.exists():
            for line in self.checkpoints_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out

    def _verify_checkpoints(self, audit: VaultAuditResult, heads: List[Tuple[str, str]],
                            checkpoints: Optional[List[Dict[str, Any]]], trusted_keys, tsa_trust) -> None:
        for cp in checkpoints or []:
            size = int(cp.get("ledger_size", 0))
            if trusted_keys is not None:
                from .sealing import verify_checkpoint_seal

                chk = verify_checkpoint_seal(cp, trusted_keys, tsa_trust=tsa_trust, require_timestamp=bool(tsa_trust))
                if not chk.ok:
                    audit.is_valid = False
                    audit.errors.append(f"Checkpoint @{size}: seal invalid: {chk.reason}")
                    continue
            if size == 0:
                audit.checkpoints_verified += 1
                continue
            if size > len(heads):
                audit.is_valid = False
                audit.errors.append(
                    f"Ledger truncated: checkpoint attests {size} records "
                    f"(head {cp.get('head_record_id')}) but only {len(heads)} remain."
                )
            elif heads[size - 1] != (cp.get("head_hash"), cp.get("head_record_id")):
                audit.is_valid = False
                audit.errors.append(
                    f"Ledger rewritten: record #{size} no longer matches the checkpointed head "
                    f"{cp.get('head_record_id')} ({str(cp.get('head_hash'))[:12]}...)."
                )
            else:
                audit.checkpoints_verified += 1

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

    def _build_forensic_report_md(self, record: Any) -> str:
        """Generates a human-readable, court-admissible Markdown forensic report."""
        if isinstance(record, VerificationRecord):
            lines = [
                f"# AEGIS Forensic Verification Report",
                f"",
                f"- **Verification ID:** `{record.verification_id}`",
                f"- **Job ID:** `{record.job_id}`",
                f"- **Timestamp (UTC):** {record.created_at_utc}",
                f"- **Modality:** `{record.modality}`",
                f"- **Input Filename:** `{record.input_filename}`",
                f"- **Input SHA-256:** `{record.input_hash}`",
                f"- **Final Verdict:** **{record.verdict}**",
                f"- **Calibrated Score:** {record.calibrated_score:.4f}",
                f"- **Calibration Version:** `{record.calibration_version}`",
                f"- **SIEM Alert Tier:** `{record.siem_alert_tier}`",
                f"",
                f"## Model Versions",
            ]
            for det, ver in record.model_versions.items():
                lines.append(f"- `{det}`: `{ver}`")
            lines.extend(["", "## Detector Outputs"])
            for out in record.detector_outputs:
                lines.append(
                    f"- **{out.get('detector')}** (`{out.get('status')}`): "
                    f"score={out.get('raw_score')}, confidence={out.get('confidence')}, "
                    f"latency={out.get('latency_ms')}ms"
                )
            lines.extend([
                "",
                "## Judge Agent Debate Transcript",
                f"- **Judge Mode:** `{record.judge_transcript.get('judge_mode', 'unknown')}`",
                f"- **Debate Transcript Hash:** `{record.judge_transcript.get('debate_transcript_hash', '')}`",
                f"- **Guards Applied:** `{', '.join(record.judge_transcript.get('guards_applied', [])) or 'none'}`",
                f"- **Forensic Justification:** {record.judge_transcript.get('forensic_justification', '')}",
                "",
            ])
            for rnd in record.judge_transcript.get("rounds", []):
                lines.append(f"### Round {rnd.get('round_number')}: {rnd.get('round_name')}")
                lines.append(f"{rnd.get('summary')}")
                lines.append("")
            lines.extend([
                "## Cryptographic Chain of Custody",
                f"- **Ledger Index:** {record.record_index}",
                f"- **Previous Record Hash:** `{record.prev_record_hash}`",
                f"- **Record Hash:** `{record.record_hash}`",
                f"- **HMAC-SHA256 Signature:** `{record.signature}`",
            ])
            return "\n".join(lines) + "\n"
        else:
            # IncidentRecord (Live Surveillance)
            lines = [
                f"# AEGIS Live Surveillance Incident Report",
                f"",
                f"- **Incident ID:** `{record.incident_id}`",
                f"- **Timestamp (UTC):** {record.created_at_utc}",
                f"- **Camera ID:** `{record.camera_id}`",
                f"- **Threat Type:** `{record.threat_type}`",
                f"- **Severity:** `{record.severity}`",
                f"- **Sequence Number:** {record.sequence_number}",
                f"- **Primary Frame SHA-256:** `{record.primary_frame.sha256}`",
                f"- **Reasoning Narrative:** {record.reasoning_narrative}",
                f"",
                f"## Cryptographic Chain of Custody",
                f"- **Ledger Index:** {record.record_index}",
                f"- **Previous Record Hash:** `{record.prev_record_hash}`",
                f"- **Record Hash:** `{record.record_hash}`",
                f"- **HMAC-SHA256 Signature:** `{record.signature}`",
            ]
            return "\n".join(lines) + "\n"

    def export_signed_bundle(
        self,
        record_id: str,
        output_zip_path: Optional[Path | str] = None,
    ) -> Path:
        """
        Exports a complete, signed, offline-verifiable forensic evidence bundle (ZIP)
        for any verification (all 5 modalities) or live surveillance incident.

        Bundle contents:
          - report.md: Court-admissible forensic report
          - evidence.json: Full JSON manifest (input_hash, detector_outputs, model_versions,
                           calibration_version, full judge_transcript, ledger chain & signature)
          - payload/<blob_filename>: Original raw content-addressed input file/frame
          - hashes.sha256: SHA-256 checksums for report.md, evidence.json, and payload
          - bundle_signature.sig: HMAC-SHA256 cryptographic signature over hashes.sha256 and evidence.json
          - verify_bundle.py: Embedded standalone offline verification script
        """
        record: Any = self.get_verification(record_id) or self.get_verification_by_job_id(record_id)
        if record is None:
            record = self.get_incident(record_id)
        if record is None:
            raise ValueError(f"Record '{record_id}' not found in forensic vault.")

        if isinstance(record, VerificationRecord):
            canonical_id = record.verification_id
            blob_meta = record.input_blob
        else:
            canonical_id = record.incident_id
            blob_meta = record.primary_frame

        out_path = Path(output_zip_path or self.vault_dir / f"{canonical_id}_signed_bundle.zip").resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        report_md = self._build_forensic_report_md(record)
        evidence_json_str = json.dumps(record.to_dict(), indent=2, sort_keys=True)
        payload_bytes = self.get_frame_bytes(blob_meta.blob_relpath)
        payload_rel = f"payload/{os.path.basename(blob_meta.blob_relpath)}"

        report_sha = hashlib.sha256(report_md.encode("utf-8")).hexdigest()
        evidence_sha = hashlib.sha256(evidence_json_str.encode("utf-8")).hexdigest()
        payload_sha = hashlib.sha256(payload_bytes).hexdigest()

        hashes_txt = (
            f"{evidence_sha}  evidence.json\n"
            f"{report_sha}  report.md\n"
            f"{payload_sha}  {payload_rel}\n"
        )
        hashes_sha = hashlib.sha256(hashes_txt.encode("utf-8")).hexdigest()

        sig_payload = f"{hashes_sha}:{evidence_sha}".encode("utf-8")
        bundle_sig = hmac.new(self.signing_key, sig_payload, hashlib.sha256).hexdigest()
        sig_doc = json.dumps(
            {
                "algorithm": "HMAC-SHA256",
                "record_id": canonical_id,
                "hashes_sha256": hashes_sha,
                "evidence_sha256": evidence_sha,
                "signature": bundle_sig,
            },
            indent=2,
        )

        verify_script_path = Path(__file__).resolve().parent / "verify_bundle.py"
        if verify_script_path.exists():
            verifier_code = verify_script_path.read_text(encoding="utf-8")
        else:
            verifier_code = "# See security/forensics/verify_bundle.py\n"

        ledger_entry = self.get_ledger_entry(canonical_id) or {}
        seal = ledger_entry.get("seal")
        checkpoint = self.create_checkpoint() if self.sealer is not None else None

        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("report.md", report_md)
            zf.writestr("evidence.json", evidence_json_str)
            zf.writestr("hashes.sha256", hashes_txt)
            zf.writestr("bundle_signature.sig", sig_doc)
            zf.writestr(payload_rel, payload_bytes)
            zf.writestr("verify_bundle.py", verifier_code)
            # Ed25519 seal (+ RFC 3161 token) over this record; self-authenticating,
            # verified against the published trusted keyring, not anything in the bundle.
            if seal:
                zf.writestr("seal.json", json.dumps(
                    {"record_id": canonical_id, "record_hash": record.record_hash, "seal": seal}, indent=2))
            if checkpoint is not None:
                zf.writestr("checkpoint.json", json.dumps(checkpoint, indent=2))

        logger.info(f"Exported signed offline-verifiable bundle to {out_path}")
        return out_path


UnifiedEvidenceVault = SurveillanceEvidenceVault
