# AEGIS Finalized Forensic Evidence Storage Schema
**Covers Both File-Based Media Evaluation and Real-Time Surveillance Streams**

- **Document Version:** 2.0.0 (Finalized)
- **Status:** Approved Unified Specification (Month 2 — Task 2 Deliverable)
- **Domain:** Digital Forensics, Cryptographic Chain of Custody, Legal Admissibility
- **Supersedes:** Month 1 `flight_recorder.db` schema and Week 3 `forensic_storage_design.md`
- **Compliance:** ISO/IEC 27037:2012, NIST SP 800-61 Rev. 2, Federal Rules of Evidence (FRE) Rule 902(13)/(14)

---

## 1. Executive Summary & Design Unification

AEGIS processes synthetic media and deepfake threats across two distinct operational pathways:
1. **Path A — File-Based Media Verification:** Static media files (video/audio/image) submitted via the web gateway for deep multi-detector analysis, governed by the LLM planner and 3-round Judge Agent arbitration protocol.
2. **Path B — Real-Time Surveillance Stream Verification:** Continuous high-throughput RTSP/WebRTC feeds (25–30 FPS) protected by mutual TLS (mTLS), validated against rolling SHA-256 frame hash-chains, PRNU sensor fingerprinting, and temporal sliding-window deepfake detectors.

Previously, Month 1 utilized an operational SQLite database (`orchestrator/app/flight_recorder.db`) focused on detector telemetry and job logging, while Week 3 designed an append-only Content-Addressed Storage (CAS) vault (`SurveillanceEvidenceVault`) for live surveillance alerts.

This specification unifies both designs into a single, **finalized, tamper-evident forensic storage schema**. Evidence originating from either verification path shares an identical cryptographic audit ledger, content-addressed blob storage convention, and immutable chain-of-custody metadata, enabling uniform forensic queries and court-admissible exports.

---

## 2. High-Level Architecture & Unified Storage Tiers

Evidence storage is organized into three interconnected tiers that separate raw media payloads from cryptographic manifests and indexing databases:

```
                  VERIFICATION PATHWAYS
   Path A: File-Based Upload          Path B: Live Surveillance
  (Job ID, Video/Audio/Image)      (Camera ID, RTSP/mTLS 30 FPS)
             │                                   │
             ▼                                   ▼
   Judge Adjudication & Report         Stream Anomaly / Anomaly Trigger
             │                                   │
             └─────────────────┬─────────────────┘
                               │
                               ▼
 ┌───────────────────────────────────────────────────────────────┐
 │        TIER 1: CONTENT-ADDRESSED STORAGE (CAS) BLOBS          │
 │  Path: `vault/blobs/<sha256[:2]>/<sha256>.<ext>`              │
 │  • Lossless raw media, primary frames, and context windows    │
 │  • POSIX 0444 WORM permissions (Write Once, Read Many)        │
 └─────────────────────────────┬─────────────────────────────────┘
                               │
                               ▼
 ┌───────────────────────────────────────────────────────────────┐
 │        TIER 2: RELATIONAL FORENSIC AUDIT DATABASE             │
 │  Engine: SQLite (WAL mode) / PostgreSQL                       │
 │  • Unified tables: `forensic_records`, `claim_telemetry`,     │
 │    `surveillance_sessions`, `stream_frames`, `audit_ledger`   │
 └─────────────────────────────┬─────────────────────────────────┘
                               │
                               ▼
 ┌───────────────────────────────────────────────────────────────┐
 │        TIER 3: APPEND-ONLY CRYPTOGRAPHIC AUDIT LEDGER         │
 │  Path: `vault/ledger.jsonl`                                   │
 │  • Strict hash-chaining: H_k = SHA256(H_{k-1} || Record_k)    │
 │  • Ed25519 / HMAC digital node signature on every block       │
 └───────────────────────────────────────────────────────────────┘
```

---

## 3. Cryptographic Tamper-Evidence Model

To satisfy **FRE Rule 902(13/14)** for self-authenticating electronic records, both paths enforce mathematical tamper-evidence:

### 3.1 Content-Addressed Storage (CAS) Invariant
Every piece of binary evidence (source file, anomalous frame, context frame) is stored by its SHA-256 digest:
$$\text{Blob Path} = \texttt{vault/blobs/} \parallel H(\text{Data})[:2] \parallel \texttt{/} \parallel H(\text{Data}) \parallel \texttt{.} \langle \text{ext} \rangle$$
- **Deduplication:** Identical frames or files across multiple alerts share a single storage entry.
- **Intrinsic Tamper Detection:** If any byte of the binary changes on disk, $H(\text{Data}) \neq \text{filename}$, causing automated audits to immediately flag corruption.

