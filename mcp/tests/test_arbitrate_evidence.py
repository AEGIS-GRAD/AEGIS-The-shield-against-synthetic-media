"""
Unit and edge-case tests for the MCP arbitrate_evidence() tool.
"""

from __future__ import annotations

import json
import pytest
import server


# ── Edge Case & Validation Tests ─────────────────────────────────────────────

def test_arbitrate_empty_claims():
    """Empty claims list must gracefully return INTEGRITY_UNKNOWN."""
    res = server.arbitrate_evidence(claims=[])
    assert res["status"] == "ok"
    assert res["final_verdict"] == "INTEGRITY_UNKNOWN"
    assert res["calibrated_score"] == 0.5
    assert "No forensic evidence provided" in res["forensic_justification"]
    assert res["verdict"]["verdict_id"].startswith("vrd-")


def test_arbitrate_non_list_claims():
    """Non-list claims parameter must return a structured error."""
    res = server.arbitrate_evidence(claims=12345)  # type: ignore[arg-type]
    assert res["status"] == "error"
    assert "must be a list" in res["error"]
    assert res["verdict"] is None


def test_arbitrate_malformed_claim_element():
    """Non-dict element inside claims list must return a structured error."""
    res = server.arbitrate_evidence(claims=["not_a_dict"])
    assert res["status"] == "error"
    assert "not a dict" in res["error"]


def test_arbitrate_missing_required_field():
    """Claim missing required field (e.g. confidence or domain) returns error."""
    invalid_claim = {
        "job_id": "job-bad",
        "detector_id": "video-classifier",
        # missing model_version, domain, polarity, confidence
        "claim": "Incomplete claim",
    }
    res = server.arbitrate_evidence(claims=[invalid_claim])
    assert res["status"] == "error"
    assert "Invalid claim at index 0" in res["error"]


def test_arbitrate_invalid_confidence_range():
    """Confidence outside [0.0, 1.0] must be rejected."""
    bad_conf_claim = {
        "job_id": "job-bad-conf",
        "detector_id": "video-classifier",
        "model_version": "v1",
        "domain": "spatial_pixel",
        "polarity": "SYNTHETIC",
        "confidence": 1.5,  # Invalid: > 1.0
        "claim": "Score out of range",
    }
    res = server.arbitrate_evidence(claims=[bad_conf_claim])
    assert res["status"] == "error"
    assert "Invalid claim at index 0" in res["error"]


def test_arbitrate_json_string_input(sample_video_classifier_synthetic):
    """Claims passed as a JSON-encoded string must be parsed and processed."""
    claims_json = json.dumps([sample_video_classifier_synthetic])
    res = server.arbitrate_evidence(claims=claims_json)
    assert res["status"] == "ok"
    assert res["final_verdict"] in ("SYNTHETIC", "INTEGRITY_UNKNOWN")


def test_arbitrate_malformed_operating_conditions(sample_video_classifier_synthetic):
    """Invalid operating conditions type or schema returns a structured error."""
    res = server.arbitrate_evidence(
        claims=[sample_video_classifier_synthetic],
        operating_conditions="not a valid json",
    )
    assert res["status"] == "error"
    assert "Failed to parse 'operating_conditions'" in res["error"]


# ── Consensus Scenarios ──────────────────────────────────────────────────────

def test_arbitrate_unanimous_synthetic(sample_video_classifier_synthetic, sample_aasist_synthetic):
    """Unanimous synthetic claims should confirm SYNTHETIC via consensus_fast_path."""
    res = server.arbitrate_evidence(
        claims=[sample_video_classifier_synthetic, sample_aasist_synthetic]
    )
    assert res["status"] == "ok"
    assert res["final_verdict"] == "SYNTHETIC"
    assert res["calibrated_score"] >= 0.65
    assert res["arbitration_mode"] == "consensus_fast_path"
    assert res["verdict"]["siem_alert_tier"] == "P1_CRITICAL"


