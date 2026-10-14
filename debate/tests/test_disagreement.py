"""
Tests for AEGIS Disagreement Detection Engine.
Verifies threshold triggers, polarity inversion detection, and coverage gap isolation.
"""

import pytest
from debate.disagreement import evaluate_disagreement
from debate.schemas import (
    ClaimPolarity,
    DisagreementType,
    EvidenceDomain,
    ForensicClaim,
)


def make_claim(detector_id: str, conf: float, polarity: ClaimPolarity, flags: list = None, coverage_gap: bool = False) -> ForensicClaim:
    return ForensicClaim(
        job_id="test-job",
        detector_id=detector_id,
        model_version="v1.0",
        domain=EvidenceDomain.SPATIAL_PIXEL,
        polarity=polarity,
        confidence=conf,
        claim=f"Test claim from {detector_id}",
        flags=flags or [],
        coverage_gap=coverage_gap,
    )


def test_consensus_no_arbitration():
    claims = [
        make_claim("video-classifier", 0.85, ClaimPolarity.SYNTHETIC),
        make_claim("rppg", 0.78, ClaimPolarity.SYNTHETIC),
        make_claim("syncnet", 0.82, ClaimPolarity.SYNTHETIC),
    ]
    analysis = evaluate_disagreement(claims)
    assert not analysis.requires_arbitration
    assert analysis.primary_disagreement_type == DisagreementType.CONSENSUS
    assert analysis.confidence_spread == pytest.approx(0.07, abs=1e-3)
    assert len(analysis.coverage_gaps) == 0


def test_polarity_inversion_triggers_arbitration():
    claims = [
        make_claim("video-classifier", 0.92, ClaimPolarity.SYNTHETIC, flags=["high_fake_probability"]),
        make_claim("rppg", 0.15, ClaimPolarity.AUTHENTIC, flags=["nominal_heart_rate"]),
    ]
    analysis = evaluate_disagreement(claims)
    assert analysis.requires_arbitration
    assert analysis.primary_disagreement_type == DisagreementType.POLARITY_INVERSION
    assert "video-classifier" in analysis.conflicting_detectors
    assert "rppg" in analysis.conflicting_detectors
    assert analysis.confidence_spread == pytest.approx(0.77, abs=1e-3)


def test_confidence_spread_triggers_arbitration():
    # Both lean synthetic, but spread >= 0.30
    claims = [
        make_claim("video-classifier", 0.95, ClaimPolarity.SYNTHETIC),
        make_claim("rppg", 0.60, ClaimPolarity.SYNTHETIC),
    ]
    analysis = evaluate_disagreement(claims)
    assert analysis.requires_arbitration
    assert analysis.primary_disagreement_type == DisagreementType.CONFIDENCE_SPREAD
    assert analysis.confidence_spread == pytest.approx(0.35, abs=1e-3)


def test_coverage_gap_isolated_from_conflict():
    # Silent video: SyncNet returns not_applicable / coverage gap
    claims = [
        make_claim("video-classifier", 0.88, ClaimPolarity.SYNTHETIC),
        make_claim("rppg", 0.84, ClaimPolarity.SYNTHETIC),
        make_claim("syncnet", 0.50, ClaimPolarity.NOT_APPLICABLE, flags=["not_applicable", "silent_video"], coverage_gap=True),
    ]
    analysis = evaluate_disagreement(claims)
    assert not analysis.requires_arbitration
    assert analysis.primary_disagreement_type == DisagreementType.CONSENSUS
    assert "syncnet" in analysis.coverage_gaps
    assert analysis.confidence_spread == pytest.approx(0.04, abs=1e-3)


def test_single_active_with_gaps():
    claims = [
        make_claim("video-classifier", 0.82, ClaimPolarity.SYNTHETIC),
        make_claim("rppg", 0.50, ClaimPolarity.INCONCLUSIVE, flags=["insufficient_signal"], coverage_gap=True),
        make_claim("syncnet", 0.50, ClaimPolarity.NOT_APPLICABLE, flags=["not_applicable"], coverage_gap=True),
    ]
    analysis = evaluate_disagreement(claims)
    assert not analysis.requires_arbitration
    assert len(analysis.coverage_gaps) == 2