### 3.2 Unified Append-Only Ledger Chain
Every forensic record (file verdict or stream incident) updates an unbroken cryptographic ledger:
$$H_0 = \text{SHA256}(\texttt{"AEGIS\_UNIFIED\_VAULT\_V2\_GENESIS"})$$
$$H_k = \text{SHA256}\left(H_{k-1} \parallel \text{RecordID}_k \parallel \text{PathType}_k \parallel \text{Timestamp}_k \parallel \text{PayloadDigest}_k\right)$$

Where:
- $\text{RecordID}_k$: UUIDv4 or formatted identifier (`JOB-...` or `INC-...`).
- $\text{PathType}_k$: Enum string (`FILE_BASED` or `SURVEILLANCE`).
- $\text{PayloadDigest}_k$: SHA-256 digest over the canonical JSON representation of the forensic record.

Every block in Tier 3 is signed with the AEGIS security node key using Ed25519 or HMAC-SHA256.

---

## 4. Relational Data Schema (DDL)

The relational layer coordinates indexing, fast retrieval, and cross-path correlation queries. The schema is fully compatible with SQLite (WAL mode) and PostgreSQL.

```sql
-- ============================================================================
-- AEGIS Unified Forensic Evidence Storage Schema (Version 2.0.0)
-- ============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ----------------------------------------------------------------------------
-- 1. Evidence Blobs (Content-Addressed Storage Catalog)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence_blobs (
    sha256              TEXT PRIMARY KEY,
    byte_size           INTEGER NOT NULL,
    mime_type           TEXT NOT NULL,
    storage_relpath     TEXT NOT NULL UNIQUE,
    created_at_utc      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_lossless         BOOLEAN DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_blobs_created ON evidence_blobs(created_at_utc);

-- ----------------------------------------------------------------------------
-- 2. Master Forensic Records (Unified for Both Paths)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forensic_records (
    record_id           TEXT PRIMARY KEY,                  -- "JOB-<uuid>" or "INC-<timestamp>-<cam>-<seq>"
    path_type           TEXT NOT NULL CHECK(path_type IN ('FILE_BASED', 'SURVEILLANCE')),
    created_at_utc      TIMESTAMP NOT NULL,
    primary_blob_sha256 TEXT NOT NULL,
    final_verdict       TEXT NOT NULL CHECK(final_verdict IN ('AUTHENTIC', 'SYNTHETIC', 'INTEGRITY_UNKNOWN')),
    calibrated_score    REAL NOT NULL CHECK(calibrated_score >= 0.0 AND calibrated_score <= 1.0),
    confidence_min      REAL,
    confidence_max      REAL,
    siem_alert_tier     TEXT NOT NULL CHECK(siem_alert_tier IN ('P1_CRITICAL', 'P2_ELEVATED', 'P4_INFORMATIONAL')),
    forensic_summary    TEXT NOT NULL,
    transcript_hash     TEXT NOT NULL,                     -- SHA-256 over debate rounds or stream incident telemetry
    ledger_index        INTEGER UNIQUE NOT NULL,           -- Position in the append-only ledger
    record_hash         TEXT UNIQUE NOT NULL,              -- Block hash H_k in the ledger chain
    prev_record_hash    TEXT NOT NULL,                     -- Block hash H_{k-1}
    node_signature      TEXT NOT NULL,                     -- Cryptographic node signature
    FOREIGN KEY (primary_blob_sha256) REFERENCES evidence_blobs(sha256)
);

CREATE INDEX IF NOT EXISTS idx_records_path_type ON forensic_records(path_type);
CREATE INDEX IF NOT EXISTS idx_records_verdict ON forensic_records(final_verdict);
CREATE INDEX IF NOT EXISTS idx_records_alert ON forensic_records(siem_alert_tier);
CREATE INDEX IF NOT EXISTS idx_records_created ON forensic_records(created_at_utc);
CREATE INDEX IF NOT EXISTS idx_records_ledger ON forensic_records(ledger_index);

-- ----------------------------------------------------------------------------
-- 3. Path A Extension: File-Based Verification Metadata
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS file_verification_metadata (
    record_id           TEXT PRIMARY KEY,
    input_filename      TEXT NOT NULL,
    file_size_bytes     INTEGER NOT NULL,
    modality            TEXT NOT NULL CHECK(modality IN ('video', 'audio', 'image', 'multimodal')),
    has_audio           BOOLEAN NOT NULL,
    duration_seconds    REAL,
    resolution_w        INTEGER,
    resolution_h        INTEGER,
    fps                 REAL,
    planner_mode        TEXT NOT NULL,                     -- 'rule_based' | 'llm'
    plan_json           TEXT,                              -- Complete JSON plan from orchestrator planner
    judge_mode          TEXT NOT NULL,                     -- 'expert_deterministic_judge' | 'llm_agentic_judge'
    guards_applied      INTEGER DEFAULT 0,
    cross_exam_count    INTEGER DEFAULT 0,
    adjudication_ms     REAL NOT NULL,
    full_transcript     TEXT NOT NULL,                     -- Full 3-round debate transcript JSON
    FOREIGN KEY (record_id) REFERENCES forensic_records(record_id) ON DELETE CASCADE
);

-- ----------------------------------------------------------------------------
-- 4. Path B Extension: Live Surveillance Session & Stream Incidents
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS surveillance_sessions (
    session_id          TEXT PRIMARY KEY,                  -- "SESSION-<camera_id>-<timestamp>"
    camera_id           TEXT NOT NULL,
    mtls_subject_cn     TEXT NOT NULL,
    mtls_cert_sha256    TEXT NOT NULL,
    peer_ip             TEXT NOT NULL,
    peer_port           INTEGER NOT NULL,
    connected_at_utc    TIMESTAMP NOT NULL,
    disconnected_at_utc TIMESTAMP,
    cipher_suite        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_surv_camera ON surveillance_sessions(camera_id);

CREATE TABLE IF NOT EXISTS surveillance_incident_metadata (
    record_id           TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    camera_id           TEXT NOT NULL,
    threat_type         TEXT NOT NULL CHECK(threat_type IN (
                            'HASH_CHAIN_BREAK',
                            'PRNU_SENSOR_MISMATCH',
                            'SEQUENCE_ANOMALY',
                            'DEEPFAKE_ALERT',
                            'SESSION_HIJACK'
                        )),
    stream_seq_number   INTEGER NOT NULL,
    stream_timestamp_ms INTEGER NOT NULL,
    expected_hash       TEXT,                              -- Expected rolling SHA-256 in hash chain
    received_hash       TEXT,                              -- Received rolling SHA-256 in stream packet
    prnu_pce            REAL,                              -- Peak-to-Correlation Energy
    prnu_threshold      REAL DEFAULT 50.0,
    prnu_enrolled_cam   TEXT,
    window_start_seq    INTEGER,
    window_end_seq      INTEGER,
    socket_severed      BOOLEAN DEFAULT 0,
    FOREIGN KEY (record_id) REFERENCES forensic_records(record_id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES surveillance_sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_surv_threat ON surveillance_incident_metadata(threat_type);
CREATE INDEX IF NOT EXISTS idx_surv_camera_inc ON surveillance_incident_metadata(camera_id);

-- ----------------------------------------------------------------------------
-- 5. Surveillance Context Frames (Sliding Window & Surrounding Buffer)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS surveillance_context_frames (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id           TEXT NOT NULL,
    seq_number          INTEGER NOT NULL,
    blob_sha256         TEXT NOT NULL,
    is_tampered         BOOLEAN DEFAULT 0,
    frame_delta_ms      INTEGER,
    FOREIGN KEY (record_id) REFERENCES forensic_records(record_id) ON DELETE CASCADE,
    FOREIGN KEY (blob_sha256) REFERENCES evidence_blobs(sha256)
);

CREATE INDEX IF NOT EXISTS idx_ctx_record ON surveillance_context_frames(record_id);

-- ----------------------------------------------------------------------------
-- 6. Individual Detector Claims & Telemetry (Unified for Both Paths)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forensic_claims (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id           TEXT NOT NULL,
    detector_name       TEXT NOT NULL,
    domain              TEXT NOT NULL CHECK(domain IN ('facial', 'physiological', 'acoustics', 'audiovisual', 'sensor_physical')),
    status              TEXT NOT NULL,                     -- 'ok' | 'failed' | 'coverage_gap'
    raw_confidence      REAL,                              -- [0.0 = Authentic, 1.0 = Synthetic]
    effective_confidence REAL,
    accepted_confidence REAL,
    assigned_weight     REAL,
    discount_reason     TEXT,
    latency_ms          INTEGER,
    diagnostic_flags    TEXT,                              -- Comma-separated or JSON list of flags
    claim_assertion     TEXT,                              -- Plaintext assertion
    evidence_digest     TEXT,                              -- Hash of detector-specific raw evidence payload
    FOREIGN KEY (record_id) REFERENCES forensic_records(record_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_claims_record ON forensic_claims(record_id);
CREATE INDEX IF NOT EXISTS idx_claims_detector ON forensic_claims(detector_name);
```

