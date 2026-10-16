"""
Unit Tests for JudgeAgent and the 3-Round Debate Protocol.
=========================================================
Tests claim ingestion, manifest cross-examination, precedence matrix routing,
judge guards (G1 & G2), tamper-evident hashing, and dual-mode explainability.
"""

import json
from pathlib import Path
import pytest

from debate.judge_agent import JudgeAgent
from debate.schemas import (
    ClaimPolarity,
    CourtAdmissibleVerdict,
    EvidenceDomain,
    ForensicClaim,
    JudgeReport,
    JudgeVerdictClass,
    OperatingConditions,
)


@pytest.fixture
def judge():
    return JudgeAgent(mode="deterministic")


@pytest.fixture
def sample_raw_responses():
    return {
        "video-classifier": {
            "job_id": "test-job-001",
            "confidence": 0.92,
            "raw_score": 0.92,
            "latency_ms": 3500,
            "model_version": "efficientnet-b0-v1.0",
            "evidence": {
                "claim": "Frame-level analysis computed fake probability of 0.92.",
                "flags": ["high_fake_probability"],
            },
        },
        "rppg": {
            "job_id": "test-job-001",
            "confidence": 0.64,
            "score": 0.18,  # Authentic heart rate
            "raw_score": 0.18,
            "verdict": "authentic",
            "estimated_bpm": 72.0,
            "latency_ms": 4200,
            "input_quality": 1.0,
            "evidence": {
                "claim": "BVP pulse signal extracted via CHROM with estimated heart rate of 72.0 BPM.",
                "flags": ["nominal_pulse_72_bpm"],
            },
        },
        "syncnet": {
            "job_id": "test-job-001",
            "confidence": 0.50,
            "raw_score": 0.0,
            "latency_ms": 100,
            "evidence": {
                "claim": "No audio track present in file — lip-sync analysis skipped.",
                "flags": ["not_applicable"],
            },
        },
    }


# ── Test Suite ───────────────────────────────────────────────────────────────

def test_judge_file_creates_valid_report(judge, sample_raw_responses):
    report: JudgeReport = judge.judge_file(sample_raw_responses, job_id="test-job-001")

    assert isinstance(report, JudgeReport)
    assert report.job_id == "test-job-001"
    assert len(report.rounds) == 3
    assert report.rounds[0].round_name == "Claim Submissions"
    assert report.rounds[1].round_name == "Cross-Examination & Context Injection"
    assert report.rounds[2].round_name == "Adjudication & Forensic Ruling"
    assert len(report.debate_transcript_hash) == 64
    assert report.verdict.final_verdict in (JudgeVerdictClass.SYNTHETIC, JudgeVerdictClass.AUTHENTIC, JudgeVerdictClass.INTEGRITY_UNKNOWN)


def test_round_2_cross_examination_detects_constraint_violations(judge):
    """Verifies cross-examination detects duration and lighting limitations."""
    claims = [
        ForensicClaim(
            job_id="job-cx",
            detector_id="rppg",
            model_version="rppg-v1",
            domain=EvidenceDomain.PHYSIOLOGICAL_BVP,
            polarity=ClaimPolarity.SYNTHETIC,
            confidence=0.85,
            claim="Pulse irregular",
            flags=["low_light_attenuation"],
        ),
        ForensicClaim(
            job_id="job-cx",
            detector_id="syncnet",
            model_version="syncnet-v1",
            domain=EvidenceDomain.AUDIOVISUAL_SYNC,
            polarity=ClaimPolarity.NOT_APPLICABLE,
            confidence=0.50,
            claim="No audio stream detected",
            flags=["not_applicable"],
            coverage_gap=True,
        ),
    ]
    conditions = OperatingConditions(duration_seconds=1.2, mean_luminance=22.0, audio_present=False)

    findings = judge.cross_examine(claims, conditions=conditions)
    categories = [f.check_category for f in findings]
    det_ids = [f.detector_id for f in findings]

    assert "operating_constraint" in categories  # duration < 2.0s
    assert "known_failure_mode" in categories    # luminance < 40.0
    assert "coverage_gap" in categories          # syncnet no audio
    assert "rppg" in det_ids
    assert "syncnet" in det_ids


