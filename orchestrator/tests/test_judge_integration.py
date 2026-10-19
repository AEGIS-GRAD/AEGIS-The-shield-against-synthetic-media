"""
Integration test: verifies that the orchestrator pipeline produces a full
JudgeReport (3 rounds, transcript hash, verdict) instead of raw score averaging.
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from models import DetectorResult, DetectorEvidence, InputMetadata
from judge_bridge import run_judge, build_raw_responses, build_operating_conditions


class TestJudgeBridgeTranslation:
    def test_build_raw_responses_ok_detector(self):
        r = DetectorResult(
            detector="video-classifier", status="ok", job_id="j1",
            confidence=0.8, raw_score=0.8, latency_ms=100, model_version="v1",
            evidence=DetectorEvidence(claim="Synthetic.", flags=["face_swap"])
        )
        raw = build_raw_responses([r])
        assert "video-classifier" in raw
        assert raw["video-classifier"]["confidence"] == 0.8
        assert raw["video-classifier"]["evidence"]["flags"] == ["face_swap"]

    def test_build_raw_responses_failed_detector_is_none(self):
        r = DetectorResult(detector="rppg", status="failed", job_id="j1", error="timeout")
        raw = build_raw_responses([r])
        assert raw["rppg"] is None

    def test_operating_conditions_from_metadata(self):
        meta = InputMetadata(filename="f.mp4", modality="video", has_audio=True, duration_seconds=10.0)
        cond = build_operating_conditions(meta)
        assert cond.duration_seconds == 10.0
        assert cond.audio_present is True


class TestJudgeReportStructure:
    def _make_results(self, conf1=0.9, conf2=0.85) -> list:
        return [
            DetectorResult(
                detector="video-classifier", status="ok", job_id="int-001",
                confidence=conf1, raw_score=conf1, latency_ms=120, model_version="v1",
                evidence=DetectorEvidence(claim="High synthetic probability.", flags=[])
            ),
            DetectorResult(
                detector="rppg", status="ok", job_id="int-001",
                confidence=conf2, raw_score=conf2, latency_ms=300, model_version="v1",
                evidence=DetectorEvidence(claim="Flat BVP — no pulse.", flags=[])
            ),
        ]

    def test_report_has_three_rounds(self):
        meta = InputMetadata(filename="x.mp4", modality="video", has_audio=False, duration_seconds=6.0)
        report = run_judge(self._make_results(), meta, "int-001")
        assert len(report.rounds) == 3
        assert report.rounds[0].round_name == "Claim Submissions"
        assert report.rounds[1].round_name == "Cross-Examination & Context Injection"
        assert report.rounds[2].round_name == "Adjudication & Forensic Ruling"

    def test_report_has_transcript_hash(self):
        meta = InputMetadata(filename="x.mp4", modality="video", has_audio=False, duration_seconds=6.0)
        report = run_judge(self._make_results(), meta, "int-002")
        assert report.debate_transcript_hash
        assert len(report.debate_transcript_hash) == 64  # SHA-256 hex

    def test_verdict_is_not_raw_average(self):
        """The verdict must come from arbitration, not a bare weighted average."""
        meta = InputMetadata(filename="x.mp4", modality="video", has_audio=False, duration_seconds=6.0)
        report = run_judge(self._make_results(), meta, "int-003")
        assert report.verdict.final_verdict.value in ("SYNTHETIC", "AUTHENTIC", "INTEGRITY_UNKNOWN")
        assert report.verdict.arbitration_mode in (
            "consensus_fast_path", "expert_deterministic_judge", "llm_agentic_judge"
        )
        # Score must be a float, not None
        assert isinstance(report.verdict.calibrated_score, float)

    def test_forensic_justification_is_not_empty(self):
        meta = InputMetadata(filename="x.mp4", modality="video", has_audio=False, duration_seconds=6.0)
        report = run_judge(self._make_results(), meta, "int-004")
        assert report.verdict.forensic_justification
        assert len(report.verdict.forensic_justification) > 20  # must be a real sentence

    def test_polarity_conflict_triggers_guard_or_rules(self):
        """video-classifier says authentic (0.1), rppg says synthetic (0.8) — Guard 1 or a Rule must fire."""
        results = [
            DetectorResult(detector="video-classifier", status="ok", job_id="g1-test",
                           confidence=0.1, raw_score=0.1, latency_ms=100, model_version="v1",
                           evidence=DetectorEvidence(claim="Authentic frames.", flags=[])),
            DetectorResult(detector="rppg", status="ok", job_id="g1-test",
                           confidence=0.8, raw_score=0.8, latency_ms=200, model_version="v1",
                           evidence=DetectorEvidence(claim="Flat BVP detected.", flags=[])),
        ]
        meta = InputMetadata(filename="conflict.mp4", modality="video", has_audio=False, duration_seconds=6.0)
        report = run_judge(results, meta, "g1-test")
        # Guard 1 must have prevented a false AUTHENTIC verdict
        assert report.verdict.final_verdict.value != "AUTHENTIC", \
            "Guard 1 must block AUTHENTIC when detectors disagree without a resolved precedence rule"
