"""
Characterization tests for Feed Fusion Engine Limitations.
==========================================================
Pins documented limitations in docs/LIMITATIONS.md (M2-L6 to M2-L8).
When any limitation is fixed in production, update both the test and
the corresponding LIMITATIONS.md entry.
"""

import pytest
from security.fusion.feed_fusion import FeedFusionEngine


def test_m2_l6_equal_weights_verdict_reduces_to_ai_threshold():
    """
    M2-L6: Redundant Combined Score Thresholds under Clean Integrity.
    When feed integrity is fully intact (integrity_score=0.0), with w_integrity=0.5
    and w_ai=0.5, combined_score = 0.5 * ai_score.
    Because combined_score <= 0.5, the condition `combined_score >= synthetic_threshold (0.65)`
    can never trigger on combined_score alone; the engine relies entirely on `ai_score >= 0.65`.
    Similarly, for authentic: `combined_score <= 0.35` is satisfied whenever `ai_score <= 0.70`,
    but `ai_score <= authentic_threshold (0.35)` is what governs the verdict.
    Any ai_score in (0.35, 0.65) strictly yields UNCERTAIN.
    """
    engine = FeedFusionEngine(w_integrity=0.5, w_ai=0.5, synthetic_threshold=0.65, authentic_threshold=0.35)

    # 1. Authentic regime: ai_score = 0.30 -> AUTHENTIC
    res_auth = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.30)
    assert res_auth.verdict == "AUTHENTIC"
    assert res_auth.combined_score == 0.15

    # 2. Ambiguous regime: ai_score = 0.50 -> UNCERTAIN
    res_unc = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.50)
    assert res_unc.verdict == "UNCERTAIN"
    assert res_unc.combined_score == 0.25

    # 3. Synthetic regime: ai_score = 0.70 -> SYNTHETIC
    res_syn = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.70)
    assert res_syn.verdict == "SYNTHETIC"
    assert res_syn.combined_score == 0.35


def test_m2_l6_integrity_failure_never_authentic():
    """
    M2-L6 Invariant: Feed integrity failure must NEVER resolve to AUTHENTIC.
    This is an essential security invariant of the system.
    """
    engine = FeedFusionEngine()

    # Even with an AI score of 0.00 (completely authentic-looking frames),
    # a hash-chain break forces INTEGRITY_UNKNOWN.
    res = engine.fuse(hash_chain_ok=False, integrity_anomalies=[], prnu_ok=True, ai_score=0.00)
    assert res.verdict == "INTEGRITY_UNKNOWN"
    assert res.integrity_ok is False


def test_m2_l7_alert_uses_placeholder_evidence_when_omitted():
    """
    M2-L7: Placeholder Camera & Forensic Evidence Defaults.
    When build_incident_alert() is called without explicit camera metadata
    or forensic hashes, it populates synthetic/placeholder fields:
    - default camera IP: 192.168.10.50
    - default forensic_hash: e3b0c442... (SHA-256 of empty string)
    """
    engine = FeedFusionEngine()
    res = engine.fuse(hash_chain_ok=False, integrity_anomalies=[], prnu_ok=True, ai_score=0.50)
    alert = engine.build_incident_alert(res)

    assert alert is not None
    assert alert.camera_metadata.ip_address == "192.168.10.50"
    # Empty string SHA-256 hash
    assert alert.evidence_bundle.forensic_hash == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_m2_l8_prnu_pce_not_thresholded_in_fusion():
    """
    M2-L8: PCE Value Decoupling from Integrity Score.
    In feed_fusion.py, `prnu_pce` is passed into evidence metadata,
    but the integrity_score and integrity_ok calculations rely strictly on
    the boolean `prnu_ok`, never evaluating `prnu_pce >= 50.0`.
    """
    engine = FeedFusionEngine()
    # Even if prnu_pce is 1.0 (critically degraded), if prnu_ok=True is passed,
    # the fusion engine treats the sensor as clean.
    res = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, prnu_pce=1.0, ai_score=0.10)
    assert res.integrity_ok is True
    assert res.verdict == "AUTHENTIC"
