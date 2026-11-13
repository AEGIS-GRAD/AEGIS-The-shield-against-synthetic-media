"""
Unit & Integration Tests for Task 3 — Explicit UNCERTAIN Outcome Handling
========================================================================
Validates that:
  1. UNCERTAIN is treated as an explicit, first-class outcome in aggregation and judge layers.
  2. UNCERTAIN is NEVER folded or counted as authentic/real.
  3. JudgeVerdictClass has an explicit UNCERTAIN enum alongside AUTHENTIC, SYNTHETIC, INTEGRITY_UNKNOWN.
  4. CourtAdmissibleVerdict exposes is_decisive, is_uncertain, is_integrity_unknown properties.
  5. Active detectors with consensus in the ambiguous zone [0.35, 0.65] render UNCERTAIN,
     while missing evidence or degraded coverage gaps render INTEGRITY_UNKNOWN.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Orchestrator aggregate
sys.path.insert(0, str(REPO_ROOT / "orchestrator" / "app"))
from orchestrator.app.aggregate import (
    AggregateOutcome,
    aggregate_results,
    evaluate_explicit_outcome,
    is_decisive,
)
from orchestrator.app.models import DetectorEvidence, DetectorResult

# Debate layer
from debate.arbitrator import JudgeArbitrator
from debate.schemas import (
    ClaimPolarity,
    CourtAdmissibleVerdict,
    EvidenceDomain,
    ForensicClaim,
    JudgeVerdictClass,
)


def make_test_claim(
    detector_id: str,
    confidence: float,
    polarity: ClaimPolarity,
    coverage_gap: bool = False,
    flags: list[str] = None,
) -> ForensicClaim:
    return ForensicClaim(
        job_id="test-job",
        detector_id=detector_id,
        model_version=f"{detector_id}-v1.0",
        domain=EvidenceDomain.SPATIAL_PIXEL,
        polarity=polarity,
        confidence=confidence,
        raw_score=confidence,
        claim=f"{detector_id} test claim",
        flags=flags or [],
        coverage_gap=coverage_gap,
    )


# ── 1. Aggregation Logic Tests ───────────────────────────────────────────────

def test_aggregation_yields_explicit_uncertain_for_ambiguous_scores():
    """Scores strictly between 0.35 and 0.65 must render UNCERTAIN, never AUTHENTIC."""
    results = [
        DetectorResult(detector="video-classifier", status="ok", confidence=0.50, raw_score=0.50),
        DetectorResult(detector="rppg", status="ok", confidence=0.50, raw_score=0.50),
    ]
    score, verdict = aggregate_results(results)
    assert verdict == AggregateOutcome.UNCERTAIN.value
    assert score == 0.50


def test_is_decisive_distinguishes_uncertain_from_authentic():
    """is_decisive must return False for UNCERTAIN and NO_RESULTS."""
    assert is_decisive("AUTHENTIC") is True
    assert is_decisive("SYNTHETIC") is True
    assert is_decisive("UNCERTAIN") is False
    assert is_decisive("NO_RESULTS") is False
    assert is_decisive("INTEGRITY_UNKNOWN") is False


def test_evaluate_explicit_outcome_does_not_fold_uncertain_into_authentic():
    """UNCERTAIN must NOT be credited as a correct authentic or folded into authentic."""
    # When media is REAL and verdict is UNCERTAIN: it is EXPLICIT_UNCERTAIN (not correct authentic!)
    res_real = evaluate_explicit_outcome("UNCERTAIN", "REAL")
    assert res_real["outcome"] == "EXPLICIT_UNCERTAIN"
    assert res_real["is_correct"] is False
    assert res_real["is_decisive"] is False

    # When media is FAKE and verdict is UNCERTAIN: it is EXPLICIT_UNCERTAIN (not false-authentic!)
    res_fake = evaluate_explicit_outcome("UNCERTAIN", "FAKE")
    assert res_fake["outcome"] == "EXPLICIT_UNCERTAIN"
    assert res_fake["is_false_authentic"] is False
    assert res_fake["is_correct"] is False

    # When media is FAKE and verdict is asserted AUTHENTIC: that IS a false-authentic
    res_fa = evaluate_explicit_outcome("AUTHENTIC", "FAKE")
    assert res_fa["outcome"] == "FALSE_AUTHENTIC"
    assert res_fa["is_false_authentic"] is True


# ── 2. Judge Verdict Class & Arbitration Tests ────────────────────────────────

def test_judge_verdict_class_has_explicit_uncertain():
    """JudgeVerdictClass must contain UNCERTAIN."""
    assert hasattr(JudgeVerdictClass, "UNCERTAIN")
    assert JudgeVerdictClass.UNCERTAIN.value == "UNCERTAIN"


def test_court_verdict_convenience_properties():
    """CourtAdmissibleVerdict should report is_decisive, is_uncertain, and is_integrity_unknown."""
    vrd_unc = CourtAdmissibleVerdict(
        verdict_id="vrd-1",
        job_id="job-1",
        final_verdict=JudgeVerdictClass.UNCERTAIN,
        calibrated_score=0.50,
        arbitration_mode="consensus_fast_path",
        forensic_justification="Ambiguous confidence across sensors.",
        siem_alert_tier="P2_ELEVATED",
        evidence_manifest_hash="0" * 64,
    )
    assert vrd_unc.is_uncertain is True
    assert vrd_unc.is_decisive is False
    assert vrd_unc.is_integrity_unknown is False

    vrd_auth = CourtAdmissibleVerdict(
        verdict_id="vrd-2",
        job_id="job-2",
        final_verdict=JudgeVerdictClass.AUTHENTIC,
        calibrated_score=0.10,
        arbitration_mode="consensus_fast_path",
        forensic_justification="Authentic signals verified.",
        siem_alert_tier="P4_INFORMATIONAL",
        evidence_manifest_hash="0" * 64,
    )
    assert vrd_auth.is_decisive is True
    assert vrd_auth.is_uncertain is False


def test_judge_renders_uncertain_when_scores_are_ambiguous_without_gaps():
    """Active detectors with no coverage gaps and ensemble score in (0.35, 0.65) must render UNCERTAIN."""
    arbitrator = JudgeArbitrator()
    claims = [
        make_test_claim("video-classifier", 0.42, ClaimPolarity.AUTHENTIC, coverage_gap=False),
        make_test_claim("rppg", 0.44, ClaimPolarity.AUTHENTIC, coverage_gap=False),
    ]
    verdict = arbitrator.arbitrate(claims, job_id="job-ambiguous")
    assert verdict.final_verdict == JudgeVerdictClass.UNCERTAIN
    assert verdict.is_uncertain is True


def test_judge_renders_integrity_unknown_when_coverage_gaps_exist():
    """When modalities suffer coverage gaps or lack evidence, verdict must be INTEGRITY_UNKNOWN."""
    arbitrator = JudgeArbitrator()
    claims = [
        make_test_claim("video-classifier", 0.50, ClaimPolarity.INCONCLUSIVE, coverage_gap=False),
        make_test_claim("syncnet", 0.50, ClaimPolarity.NOT_APPLICABLE, coverage_gap=True, flags=["not_applicable"]),
    ]
    verdict = arbitrator.arbitrate(claims, job_id="job-gaps")
    assert verdict.final_verdict == JudgeVerdictClass.INTEGRITY_UNKNOWN
    assert verdict.is_integrity_unknown is True
