-- ============================================================================
-- AEGIS Unified Forensic Evidence Query Cookbook (Version 2.0.0)
-- ============================================================================
-- Standard: ISO/IEC 27037 Digital Evidence Admissibility & FRE Rule 902(13/14)
-- Scope: Covers BOTH Path A (File-Based Media Evaluation) and 
--        Path B (Real-Time Live Surveillance Streams).
-- Compatible with: SQLite (WAL mode) and PostgreSQL.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- SECTION 1: CHAIN OF CUSTODY & INCIDENT RECONSTRUCTION
-- ----------------------------------------------------------------------------

-- 1.1 Complete Case Dossier Reconstruction for Legal Subpoena / Court Export
-- Retrieves full evidence metadata, verdict, media hash, and cryptographic ledger seal
SELECT 
    r.record_id,
    r.path_type,
    r.created_at_utc,
    r.final_verdict,
    r.calibrated_score,
    r.siem_alert_tier,
    b.sha256 AS media_sha256,
    b.storage_relpath,
    b.byte_size,
    r.ledger_index,
    r.record_hash,
    r.prev_record_hash,
    r.node_signature,
    r.forensic_summary
FROM forensic_records r
JOIN evidence_blobs b ON r.primary_blob_sha256 = b.sha256
WHERE r.record_id = :target_record_id;

-- 1.2 Multi-Detector Claims Breakdown for a Specific File or Incident
-- Shows what each detector claimed, effective confidence, weights, and discount reasons
SELECT 
    c.detector_name,
    c.domain,
    c.status,
    ROUND(c.raw_confidence, 4) AS raw_confidence,
    ROUND(c.effective_confidence, 4) AS effective_confidence,
    ROUND(c.accepted_confidence, 4) AS accepted_confidence,
    c.assigned_weight,
    c.discount_reason,
    c.diagnostic_flags,
    c.latency_ms
FROM forensic_claims c
WHERE c.record_id = :target_record_id
ORDER BY c.assigned_weight DESC, c.raw_confidence DESC;


-- ----------------------------------------------------------------------------
-- SECTION 2: PATH A — FILE-BASED MEDIA FORENSICS & DEBATE AUDIT
-- ----------------------------------------------------------------------------

-- 2.1 Identify Files with Score Inversion & Guardrail Triggers (G1 / G2 Downgrades)
-- Finds files where conflicting signals were arbitrated and prevented from defaulting to Authentic
SELECT 
    r.record_id,
    f.input_filename,
    f.modality,
    r.final_verdict,
    r.calibrated_score,
    f.judge_mode,
    f.guards_applied,
    f.cross_exam_count,
    r.forensic_summary
FROM forensic_records r
JOIN file_verification_metadata f ON r.record_id = f.record_id
WHERE r.path_type = 'FILE_BASED'
  AND (f.guards_applied > 0 OR r.final_verdict = 'INTEGRITY_UNKNOWN')
ORDER BY r.created_at_utc DESC;

-- 2.2 Forensic Precedence Rule Execution Log
-- Audits which files had claims discounted under specific rules (e.g. low-light rPPG or face-swap)
SELECT 
    r.record_id,
    f.input_filename,
    c.detector_name,
    c.raw_confidence,
    c.assigned_weight,
    c.discount_reason
FROM forensic_claims c
JOIN forensic_records r ON c.record_id = r.record_id
JOIN file_verification_metadata f ON r.record_id = f.record_id
WHERE c.discount_reason IS NOT NULL
ORDER BY r.created_at_utc DESC
LIMIT 50;

-- 2.3 LLM Planner vs Rule-Based Fallback Auditing
-- Evaluates how often the LLM planner fell back to rule-based execution and why
SELECT 
    f.planner_mode,
    COUNT(*) AS total_runs,
    AVG(f.adjudication_ms) AS avg_adjudication_ms,
    SUM(CASE WHEN f.guards_applied > 0 THEN 1 ELSE 0 END) AS guarded_verdicts
FROM file_verification_metadata f
GROUP BY f.planner_mode;


-- ----------------------------------------------------------------------------
-- SECTION 3: PATH B — LIVE SURVEILLANCE & STREAM INTEGRITY
-- ----------------------------------------------------------------------------

-- 3.1 Trace Camera Tampering & Hash-Chain Breaks in Surveillance Sessions
-- Identifies stream packets where rolling SHA-256 hash failed verification
SELECT 
    s.camera_id,
    s.session_id,
    s.peer_ip,
    r.record_id,
    r.created_at_utc,
    m.stream_seq_number,
    m.threat_type,
    m.expected_hash,
    m.received_hash,
    m.socket_severed
FROM surveillance_incident_metadata m
JOIN forensic_records r ON m.record_id = r.record_id
JOIN surveillance_sessions s ON m.session_id = s.session_id
WHERE m.threat_type = 'HASH_CHAIN_BREAK'
ORDER BY r.created_at_utc DESC;