def test_precedence_rule_3_face_swap_ruling(judge, sample_raw_responses):
    """Rule 3: Face-swap inpainting overrides preserved donor pulse -> SYNTHETIC."""
    report = judge.judge_file(sample_raw_responses)
    verdict = report.verdict

    assert verdict.final_verdict == JudgeVerdictClass.SYNTHETIC
    assert verdict.calibrated_score >= 0.85
    assert verdict.siem_alert_tier == "P1_CRITICAL"
    assert "Rule 3" in verdict.forensic_justification


def test_guard_1_unresolved_polarity_inversion_downgrades_to_unknown(judge):
    """Guard 1: Direct conflict with no precedence rule cannot default to AUTHENTIC."""
    raw = {
        "video-classifier": {
            "job_id": "g1-job",
            "confidence": 0.05,  # Strong authentic
            "raw_score": 0.05,
            "evidence": {"claim": "Authentic spatial frames.", "flags": ["authentic_frames"]},
        },
        "rppg": {
            "job_id": "g1-job",
            "confidence": 0.80,
            "score": 0.90,  # Strong synthetic (no low light or short clip flags!)
            "raw_score": 0.90,
            "verdict": "synthetic",
            "input_quality": 1.0,
            "evidence": {"claim": "No pulse detected.", "flags": []},
        },
        "syncnet": None,
    }
    # Ideal operating conditions (so Rule 1 and Rule 2 do NOT apply)
    conditions = OperatingConditions(duration_seconds=10.0, mean_luminance=120.0, audio_present=True)

    report = judge.judge_file(raw, conditions=conditions)

    # Without Guard 1, the weighted average (vc*1.5 + rppg*0.8)/(1.5+0.8) = 0.345 <= 0.35 -> AUTHENTIC!
    # Guard 1 MUST catch this and downgrade to INTEGRITY_UNKNOWN.
    assert report.verdict.final_verdict == JudgeVerdictClass.INTEGRITY_UNKNOWN
    assert report.verdict.siem_alert_tier == "P2_ELEVATED"
    assert any("Guard 1" in g for g in report.guards_applied)


def test_guard_2_single_detector_corroboration(judge):
    """Guard 2: A single detector with marginal confidence under degraded coverage cannot certify AUTHENTIC."""
    raw = {
        "video-classifier": {
            "job_id": "g2-job",
            "confidence": 0.32,  # Marginal authentic (between 0.25 and 0.35)
            "raw_score": 0.32,
            "evidence": {"claim": "Slight spatial noise.", "flags": ["authentic_frames"]},
        },
        "rppg": {
            "job_id": "g2-job",
            "confidence": 0.50,
            "score": 0.50,
            "verdict": "inconclusive",
            "input_quality": 0.0,
            "evidence": {"claim": "Short clip guardrail.", "flags": ["insufficient_duration"]},
        },
        "syncnet": {
            "job_id": "g2-job",
            "confidence": 0.50,
            "raw_score": 0.0,
            "evidence": {"claim": "No audio track.", "flags": ["not_applicable"]},
        },
    }
    report = judge.judge_file(raw)

    assert report.verdict.final_verdict == JudgeVerdictClass.INTEGRITY_UNKNOWN
    assert any("Guard 2" in g for g in report.guards_applied)


def test_transcript_hash_sensitivity(judge, sample_raw_responses):
    """Transcript hash must be deterministic and sensitive to input mutations."""
    report_a = judge.judge_file(sample_raw_responses, job_id="fixed-job")
    report_b = judge.judge_file(sample_raw_responses, job_id="fixed-job")
    assert report_a.debate_transcript_hash == report_b.debate_transcript_hash

    # Mutate confidence in raw input
    mutated = json.loads(json.dumps(sample_raw_responses))
    mutated["video-classifier"]["confidence"] = 0.40
    report_c = judge.judge_file(mutated, job_id="fixed-job")

    assert report_a.debate_transcript_hash != report_c.debate_transcript_hash


def test_llm_mode_fallback_on_mock_environment(sample_raw_responses, monkeypatch):
    """Verifies that in LLM mode, mock/offline environment uses deterministic fallback safely."""
    monkeypatch.setenv("AEGIS_MOCK_LLM", "true")
    judge_llm = JudgeAgent(mode="llm")

    report = judge_llm.judge_file(sample_raw_responses, job_id="llm-mock-job")

    assert report.judge_mode in ("llm_agentic_judge", "expert_deterministic_judge")
    assert report.verdict.final_verdict == JudgeVerdictClass.SYNTHETIC
    assert len(report.verdict.forensic_justification) > 50
    assert report.prompt_version == "judge-v1.0"
