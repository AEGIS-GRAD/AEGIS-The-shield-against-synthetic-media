"""
Regression tests verifying Task 7 deliverables:
  - 067.mp4 (m1-case-010) false-synthetic elimination (1 -> 0)
  - Guard 2B blocking secondary proxy solo-synthetic rulings
  - < 30% INTEGRITY_UNKNOWN abstention on Month 1 frozen + calibrated modes
  - 0 false-authentics preserved on all uncalibrated conflicting fakes
  - Real Text & Image suites conformance, judge_bridge not_applicable pass-through,
    and run_judge_eval.py --video-scores-csv workflow.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
ORCH_APP_DIR = REPO_ROOT / "orchestrator" / "app"
if str(ORCH_APP_DIR) not in sys.path:
    sys.path.insert(0, str(ORCH_APP_DIR))

from debate.claim_wrapper import wrap_detector_response, wrap_video_detector_outputs
from debate.disagreement import evaluate_disagreement
from debate.judge_agent import JudgeAgent
from debate.schemas import ClaimPolarity, CourtAdmissibleVerdict, JudgeVerdictClass, OperatingConditions
from judge_bridge import build_raw_responses
from models import DetectorEvidence, DetectorResult

MONTH1_PATH = REPO_ROOT / "eval" / "fixtures" / "judge" / "month1_judge_cases.json"
IMAGE_PATH = REPO_ROOT / "eval" / "fixtures" / "judge" / "image_judge_cases.json"
TEXT_PATH = REPO_ROOT / "eval" / "fixtures" / "judge" / "text_judge_cases.json"


def test_067_mp4_false_synthetic_eliminated():
    """m1-case-010 (067.mp4, true_label=real) must never produce SYNTHETIC."""
    cases = json.loads(MONTH1_PATH.read_text(encoding="utf-8"))
    case_010 = next(c for c in cases if c["case_id"] == "m1-case-010")
    assert case_010["filename"] == "067.mp4"
    assert case_010["true_label"] == "real"

    judge = JudgeAgent()
    cond = OperatingConditions(**case_010["operating_conditions"])
    report = judge.judge_file(case_010["raw_responses"], conditions=cond, job_id="m1-case-010")
    assert report.verdict.final_verdict == JudgeVerdictClass.UNCERTAIN
    assert report.verdict.final_verdict != JudgeVerdictClass.SYNTHETIC
    assert report.verdict.final_verdict != JudgeVerdictClass.INTEGRITY_UNKNOWN


def test_guard_2b_blocks_secondary_proxy_solo_synthetic():
    """Secondary proxy (rPPG) cannot solo-certify SYNTHETIC at arbitration or post-LLM Guard 2B."""
    judge = JudgeAgent()
    # Case A: primary missing (None), syncnet not_applicable -> never SYNTHETIC (INTEGRITY_UNKNOWN)
    raw_outage = {
        "video-classifier": None,
        "rppg": {
            "job_id": "g2b-test-a",
            "score": 0.95,
            "confidence": 0.90,
            "verdict": "synthetic",
            "estimated_bpm": 72.0,
            "input_quality": 1.0,
            "evidence": {"claim": "Anomalous BVP spectral envelope.", "flags": []},
        },
        "syncnet": {
            "job_id": "g2b-test-a",
            "confidence": 0.50,
            "raw_score": 0.0,
            "evidence": {"claim": "No audio.", "flags": ["not_applicable"]},
        },
    }
    cond = OperatingConditions(duration_seconds=5.0, mean_luminance=80.0, audio_present=False, face_detected=True)
    report_a = judge.judge_file(raw_outage, conditions=cond, job_id="g2b-test-a")
    assert report_a.verdict.final_verdict == JudgeVerdictClass.INTEGRITY_UNKNOWN
    assert report_a.verdict.final_verdict != JudgeVerdictClass.SYNTHETIC

    # Case B: primary borderline (0.62 INCONCLUSIVE), rPPG 0.95 synthetic, syncnet advisory gap
    raw_borderline_primary = {
        "video-classifier": {
            "job_id": "g2b-test-b",
            "confidence": 0.62,
            "verdict": "inconclusive",
            "model_version": "efficientnet-b0-v1.0",
            "evidence": {"claim": "Borderline spatial score.", "flags": ["uncertain_zone"]},
        },
        "rppg": {
            "job_id": "g2b-test-b",
            "score": 0.95,
            "confidence": 0.90,
            "verdict": "synthetic",
            "estimated_bpm": 72.0,
            "input_quality": 1.0,
            "evidence": {"claim": "Anomalous BVP spectral envelope.", "flags": []},
        },
        "syncnet": {
            "job_id": "g2b-test-b",
            "confidence": 0.50,
            "raw_score": 0.0,
            "evidence": {"claim": "No audio.", "flags": ["not_applicable"]},
        },
    }
    report_b = judge.judge_file(raw_borderline_primary, conditions=cond, job_id="g2b-test-b")
    assert report_b.verdict.final_verdict == JudgeVerdictClass.UNCERTAIN
    assert report_b.verdict.calibrated_score < 0.70

    # Also verify Round 3 Guard 2B explicitly overrides an unguarded/LLM SYNTHETIC ruling
    claims = wrap_video_detector_outputs(raw_borderline_primary, conditions=cond)
    analysis = evaluate_disagreement(claims)
    unguarded_verdict = CourtAdmissibleVerdict(
        verdict_id="verdict-g2b",
        job_id="g2b-test-b",
        final_verdict=JudgeVerdictClass.SYNTHETIC,
        calibrated_score=0.92,
        confidence_interval=[0.85, 0.98],
        arbitration_mode="llm_assisted",
        forensic_justification="Simulated unguarded LLM synthetic ruling.",
        siem_alert_tier="P1_CRITICAL",
        evidence_manifest_hash="0" * 64,
    )
    guarded, guards = judge.apply_judge_guards(unguarded_verdict, analysis, claims, conditions=cond)
    assert guarded.final_verdict == JudgeVerdictClass.UNCERTAIN
    assert guarded.calibrated_score <= 0.58
    assert any("Guard 2B" in g for g in guards)


def test_month1_frozen_abstention_under_30pct_zero_fa_zero_fs():
    """Month 1 20 cases under frozen weights: INTEGRITY_UNKNOWN < 30%, 0 FA, 0 FS, 020 remains unknown."""
    cases = json.loads(MONTH1_PATH.read_text(encoding="utf-8"))
    judge = JudgeAgent(apply_calibrated_video_checkpoint=False)

    verdicts = {}
    false_auth = 0
    false_synth = 0
    for c in cases:
        cond = OperatingConditions(**c["operating_conditions"])
        rep = judge.judge_file(c["raw_responses"], conditions=cond, job_id=c["case_id"])
        v = rep.verdict.final_verdict.value
        verdicts[c["case_id"]] = v
        if c["true_label"] == "fake" and v == "AUTHENTIC":
            false_auth += 1
        if c["true_label"] == "real" and v == "SYNTHETIC":
            false_synth += 1

    iu_pct = sum(1 for v in verdicts.values() if v == "INTEGRITY_UNKNOWN") / len(cases)
    assert iu_pct < 0.30, f"Expected INTEGRITY_UNKNOWN < 30%, got {iu_pct:.1%}"
    assert false_synth == 0
    assert false_auth == 0
    assert verdicts["m1-case-020"] == "INTEGRITY_UNKNOWN"


def test_month1_calibrated_video_checkpoint_mode_drops_total_non_decisive_under_30pct():
    """When calibrated video checkpoint lands, both INTEGRITY_UNKNOWN and total non-decisive < 30%."""
    from eval.scripts.run_judge_eval import _build_video_checkpoint_cases

    base_cases = json.loads(MONTH1_PATH.read_text(encoding="utf-8"))
    cal_cases, _ = _build_video_checkpoint_cases(base_cases, video_scores_csv=None)
    judge = JudgeAgent(apply_calibrated_video_checkpoint=True)

    iu_count = 0
    unc_count = 0
    false_auth = 0
    false_synth = 0
    for c in cal_cases:
        cond = OperatingConditions(**c["operating_conditions"])
        v = judge.judge_file(c["raw_responses"], conditions=cond, job_id=c["case_id"]).verdict.final_verdict.value
        if v == "INTEGRITY_UNKNOWN":
            iu_count += 1
        elif v == "UNCERTAIN":
            unc_count += 1
        if c["true_label"] == "fake" and v == "AUTHENTIC":
            false_auth += 1
        if c["true_label"] == "real" and v == "SYNTHETIC":
            false_synth += 1

    assert (iu_count / len(cal_cases)) < 0.30
    assert ((iu_count + unc_count) / len(cal_cases)) < 0.30
    assert false_auth == 0
    assert false_synth == 0


def test_image_and_text_suites_abstention_under_30pct():
    judge = JudgeAgent()
    for path in (IMAGE_PATH, TEXT_PATH):
        cases = json.loads(path.read_text(encoding="utf-8"))
        iu = 0
        unc = 0
        fa = 0
        for c in cases:
            cond = OperatingConditions(**(c.get("operating_conditions") or {}))
            rep = judge.judge_file(c["raw_responses"], conditions=cond, job_id=c["case_id"])
            v = rep.verdict.final_verdict.value
            if v == "INTEGRITY_UNKNOWN":
                iu += 1
            elif v == "UNCERTAIN":
                unc += 1
            if c["true_label"] == "fake" and v == "AUTHENTIC":
                fa += 1
            if path == IMAGE_PATH:
                assert v in c["expected_allowed_verdicts"], f"{c['case_id']} got {v}, expected {c['expected_allowed_verdicts']}"
        assert (iu + unc) / len(cases) < 0.30, f"{path.name} non-decisive exceeded 30%"
        assert fa == 0, f"{path.name} had {fa} false-authentics"


def test_wrapper_and_bridge_preserve_image_text_not_applicable():
    # claim_wrapper handles not_applicable cleanly
    c_img = wrap_detector_response(
        "detector_image",
        {"job_id": "na1", "status": "not_applicable", "confidence": 0.5, "evidence": {"claim": "Corrupt image", "flags": []}},
    )
    assert c_img.polarity == ClaimPolarity.NOT_APPLICABLE
    assert c_img.coverage_gap is True

    c_txt = wrap_detector_response(
        "detector_text",
        {"job_id": "na2", "status": "not_applicable", "confidence": 0.5, "evidence": {"claim": "Too short", "flags": ["text_too_short"]}},
    )
    assert c_txt.polarity == ClaimPolarity.NOT_APPLICABLE
    assert c_txt.coverage_gap is True

    # orchestrator judge_bridge forwards not_applicable rather than dropping to None
    dr = DetectorResult(
        detector="detector_text",
        status="not_applicable",
        job_id="br-1",
        confidence=0.5,
        evidence=DetectorEvidence(claim="Too short", flags=["text_too_short"]),
    )
    raw = build_raw_responses([dr])
    assert raw["detector_text"] is not None
    assert raw["detector_text"]["status"] == "not_applicable"


def test_run_judge_eval_video_scores_csv_cli(tmp_path: Path):
    """Verify --video-scores-csv and --suite video_checkpoint end-to-end execution."""
    csv_in = tmp_path / "scores.csv"
    with open(csv_in, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["sample_path", "det_video_classifier_confidence"])
        w.writeheader()
        w.writerow({"sample_path": "eval/data/video_subset/real/067.mp4", "det_video_classifier_confidence": "0.14"})

    out_md = tmp_path / "out.md"
    out_csv = tmp_path / "out.csv"
    cmd = [
        sys.executable,
        str(REPO_ROOT / "eval" / "scripts" / "run_judge_eval.py"),
        "--suite",
        "video_checkpoint",
        "--video-scores-csv",
        str(csv_in),
        "--out-md",
        str(out_md),
        "--out-csv",
        str(out_csv),
    ]
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)
    rows = list(csv.DictReader(out_csv.open(encoding="utf-8")))
    row_010 = next(r for r in rows if r["case_id"] == "m1-case-010")
    assert row_010["verdict"] == "AUTHENTIC"
    assert "067.mp4" in out_md.read_text(encoding="utf-8")