def test_arbitrate_unanimous_authentic(sample_rppg_authentic, sample_syncnet_authentic):
    """Unanimous authentic claims should confirm AUTHENTIC via consensus."""
    res = server.arbitrate_evidence(
        claims=[sample_rppg_authentic, sample_syncnet_authentic]
    )
    assert res["status"] == "ok"
    assert res["final_verdict"] == "AUTHENTIC"
    assert res["calibrated_score"] <= 0.35
    assert res["verdict"]["siem_alert_tier"] == "P4_INFORMATIONAL"


# ── Precedence Matrix Rules ──────────────────────────────────────────────────

def test_precedence_rule3_face_swap(
    sample_video_classifier_synthetic, sample_rppg_authentic, sample_nominal_conditions
):
    """Rule 3: video-classifier synthetic overrides rPPG authentic pulse (donor pulse preservation)."""
    res = server.arbitrate_evidence(
        claims=[sample_video_classifier_synthetic, sample_rppg_authentic],
        operating_conditions=sample_nominal_conditions,
    )
    assert res["status"] == "ok"
    assert res["final_verdict"] == "SYNTHETIC"
    assert res["calibrated_score"] >= 0.85
    assert res["arbitration_mode"] == "expert_deterministic_judge"

    # Verify Rule 3 applied in adjudications
    adjudications = res["verdict"]["adjudications"]
    rppg_adj = next(a for a in adjudications if a["detector_id"] == "rppg")
    assert "Face-Swap Inpainting" in (rppg_adj["discount_reason"] or "")


def test_precedence_rule1_low_light_inversion(
    sample_rppg_synthetic, sample_syncnet_authentic
):
    """Rule 1: rPPG synthetic claim discounted due to low luminance (<40.0)."""
    low_light_conditions = {
        "duration_seconds": 10.0,
        "mean_luminance": 22.0,  # Below 40.0 threshold
        "face_detected": True,
        "audio_present": True,
    }
    res = server.arbitrate_evidence(
        claims=[sample_rppg_synthetic, sample_syncnet_authentic],
        operating_conditions=low_light_conditions,
    )
    assert res["status"] == "ok"
    adjudications = res["verdict"]["adjudications"]
    rppg_adj = next(a for a in adjudications if a["detector_id"] == "rppg")
    assert rppg_adj["discount_reason"] is not None
    assert "Low Light" in rppg_adj["discount_reason"] or "Precedence Rule" in rppg_adj["discount_reason"]


def test_precedence_rule4_audio_dubbing(sample_syncnet_desync, sample_rppg_authentic):
    """Rule 4: SyncNet lip-desync discounted as audio dubbing when visual presence is authentic."""
    res = server.arbitrate_evidence(
        claims=[sample_syncnet_desync, sample_rppg_authentic]
    )
    assert res["status"] == "ok"
    adjudications = res["verdict"]["adjudications"]
    sync_adj = next(a for a in adjudications if a["detector_id"] == "syncnet")
    assert "Audio Dubbing" in (sync_adj["discount_reason"] or "")


def test_precedence_rule5_voice_cloning(
    sample_aasist_synthetic, sample_rppg_authentic, sample_nominal_conditions
):
    """Rule 5: AASIST synthetic speech overrides authentic visual footage (voice-clone attack)."""
    res = server.arbitrate_evidence(
        claims=[sample_aasist_synthetic, sample_rppg_authentic],
        operating_conditions=sample_nominal_conditions,
    )
    assert res["status"] == "ok"
    assert res["final_verdict"] == "SYNTHETIC"
    assert res["calibrated_score"] >= 0.85
    assert "Synthetic Voice" in res["forensic_justification"]


def test_guard_2b_secondary_proxy_cannot_solo_certify(sample_rppg_synthetic):
    """Guard 2B: Secondary proxy (rPPG) alone cannot certify SYNTHETIC; held in UNCERTAIN or INTEGRITY_UNKNOWN."""
    res = server.arbitrate_evidence(claims=[sample_rppg_synthetic])
    assert res["status"] == "ok"
    # Secondary proxy alone must NOT result in SYNTHETIC
    assert res["final_verdict"] != "SYNTHETIC"
    assert res["final_verdict"] in ("UNCERTAIN", "INTEGRITY_UNKNOWN")
    assert res["calibrated_score"] < 0.65
