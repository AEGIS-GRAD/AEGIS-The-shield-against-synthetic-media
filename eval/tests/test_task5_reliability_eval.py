"""
test_task5_reliability_eval.py — Verification & Validation for Task 5 RQ2 Benchmark
=================================================================================
Verifies:
  1. Multi-session paired dataset generation (6+ sessions x 50 inputs/session).
  2. End-to-end Loop OFF vs. Loop ON execution over 6 sessions x 50 inputs:
     - Cold-start parity in Session 1
     - Sharp reduction in failing-condition dispatches & confirmed-wrong overrules in S2..S6
     - 100% nominal condition retention (condition specificity)
     - Compute cost & latency reduction without accuracy or safety regression
  3. Presence & integrity of committed RQ2 artifacts in eval/reports/.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from eval.scripts.run_reliability_loop_eval import (
    generate_session_dataset,
    run_evaluation,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = REPO_ROOT / "eval" / "reports"


def test_generate_session_dataset_stratification():
    sessions = generate_session_dataset(num_sessions=6, batch_size=50, seed=123)
    assert len(sessions) == 6
    for batch in sessions:
        assert len(batch) == 50
        conds = {s.condition for s in batch}
        assert conds == {"low_light", "short_clip", "dubbed_audio", "nominal"}
        labels = {s.ground_truth for s in batch}
        assert labels == {"AUTHENTIC", "SYNTHETIC"}


def test_six_session_fifty_input_loop_comparison(tmp_path: Path):
    res = run_evaluation(
        num_sessions=6,
        batch_size=50,
        seed=2026,
        output_dir=tmp_path,
        budget_s=25.0,
    )

    off_s = res["sessions_loop_off"]
    on_s = res["sessions_loop_on"]
    assert len(off_s) == 6
    assert len(on_s) == 6
    assert all(s["batch_size"] == 50 for s in off_s + on_s)

    # Session 1 cold-start parity before first batch confirmation
    assert off_s[0]["failing_dispatch_rate"] == on_s[0]["failing_dispatch_rate"]

    # Post-adaptation Sessions 2..6
    s_off = res["statistics"]["loop_off"]
    s_on = res["statistics"]["loop_on"]
    tests = res["statistics"]["tests"]

    assert s_off["failing_dispatch_rate"] >= 0.90
    assert s_on["failing_dispatch_rate"] <= 0.20
    assert on_s[-1]["failing_dispatch_rate"] == 0.0
    assert tests["failing_dispatch_p_value"] < 0.001

    # Condition specificity: nominal detectors retained
    assert s_on["nominal_retention_rate"] == 1.0

    # Fewer confirmed overrules, fewer conflicts, lower compute cost, non-degraded accuracy
    assert s_on["total_confirmed_overrules"] < s_off["total_confirmed_overrules"]
    assert s_on["conflict_rate"] < s_off["conflict_rate"]
    assert s_on["mean_compute_cost_s"] < s_off["mean_compute_cost_s"]
    assert s_on["verdict_accuracy"] >= s_off["verdict_accuracy"]
    assert s_on["decisive_coverage"] >= s_off["decisive_coverage"]
    assert s_on["false_authentics"] / max(1, s_on["total_samples"]) <= 0.05
    assert abs(s_on["false_authentics"] - s_off["false_authentics"]) <= 2

    # Output files created
    assert (tmp_path / "task5_reliability_feedback_report.md").exists()
    svg_text = (tmp_path / "task5_reliability_learning_curves.svg").read_text(encoding="utf-8")
    assert "<svg" in svg_text and "Loop ON" in svg_text

    with open(tmp_path / "task5_loop_comparison_sessions.csv", "r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 12  # 6 sessions x 2 arms


def test_committed_task5_reports_present_and_consistent():
    json_path = REPORTS_DIR / "task5_loop_comparison_results.json"
    md_path = REPORTS_DIR / "task5_reliability_feedback_report.md"
    svg_path = REPORTS_DIR / "task5_reliability_learning_curves.svg"
    csv_path = REPORTS_DIR / "task5_loop_comparison_sessions.csv"

    for p in (json_path, md_path, svg_path, csv_path):
        assert p.exists(), f"Missing Task 5 report artifact: {p}"

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["config"]["num_sessions"] >= 6
    assert payload["config"]["batch_size"] == 50
    assert payload["statistics"]["loop_on"]["failing_dispatch_rate"] < payload["statistics"]["loop_off"]["failing_dispatch_rate"]

