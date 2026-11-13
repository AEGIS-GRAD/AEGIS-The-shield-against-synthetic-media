"""
Characterization tests for Feed Fusion Engine Limitations.
==========================================================
Pins documented limitations in docs/LIMITATIONS.md (M2-L6 to M2-L8).
When any limitation is fixed in production, update both the test and
the corresponding LIMITATIONS.md entry.
"""

import pytest
from security.fusion.feed_fusion import FeedFusionEngine


"""
Characterization tests for Feed Fusion Engine Limitations.
==========================================================
Pins documented limitations in docs/LIMITATIONS.md (M2-L6 to M2-L8).
When any limitation is fixed in production, update both the test and
the corresponding LIMITATIONS.md entry.
"""

import pytest
from security.fusion.feed_fusion import FeedFusionEngine


def test_m2_l6_resolved_tiered_fusion_decouples_ai_score():
    """
    M2-L6 RESOLVED (Month 3 Task 4):
    In tiered mode, clean feed integrity (integrity_score=0.0) no longer
    dilutes the AI anomaly score by 0.5. The calibrated content score decides
    directly.
    """
    engine = FeedFusionEngine(synthetic_threshold=0.65, authentic_threshold=0.35, mode="tiered")

    # 1. Authentic regime: ai_score = 0.30 -> AUTHENTIC, combined_score = 0.30
    res_auth = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.30)
    assert res_auth.verdict == "AUTHENTIC"
    assert res_auth.combined_score == 0.30

    # 2. Ambiguous regime: ai_score = 0.50 -> UNCERTAIN, combined_score = 0.50
    res_unc = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.50)
    assert res_unc.verdict == "UNCERTAIN"
    assert res_unc.combined_score == 0.50

    # 3. Synthetic regime: ai_score = 0.70 -> SYNTHETIC, combined_score = 0.70 (>= 0.65 threshold)
    res_syn = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.70)
    assert res_syn.verdict == "SYNTHETIC"
    assert res_syn.combined_score == 0.70

    # 4. Backward-compatibility check: legacy mode retains Month 2 dilution
    legacy_engine = FeedFusionEngine(w_integrity=0.5, w_ai=0.5, mode="legacy")
    res_legacy = legacy_engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.70)
    assert res_legacy.combined_score == 0.35


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


def test_m2_l8_resolved_prnu_pce_thresholded_in_fusion():
    """
    M2-L8 RESOLVED (Month 3 Task 4):
    PCE Value Evaluation in Tier 1.
    In feed_fusion.py, `prnu_pce` is actively evaluated against `pce_threshold` (50.0).
    A degraded PCE (< 50.0) triggers a Tier 1 hard alert (INTEGRITY_UNKNOWN) even
    if prnu_ok boolean is passed as True.
    """
    engine = FeedFusionEngine(pce_threshold=50.0)
    # When prnu_pce is 1.0 (critically degraded foreign sensor),
    # Tier 1 triggers hard alert INTEGRITY_UNKNOWN.
    res = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, prnu_pce=1.0, ai_score=0.10)
    assert res.integrity_ok is False
    assert res.verdict == "INTEGRITY_UNKNOWN"
    assert res.tier == 1

    # When prnu_pce >= 50.0 and feed is clean, Tier 2 evaluates authentic
    res_clean = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, prnu_pce=85.0, ai_score=0.10)
    assert res_clean.integrity_ok is True
    assert res_clean.verdict == "AUTHENTIC"
    assert res_clean.tier == 2