---

## 5. JSON Evidence Manifest Specification

To facilitate **portable, self-verifying court bundles** (ISO/IEC 27037 compliant ZIP archives), every record in Tier 2 exports directly into a standardized JSON manifest matching this schema:

```json
{
  "$schema": "https://aegis.defense/schemas/v2/forensic_manifest.json",
  "schema_version": "2.0.0",
  "record_id": "JOB-20261026-F91A0C8",
  "path_type": "FILE_BASED",
  "created_at_utc": "2026-10-26T17:49:00.104Z",
  "provenance": {
    "source_file": "interview_broadcast_c23.mp4",
    "file_size_bytes": 14205842,
    "primary_blob": {
      "sha256": "8a7f4e91b2c3d4e5f60718293a4b5c6d7e8f901a2b3c4d5e6f7a8b9c0d1e2f3a",
      "blob_relpath": "blobs/8a/8a7f4e91b2c3d4e5f60718293a4b5c6d7e8f901a2b3c4d5e6f7a8b9c0d1e2f3a.mp4",
      "mime_type": "video/mp4"
    },
    "origin_session": null
  },
  "ruling": {
    "verdict": "SYNTHETIC",
    "calibrated_score": 0.8842,
    "confidence_interval": [0.8410, 0.9274],
    "siem_alert_tier": "P1_CRITICAL",
    "forensic_justification": "Spatial boundary artifacts detected by video-classifier (0.912) and corroborated by SyncNet lip-phoneme desync (0.856). rPPG pulse preservation discounted under Precedence Rule 3 (Face-Swap Inpainting)."
  },
  "claims": [
    {
      "detector_id": "video-classifier",
      "domain": "facial",
      "raw_confidence": 0.9120,
      "effective_confidence": 0.9120,
      "assigned_weight": 1.5,
      "discount_reason": null,
      "latency_ms": 7120
    },
    {
      "detector_id": "rppg",
      "domain": "physiological",
      "raw_confidence": 0.1200,
      "effective_confidence": 0.1200,
      "assigned_weight": 0.2,
      "discount_reason": "Precedence Rule 3: Spatial face-swap overrides intact donor heart pulse",
      "latency_ms": 6450
    }
  ],
  "cryptographic_ledger_seal": {
    "ledger_index": 104,
    "prev_record_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "record_hash": "7b58c8942b0833a6ec001cd59837a43ec946e38ea3915bc5c1920703df77e52a",
    "transcript_hash": "1d86f7b14d48c89a9f4c390544f86641d44fb6b5ac7c23f2b45cf09559c3bc88",
    "node_signature": "MEQCIFz...[Ed25519]"
  }
}
```

For **Surveillance Alerts** (`path_type: "SURVEILLANCE"`), `provenance.origin_session` populates with camera ID, mTLS certificate thumbprint, sequence number, PRNU PCE score, and context frame blobs.

---

## 6. Verification and Export Workflow

1. **Ingestion & Seal:** As soon as an incident occurs or a file verdict is reached, all media blobs are written to `vault/blobs/`, relational rows are inserted into the SQLite database, and a sealed entry is appended to `vault/ledger.jsonl`.
2. **Scheduled Integrity Scans:** A background cron job or forensic command runs a recursive audit:
   - Validates that every blob referenced in the database exists and matches its SHA-256 hash.
   - Recalculates the ledger chain from genesis ($H_0$) to the latest record, flagging any broken links or modified entries.
3. **Legal Bundle Packaging:** Investigators can invoke `export_incident_package(record_id)` which generates a self-contained ZIP archive containing:
   - `manifest.json` (the sealed JSON evidence manifest).
   - `evidence/` (all raw lossless media blobs).
   - `verify.py` (a zero-dependency Python script that judges and defense counsel can run to independently prove the mathematical validity of the hashes and signatures without installing the AEGIS stack).
