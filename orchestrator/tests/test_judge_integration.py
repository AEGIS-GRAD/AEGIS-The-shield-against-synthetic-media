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

    def test_build_raw_responses_includes_aasist(self):
        """M2-L9 fix: aasist audio detector claims must NOT be filtered out."""
        r = DetectorResult(
            detector="aasist", status="ok", job_id="j-audio",
            confidence=0.95, raw_score=3.5, latency_ms=180, model_version="aasist-v1.0",
            evidence=DetectorEvidence(
                claim="Voice cloning suspected with high confidence.",
                flags=["voice_cloning_suspected", "high_spoof_confidence"],
            ),
        )
        raw = build_raw_responses([r])
        assert "aasist" in raw
        assert raw["aasist"]["confidence"] == 0.95
        assert "voice_cloning_suspected" in raw["aasist"]["evidence"]["flags"]

    def test_operating_conditions_from_metadata(self):
        meta = InputMetadata(
            filename="f.mp4", modality="video", has_audio=True, duration_seconds=10.0,
            mean_luminance=78.5, face_detected=True,
        )
        cond = build_operating_conditions(meta)
        assert cond.duration_seconds == 10.0
        assert cond.audio_present is True
        assert cond.mean_luminance == 78.5
        assert cond.face_detected is True

    def test_operating_conditions_enrichment_from_results(self):
        meta = InputMetadata(filename="dark.mp4", modality="video", has_audio=True, duration_seconds=5.0)
        res = [
            DetectorResult(
                detector="rppg", status="ok", job_id="j-dark",
                confidence=0.75, raw_score=0.75, latency_ms=200, model_version="v1",
                evidence=DetectorEvidence(claim="Low lighting.", flags=["low_light_attenuation"]),
            )
        ]
        cond = build_operating_conditions(meta, results=res)
        assert cond.mean_luminance == 25.0


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

    def test_cloned_voice_clip_reaches_judge_and_adjudicates_synthetic(self):
        """Task 5 test: Voice clone clip with authentic video + synthetic audio.

        AASIST claim must reach judge, Rule 5 must fire, and final verdict must be SYNTHETIC.
        """
        results = [
            DetectorResult(
                detector="video-classifier", status="ok", job_id="vc-clone-01",
                confidence=0.10, raw_score=0.10, latency_ms=120, model_version="v1",
                evidence=DetectorEvidence(claim="Authentic facial frames.", flags=["authentic_frames"]),
            ),
            DetectorResult(
                detector="rppg", status="ok", job_id="vc-clone-01",
                confidence=0.15, raw_score=0.15, latency_ms=250, model_version="v1",
                evidence=DetectorEvidence(claim="Nominal pulse 72 BPM.", flags=["nominal_pulse_72_bpm"]),
            ),
            DetectorResult(
                detector="aasist", status="ok", job_id="vc-clone-01",
                confidence=0.96, raw_score=3.8, latency_ms=200, model_version="aasist-v1.0",
                evidence=DetectorEvidence(
                    claim="Synthetic cloned audio detected with high confidence.",
                    flags=["high_spoof_confidence", "voice_cloning_suspected"],
                ),
            ),
        ]
        meta = InputMetadata(
            filename="voice_clone_clip.mp4",
            modality="video",
            has_audio=True,
            duration_seconds=5.0,
            mean_luminance=90.0,
            face_detected=True,
        )

        report = run_judge(results, meta, "vc-clone-01")

        # Confirm audio claim reached the judge debate rounds
        r1_claims = report.rounds[0].details.get("claims", [])
        assert any(c["detector_id"] == "aasist" for c in r1_claims), "AASIST claim must appear in Round 1"

        # Confirm Rule 5 applied
        assert report.verdict.final_verdict.value == "SYNTHETIC"
        assert report.verdict.calibrated_score >= 0.85
        assert report.verdict.siem_alert_tier == "P1_CRITICAL"
        assert "Rule 5" in report.verdict.forensic_justification

    def test_low_light_clip_triggers_rule1_dynamically(self):
        """Task 5 test: Low-light video where rPPG chromatic collapse emits false synthetic.

        Real metadata luminance < 40 must dynamically trigger Precedence Rule 1.
        """
        results = [
            DetectorResult(
                detector="video-classifier", status="ok", job_id="lowlight-01",
                confidence=0.15, raw_score=0.15, latency_ms=110, model_version="v1",
                evidence=DetectorEvidence(claim="No artifacts found in frames.", flags=["authentic_frames"]),
            ),
            DetectorResult(
                detector="rppg", status="ok", job_id="lowlight-01",
                confidence=0.88, raw_score=0.88, latency_ms=210, model_version="v1",
                evidence=DetectorEvidence(claim="Low lighting attenuation.", flags=["low_light_attenuation"]),
            ),
        ]
        meta = InputMetadata(
            filename="night_clip.mp4",
            modality="video",
            has_audio=False,
            duration_seconds=8.0,
            mean_luminance=20.5,  # Real computed low luminance (< 40)
            face_detected=True,
        )

        report = run_judge(results, meta, "lowlight-01")

        # Operating conditions must reflect real metadata
        r2_findings = report.rounds[1].details.get("findings", [])
        assert any("Rule 1" in (f.get("rule_reference") or "") for f in r2_findings), \
            "Cross-examination should note Rule 1 under low-light operating conditions"

        # rPPG is discounted under Rule 1, authentic visual consensus prevails
        assert "Rule 1" in report.verdict.forensic_justification
        assert report.verdict.final_verdict.value == "AUTHENTIC"
        assert report.verdict.calibrated_score <= 0.35
