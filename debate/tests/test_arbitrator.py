"""
Comprehensive tests for JudgeArbitrator.
Verifies all five conflict scenarios, precedence matrix rules, and court-admissible formatting.
"""

import pytest
from debate.arbitrator import JudgeArbitrator
from debate.schemas import (
    ClaimPolarity,
    EvidenceDomain,
    ForensicClaim,
    JudgeVerdictClass,
    OperatingConditions,
)


@pytest.fixture
def arbitrator():
    return JudgeArbitrator()


def make_claim(
    detector_id: str,
    conf: float,
    polarity: ClaimPolarity,
    domain: EvidenceDomain = EvidenceDomain.SPATIAL_PIXEL,
    flags: list = None,
    coverage_gap: bool = False,
) -> ForensicClaim:
    return ForensicClaim(
        job_id="job-scenario-test",
        detector_id=detector_id,
        model_version=f"{detector_id}-v1",
        domain=domain,
        polarity=polarity,
        confidence=conf,
        claim=f"Test evidence from {detector_id} (conf={conf:.2f})",
        flags=flags or [],
        coverage_gap=coverage_gap,
    )


def test_scenario_1_face_swap_deepfake(arbitrator):
    """Scenario 1: High spatial manipulation, but rPPG detects intact host body pulse.

    Rule 3 applies: Face-swap inpainting overrides preserved donor pulse.
    """
    claims = [
        make_claim("video-classifier", 0.91, ClaimPolarity.SYNTHETIC, EvidenceDomain.SPATIAL_PIXEL, ["high_fake_probability"]),
        make_claim("rppg", 0.18, ClaimPolarity.AUTHENTIC, EvidenceDomain.PHYSIOLOGICAL_BVP, ["nominal_pulse_68_bpm"]),
        make_claim("syncnet", 0.50, ClaimPolarity.NOT_APPLICABLE, EvidenceDomain.AUDIOVISUAL_SYNC, ["not_applicable"], coverage_gap=True),
    ]

    verdict = arbitrator.arbitrate(claims, job_id="job-scenario-1")

    assert verdict.final_verdict == JudgeVerdictClass.SYNTHETIC
    assert verdict.calibrated_score >= 0.85
    assert verdict.siem_alert_tier == "P1_CRITICAL"
    assert "Rule 3" in verdict.forensic_justification
    assert len(verdict.evidence_manifest_hash) == 64


def test_scenario_2_low_light_score_inversion_trap(arbitrator):
    """Scenario 2: Dark night video where rPPG chromatic collapse emits false synthetic.

    Rule 1 applies: rPPG synthetic claim discounted due to luminance < 40.
    """
    claims = [
        make_claim("video-classifier", 0.28, ClaimPolarity.AUTHENTIC, EvidenceDomain.SPATIAL_PIXEL, ["authentic_frames"]),
        make_claim("rppg", 0.89, ClaimPolarity.SYNTHETIC, EvidenceDomain.PHYSIOLOGICAL_BVP, ["low_light_attenuation"]),
        make_claim("syncnet", 0.50, ClaimPolarity.NOT_APPLICABLE, EvidenceDomain.AUDIOVISUAL_SYNC, ["not_applicable"], coverage_gap=True),
    ]
    conditions = OperatingConditions(mean_luminance=15.0, duration_seconds=8.0)

    verdict = arbitrator.arbitrate(claims, job_id="job-scenario-2", conditions=conditions)

    assert verdict.final_verdict == JudgeVerdictClass.AUTHENTIC
    assert verdict.calibrated_score <= 0.35
    assert verdict.siem_alert_tier == "P4_INFORMATIONAL"
    assert "Rule 1" in verdict.forensic_justification


def test_scenario_3_foreign_dubbed_news(arbitrator):
    """Scenario 3: Authentic news video with post-production foreign translation.

    Rule 4 applies: SyncNet desync is ruled as post-dubbing, visual authentic signals prevail.
    """
    claims = [
        make_claim("video-classifier", 0.15, ClaimPolarity.AUTHENTIC, EvidenceDomain.SPATIAL_PIXEL, ["authentic_frames"]),
        make_claim("rppg", 0.20, ClaimPolarity.AUTHENTIC, EvidenceDomain.PHYSIOLOGICAL_BVP, ["nominal_pulse_72_bpm"]),
        make_claim("syncnet", 0.92, ClaimPolarity.SYNTHETIC, EvidenceDomain.AUDIOVISUAL_SYNC, ["sync_offset_detected", "audio_visual_mismatch"]),
    ]

    verdict = arbitrator.arbitrate(claims, job_id="job-scenario-3")

    assert verdict.final_verdict == JudgeVerdictClass.AUTHENTIC
    assert verdict.calibrated_score <= 0.35
    assert "Rule 4" in verdict.forensic_justification


def test_scenario_4_silent_surveillance_consensus(arbitrator):
    """Scenario 4: Silent surveillance camera. SyncNet is a coverage gap.

    Active detectors agree synthetic -> Consensus fast-path with coverage caveat.
    """
    claims = [
        make_claim("video-classifier", 0.86, ClaimPolarity.SYNTHETIC, EvidenceDomain.SPATIAL_PIXEL, ["high_fake_probability"]),
        make_claim("rppg", 0.82, ClaimPolarity.SYNTHETIC, EvidenceDomain.PHYSIOLOGICAL_BVP, ["irregular_pulse_pattern"]),
        make_claim("syncnet", 0.50, ClaimPolarity.NOT_APPLICABLE, EvidenceDomain.AUDIOVISUAL_SYNC, ["not_applicable", "silent_video"], coverage_gap=True),
    ]

    verdict = arbitrator.arbitrate(claims, job_id="job-scenario-4")

    assert verdict.final_verdict == JudgeVerdictClass.SYNTHETIC
    assert verdict.arbitration_mode == "consensus_fast_path"
    assert len(verdict.coverage_warnings) >= 1
    assert "syncnet" in verdict.coverage_warnings[0]


def test_scenario_5_severely_degraded_video(arbitrator):
    """Scenario 5: Poorly lit, occluded, short clip.

    Anti-default rule: Must NEVER default to authentic. Must be INTEGRITY_UNKNOWN.
    """
    claims = [
        make_claim("video-classifier", 0.52, ClaimPolarity.INCONCLUSIVE, EvidenceDomain.SPATIAL_PIXEL, ["borderline_frames"]),
        make_claim("rppg", 0.50, ClaimPolarity.INCONCLUSIVE, EvidenceDomain.PHYSIOLOGICAL_BVP, ["insufficient_signal"], coverage_gap=True),
        make_claim("syncnet", 0.50, ClaimPolarity.NOT_APPLICABLE, EvidenceDomain.AUDIOVISUAL_SYNC, ["insufficient_signal"], coverage_gap=True),
    ]

    verdict = arbitrator.arbitrate(claims, job_id="job-scenario-5")

    assert verdict.final_verdict == JudgeVerdictClass.INTEGRITY_UNKNOWN
    assert verdict.siem_alert_tier == "P2_ELEVATED"


def test_empty_claims_handling(arbitrator):
    verdict = arbitrator.arbitrate([], job_id="empty-job")
    assert verdict.final_verdict == JudgeVerdictClass.INTEGRITY_UNKNOWN
    assert verdict.arbitration_mode == "no_evidence_fallback"
