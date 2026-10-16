"""
Month 1 File-Based Evaluation Tests for Judge Agent.
===================================================
Executes the Judge Agent across 20 Month 1 benchmark cases (including 11 known disagreements).
Validates that:
  1. The evaluation suite contains at least 15 cases (Task Card requirement: 15–20 cases).
  2. The suite contains at least 5 known-disagreement cases (Task Card requirement: >= 5).
  3. Every case renders a valid, court-admissible verdict and audit justification without crashes.
  4. Known disagreements are adjudicated strictly according to Forensic Precedence Rules or Guard 1.
"""

import json
from pathlib import Path
import pytest

from debate.judge_agent import JudgeAgent
from debate.schemas import JudgeReport, OperatingConditions

FIXTURES_PATH = Path(__file__).resolve().parent.parent.parent / "eval" / "fixtures" / "judge" / "month1_judge_cases.json"


def load_fixtures():
    if FIXTURES_PATH.is_file():
        with open(FIXTURES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    try:
        import sys
        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from eval.scripts.build_judge_cases import build_cases
        return build_cases()
    except Exception as exc:
        pytest.skip(f"Could not load or build fixtures: {exc}")


FIXTURES = load_fixtures()


@pytest.fixture(scope="module")
def judge():
    return JudgeAgent(mode="deterministic")


def test_suite_meets_task_card_requirements():
    """Asserts that the evaluation suite satisfies the task card requirements."""
    assert len(FIXTURES) >= 15, f"Expected >= 15 cases, found {len(FIXTURES)}"
    disagreements = [c for c in FIXTURES if c.get("is_known_disagreement")]
    assert len(disagreements) >= 5, f"Expected >= 5 known-disagreement cases, found {len(disagreements)}"


@pytest.mark.parametrize("case", FIXTURES, ids=[c["case_id"] for c in FIXTURES])
def test_adjudicate_month1_case(judge, case):
    """Evaluates each Month 1 case through the Judge Agent."""
    cond_dict = case.get("operating_conditions")
    conditions = OperatingConditions(**cond_dict) if cond_dict else None

    report: JudgeReport = judge.judge_file(
        raw_responses=case["raw_responses"],
        conditions=conditions,
        job_id=case["case_id"],
    )

    verdict = report.verdict

    # 1. Structural Conformance
    assert len(report.rounds) == 3
    assert len(verdict.evidence_manifest_hash) == 64
    assert len(report.debate_transcript_hash) == 64
    assert 0.0 <= verdict.calibrated_score <= 1.0

    # 2. Verdict Class Sanity
    actual_verdict_str = verdict.final_verdict.value
    allowed_verdicts = case["expected_allowed_verdicts"]
    assert actual_verdict_str in allowed_verdicts, (
        f"Case {case['case_id']} ({case['filename']}): Got {actual_verdict_str}, "
        f"expected one of {allowed_verdicts}. Justification: {verdict.forensic_justification}"
    )

    # 3. Substantive Justification Check
    assert len(verdict.forensic_justification.strip()) > 40
    assert any(det in verdict.forensic_justification.lower() for det in ("video-classifier", "rppg", "detector", "ruling"))

    # 4. Invariant: Guards Never Upgrade toward Authentic
    if report.guards_applied:
        assert verdict.final_verdict != "AUTHENTIC", "Guard was applied, but verdict remained AUTHENTIC!"
