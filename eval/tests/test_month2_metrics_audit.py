"""
Unit and Golden Tests for Month 2 Metrics Auditor.
=================================================
Validates mathematical re-derivation of all metrics, edge cases on synthetic
rows, and golden outputs against committed benchmark CSV data.
"""

from pathlib import Path
import pytest
from eval.scripts.month2_metrics_audit import (
    audit_judge_cases,
    audit_planner_cases,
    audit_surveillance_cases,
    run_full_audit,
    verify_summary_doc,
    RAW_CSV_PATH,
    SUMMARY_MD_PATH,
)


def test_audit_judge_synthetic_rows():
    """Validates judge arithmetic on small synthetic cases."""
    rows = [
        # 1. Authentic correct
        {"parameter2": "REAL", "parameter3": "P4_INFORMATIONAL", "m1_metric": "AUTHENTIC(0.20)", "m2_metric": "AUTHENTIC(0.15)"},
        # 2. Synthetic correct
        {"parameter2": "FAKE", "parameter3": "P1_CRITICAL", "m1_metric": "SYNTHETIC(0.80)", "m2_metric": "SYNTHETIC(0.85)"},
        # 3. Abstention (INTEGRITY_UNKNOWN) on FAKE -> prevents false-auth
        {"parameter2": "FAKE", "parameter3": "P2_ELEVATED", "m1_metric": "UNCERTAIN(0.40)", "m2_metric": "INTEGRITY_UNKNOWN(0.35)"},
        # 4. Abstention (INTEGRITY_UNKNOWN) on REAL
        {"parameter2": "REAL", "parameter3": "P2_ELEVATED", "m1_metric": "UNCERTAIN(0.45)", "m2_metric": "INTEGRITY_UNKNOWN(0.40)"},
        # 5. False-synthetic: REAL video classified as SYNTHETIC
        {"parameter2": "REAL", "parameter3": "P1_CRITICAL", "m1_metric": "AUTHENTIC(0.30)", "m2_metric": "SYNTHETIC(0.75)"},
    ]

    metrics = audit_judge_cases(rows)
    assert metrics["total_cases"] == 5
    # Decisive verdicts: 3 (rows 1, 2, 5)
    assert metrics["decisive_verdicts"] == 3
    # Strict correct: rows 1 and 2 = 2
    assert metrics["strict_correct"] == 2
    assert metrics["strict_accuracy"] == 0.4  # 2/5
    # Decisive precision: 2/3 = 0.6667
    assert metrics["decisive_precision"] == 0.6667
    # Coverage rate: 3/5 = 0.6
    assert metrics["coverage_rate"] == 0.6
    # Abstention: 2 (rows 3, 4)
    assert metrics["abstention_count"] == 2
    assert metrics["abstention_rate"] == 0.4
    # False-authentics: 0
    assert metrics["false_authentics"] == 0
    # False-synthetics: 1 (row 5)
    assert metrics["false_synthetics"] == 1
    # Month 1 false-authentics: row 3 (FAKE with m1_metric UNCERTAIN resolved to AUTHENTIC)
    assert metrics["month1_false_authentics"] == 1


def test_audit_planner_synthetic_rows():
    """Validates planner divergence and empty plan tracking."""
    rows = [
        {"m1_metric": "rppg+aasist", "m2_metric": "rppg+aasist", "delta_or_status": "cost_delta:0.0ms"},
        {"m1_metric": "video-classifier+rppg", "m2_metric": "rppg", "delta_or_status": "cost_delta:-420.0ms"},
        {"m1_metric": "aasist", "m2_metric": "", "delta_or_status": "cost_delta:-235.0ms"},
    ]

    metrics = audit_planner_cases(rows)
    assert metrics["total_samples"] == 3
    assert metrics["agreements"] == 1
    assert metrics["divergence_count"] == 2
    assert metrics["empty_plans"] == 1
    assert metrics["mean_cost_delta_ms"] == round((-420.0 - 235.0) / 3, 1)


def test_audit_surveillance_synthetic_rows():
    """Validates surveillance scenario aggregation."""
    rows = [
        {"parameter1": "EVALUATED", "parameter2": "ratio:0.160", "parameter3": "p95:52.0ms", "delta_or_status": "PASS"},
        {"parameter1": "EVALUATED", "parameter2": "ratio:0.180", "parameter3": "p95:70.0ms", "delta_or_status": "PASS"},
        {"parameter1": "SKIPPED", "parameter2": "ratio:0.0", "parameter3": "p95:0.0ms", "delta_or_status": "PASS"},
    ]

    metrics = audit_surveillance_cases(rows)
    assert metrics["total_scenarios"] == 3
    assert metrics["active_scenarios"] == 2
    assert metrics["skipped_scenarios"] == 1
    assert metrics["passes"] == 2
    assert metrics["accuracy_pct"] == 100.0
    assert metrics["min_realtime_ratio"] == 0.16
    assert metrics["max_realtime_ratio"] == 0.18
    assert metrics["min_p95_ms"] == 52.0
    assert metrics["max_p95_ms"] == 70.0


def test_golden_metrics_against_committed_csv():
    """
    Golden test asserting exact verified values against the committed
    month2_vs_month1_full_benchmark_raw.csv file.
    """
    assert RAW_CSV_PATH.exists(), f"Raw CSV missing: {RAW_CSV_PATH}"
    audit = run_full_audit(RAW_CSV_PATH)

    j = audit["judge"]
    p = audit["planner"]
    s = audit["surveillance"]

    # Judge Golden Asserts
    assert j["total_cases"] == 20
    assert j["strict_correct"] == 6
    assert j["strict_accuracy"] == 0.30
    assert j["decisive_verdicts"] == 7
    assert j["decisive_correct"] == 6
    assert j["decisive_precision"] == 0.8571
    assert j["coverage_rate"] == 0.35
    assert j["abstention_count"] == 13
    assert j["abstention_rate"] == 0.65
    assert j["false_authentics"] == 0
    assert j["false_synthetics"] == 1
    assert j["month1_baseline_correct"] == 11
    assert j["month1_baseline_accuracy"] == 0.55
    assert j["month1_false_authentics"] == 9

    # Planner Golden Asserts
    assert p["total_samples"] == 19
    assert p["agreements"] == 6
    assert p["divergence_count"] == 13
    assert p["divergence_rate"] == 0.6842
    assert p["empty_plans"] == 1

    # Surveillance Golden Asserts
    assert s["total_scenarios"] == 9
    assert s["active_scenarios"] == 8
    assert s["skipped_scenarios"] == 1
    assert s["passes"] == 8
    assert s["accuracy_pct"] == 100.0
    assert s["min_realtime_ratio"] == 0.156
    assert s["max_realtime_ratio"] == 0.177


def test_summary_doc_audit_check_passes():
    """Verifies that docs/month2_ai_track_summary.md passes the --check audit assertion."""
    assert SUMMARY_MD_PATH.exists(), f"Summary doc missing: {SUMMARY_MD_PATH}"
    audit = run_full_audit(RAW_CSV_PATH)
    matched, msg = verify_summary_doc(SUMMARY_MD_PATH, audit)
    assert matched is True, f"Audit block check failed: {msg}"