-- 3.2 Sensor Fingerprint (PRNU) Spoofing & Silicon Anomaly Log
-- Queries camera frames where Peak-to-Correlation Energy (PCE) fell below the threshold (50.0)
SELECT 
    m.camera_id,
    r.created_at_utc,
    m.stream_seq_number,
    m.prnu_pce,
    m.prnu_threshold,
    ROUND(m.prnu_threshold - m.prnu_pce, 2) AS pce_deficit,
    m.prnu_enrolled_cam,
    b.storage_relpath AS evidentiary_frame_blob
FROM surveillance_incident_metadata m
JOIN forensic_records r ON m.record_id = r.record_id
JOIN evidence_blobs b ON r.primary_blob_sha256 = b.sha256
WHERE m.threat_type = 'PRNU_SENSOR_MISMATCH'
ORDER BY m.prnu_pce ASC;

-- 3.3 Context Frame Buffer Retrieval for Incident Video Reconstruction
-- Pulls the temporal sliding-window context frames surrounding a detected deepfake incident
SELECT 
    c.record_id,
    c.seq_number,
    c.frame_delta_ms,
    c.is_tampered,
    b.sha256,
    b.storage_relpath
FROM surveillance_context_frames c
JOIN evidence_blobs b ON c.blob_sha256 = b.sha256
WHERE c.record_id = :target_incident_id
ORDER BY c.seq_number ASC;


-- ----------------------------------------------------------------------------
-- SECTION 4: CRYPTOGRAPHIC LEDGER AUDITING & TAMPER-CHECK RECIPES
-- ----------------------------------------------------------------------------

-- 4.1 Detect Ledger Chain Breaks (Immediate Evidence Tampering Flag)
-- Compares each record's prev_record_hash against the previous record's record_hash
-- If this query returns ANY rows, the cryptographic ledger has been modified or spliced!
SELECT 
    curr.ledger_index AS broken_at_index,
    curr.record_id AS broken_record_id,
    curr.created_at_utc AS record_timestamp,
    curr.prev_record_hash AS recorded_prev_hash,
    prev.record_hash AS actual_prev_record_hash,
    prev.record_id AS preceding_record_id
FROM forensic_records curr
JOIN forensic_records prev ON curr.ledger_index = prev.ledger_index + 1
WHERE curr.prev_record_hash != prev.record_hash;

-- 4.2 Orphan Blob Detection (Media Files Present Without Ledger Provenance)
-- Identifies any media blob stored on disk that is not bound to a certified forensic record
SELECT 
    b.sha256,
    b.storage_relpath,
    b.byte_size,
    b.created_at_utc
FROM evidence_blobs b
LEFT JOIN forensic_records r ON b.sha256 = r.primary_blob_sha256
LEFT JOIN surveillance_context_frames ctx ON b.sha256 = ctx.blob_sha256
WHERE r.record_id IS NULL AND ctx.id IS NULL;


-- ----------------------------------------------------------------------------
-- SECTION 5: UNIFIED SIEM ALERTING & RELIABILITY TELEMETRY
-- ----------------------------------------------------------------------------

-- 5.1 High-Severity Incident Triage Across Both Paths
-- Surfaces all P1_CRITICAL security incidents regardless of source (file upload or live camera)
SELECT 
    r.record_id,
    r.path_type,
    r.created_at_utc,
    r.final_verdict,
    r.calibrated_score,
    r.siem_alert_tier,
    COALESCE(f.input_filename, s.camera_id) AS entity_identifier,
    r.forensic_summary
FROM forensic_records r
LEFT JOIN file_verification_metadata f ON r.record_id = f.record_id
LEFT JOIN surveillance_incident_metadata s ON r.record_id = s.record_id
WHERE r.siem_alert_tier = 'P1_CRITICAL'
ORDER BY r.created_at_utc DESC
LIMIT 100;

-- 5.2 Detector Latency, Reliability, and Error Rates (Telemetric Health)
-- Aggregates performance across both offline and online verification runs
SELECT 
    c.detector_name,
    COUNT(c.id) AS total_invocations,
    ROUND(AVG(c.latency_ms), 1) AS avg_latency_ms,
    MAX(c.latency_ms) AS max_latency_ms,
    ROUND(SUM(CASE WHEN c.status = 'failed' THEN 1 ELSE 0 END) * 100.0 / COUNT(c.id), 2) AS failure_rate_pct,
    ROUND(SUM(CASE WHEN c.status = 'coverage_gap' THEN 1 ELSE 0 END) * 100.0 / COUNT(c.id), 2) AS coverage_gap_pct
FROM forensic_claims c
GROUP BY c.detector_name
ORDER BY avg_latency_ms DESC;
