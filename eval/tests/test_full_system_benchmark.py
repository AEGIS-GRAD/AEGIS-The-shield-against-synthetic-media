"""
eval/tests/test_full_system_benchmark.py
========================================
Unit and regression tests for AEGIS Full-System Benchmark Harness & Deliverables.

Verifies:
  1. Benchmark raw CSV exists, is well-formed, and covers all required modalities.
  2. Summary JSON contains valid metrics, timestamps, and Month 2 movement deltas.
  3. Mathematical functions (compute_auc, compute_ece_and_brier) are mathematically sound.
  4. Dual-threshold evaluation (nominal tau=0.5 vs forensic tau=0.65 abstention band) functions correctly.
  5. Evidence bundle verification achieves 100% precision and tamper detection.
  6. Live surveillance path Real-Time Ratio satisfies SLA constraint (RTR <= 1.0).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import numpy as np
import pytest

from eval.scripts.run_full_system_benchmark import (
    compute_auc,
    compute_ece_and_brier,
    evaluate_binary_predictions,
    evaluate_bundles_modality,
    evaluate_live_path_modality,
    OUTPUT_CSV,
    OUTPUT_JSON,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_auc_math_exact():
    """Verify compute_auc calculates exact area under curve on synthetic arrays."""
    # Perfect separation -> AUC = 1.0
    y_true = np.array([0, 0, 0, 1, 1, 1])
    y_scores_perfect = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
    assert compute_auc(y_true, y_scores_perfect) == pytest.approx(1.0, abs=1e-4)

    # Completely inverted -> AUC = 0.0
    y_scores_inverted = np.array([0.9, 0.8, 0.7, 0.3, 0.2, 0.1])
    assert compute_auc(y_true, y_scores_inverted) == pytest.approx(0.0, abs=1e-4)

    # Random / uniform -> AUC ~ 0.5
    rng = np.random.RandomState(42)
    y_rand_labels = np.array([0] * 500 + [1] * 500)
    y_rand_scores = rng.uniform(0, 1, 1000)
    assert 0.45 <= compute_auc(y_rand_labels, y_rand_scores) <= 0.55


def test_ece_and_brier_math():
    """Verify compute_ece_and_brier on perfectly calibrated vs uncalibrated scores."""
    # Perfect calibration: labels match predicted probabilities exactly
    y_true = np.array([0, 0, 1, 1])
    y_probs = np.array([0.0, 0.0, 1.0, 1.0])
    ece, brier = compute_ece_and_brier(y_probs, y_true, n_bins=5)
    assert ece == pytest.approx(0.0, abs=1e-4)
    assert brier == pytest.approx(0.0, abs=1e-4)

    # Severely uncalibrated: overconfident wrong predictions
    y_wrong_probs = np.array([0.9, 0.9, 0.1, 0.1])
    ece_bad, brier_bad = compute_ece_and_brier(y_wrong_probs, y_true, n_bins=5)
    assert ece_bad > 0.5
    assert brier_bad > 0.5


def test_dual_threshold_evaluation():
    """Verify nominal classification vs forensic uncertainty abstention band [0.35, 0.65]."""
    # 4 samples: 1 clear authentic, 1 clear synthetic, 2 uncertain (in [0.35, 0.65])
    probs = np.array([0.10, 0.40, 0.60, 0.90])
    labels = np.array([0, 0, 1, 1])
    latencies = [10.0, 20.0, 30.0, 40.0]

    res = evaluate_binary_predictions(
        probs=probs,
        labels=labels,
        latencies_ms=latencies,
        nominal_threshold=0.50,
        forensic_low=0.35,
        forensic_high=0.65,
    )

    assert res["n_samples"] == 4
    # All nominal predictions match labels
    assert res["nominal_accuracy"] == 1.0
    # Exactly 2 samples fall in [0.35, 0.65] abstention band
    assert res["abstention_count"] == 2
    assert res["abstention_rate"] == 0.50
    # Decisive samples are 2 (sample 0 and 3), both correct
    assert res["decisive_samples"] == 2
    assert res["decisive_accuracy"] == 1.0
    assert res["decisive_false_authentics"] == 0


def test_evidence_bundles_verification():
    """Verify Role 7 evidence verifier identifies genuine bundles and detects all tampered packages."""
    bundle_res = evaluate_bundles_modality()
    assert bundle_res["modality"] == "bundles"
    assert bundle_res["n_samples"] == 11
    assert bundle_res["nominal_accuracy"] == 1.0
    assert bundle_res["tamper_detection_rate"] == 1.0
    assert bundle_res["mean_latency_ms"] < 50.0  # Offline zero-dep verification is sub-50ms


def test_live_surveillance_real_time_ratio():
    """Verify live surveillance path satisfies strict real-time ratio constraint (RTR <= 1.0)."""
    live_res = evaluate_live_path_modality()
    assert live_res["modality"] == "live_path"
    assert live_res["realtime_pass"] is True
    assert live_res["realtime_ratio"] <= 1.0, f"RTR was {live_res['realtime_ratio']} > 1.0"
    assert live_res["window_duration_budget_ms"] == pytest.approx(266.67, abs=0.1)


def test_benchmark_csv_output_integrity():
    """Verify full_system_benchmark_raw.csv exists, has header, and contains all modalities."""
    assert OUTPUT_CSV.exists(), f"Raw CSV missing at {OUTPUT_CSV}"
    with open(OUTPUT_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    expected_modalities = {"video", "audio", "image", "text", "multimodal_fused", "bundles", "live_path"}
    found_modalities = {r["modality"] for r in rows}
    assert expected_modalities.issubset(found_modalities), f"Missing modalities: {expected_modalities - found_modalities}"

    for r in rows:
        assert float(r["balanced_accuracy"]) >= 0.0
        assert float(r["auc"]) >= 0.50
        assert float(r["ece"]) >= 0.0
        assert float(r["mean_latency_ms"]) > 0.0


def test_benchmark_json_output_and_movement():
    """Verify full_system_benchmark_results.json exists and contains Month 2 comparisons."""
    assert OUTPUT_JSON.exists(), f"Results JSON missing at {OUTPUT_JSON}"
    with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "modalities" in data
    assert "month2_comparison" in data
    assert len(data["month2_comparison"]) >= 6

    directions = {d["direction"] for d in data["month2_comparison"]}
    # Verify honest reporting of both improvements and regressions
    assert "IMPROVED" in directions, "Should contain improved metrics (e.g. Live RTR, Multimodal accuracy)"
    assert "REGRESSED" in directions, "Should honestly report regressions (e.g. Video under stress, compute latency)"
    assert "EXPANDED" in directions, "Should contain newly established baselines (Text, Image, Bundles)"
