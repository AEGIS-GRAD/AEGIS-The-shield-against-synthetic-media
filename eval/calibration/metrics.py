"""
AEGIS Calibration Module — Metrics
===================================
Calculates Expected Calibration Error (ECE), Maximum Calibration Error (MCE),
and Brier Score for probability calibration evaluation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np


def compute_ece(
    probs: Any,
    labels: Any,
    n_bins: int = 10,
) -> Dict[str, Any]:
    """
    Computes Expected Calibration Error (ECE), Maximum Calibration Error (MCE),
    and Brier score on predicted probabilities and binary labels.

    Args:
        probs: Array-like of predicted probabilities in [0.0, 1.0] (probability of class 1 = SYNTHETIC).
        labels: Array-like of ground truth binary labels (0 = AUTHENTIC, 1 = SYNTHETIC).
        n_bins: Number of equal-width bins (default 10).

    Returns:
        Dict containing:
            - 'ece': Expected Calibration Error float in [0.0, 1.0]
            - 'mce': Maximum Calibration Error float in [0.0, 1.0]
            - 'brier_score': Mean squared error between probabilities and labels
            - 'bin_edges': Bin partition boundaries
            - 'bin_accuracies': Empirical positive label fraction per bin
            - 'bin_confidences': Mean confidence per bin
            - 'bin_counts': Number of samples falling in each bin
            - 'total_samples': Sample count
    """
    p = np.asarray(probs, dtype=np.float64).ravel()
    y = np.asarray(labels, dtype=np.float64).ravel()

    if len(p) != len(y):
        raise ValueError(f"Lengths differ: probs ({len(p)}) vs labels ({len(y)})")

    n_samples = len(p)
    if n_samples == 0:
        return {
            "ece": 0.0,
            "mce": 0.0,
            "brier_score": 0.0,
            "bin_edges": [],
            "bin_accuracies": [],
            "bin_confidences": [],
            "bin_counts": [],
            "total_samples": 0,
        }

    # Brier score: MSE
    brier = float(np.mean((p - y) ** 2))

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_accuracies: List[float] = []
    bin_confidences: List[float] = []
    bin_counts: List[int] = []

    ece = 0.0
    mce = 0.0

    for i in range(n_bins):
        low, high = bin_edges[i], bin_edges[i + 1]
        if i == n_bins - 1:
            # Last bin includes the right endpoint 1.0
            in_bin = (p >= low) & (p <= high)
        else:
            in_bin = (p >= low) & (p < high)

        count = int(np.sum(in_bin))
        bin_counts.append(count)

        if count > 0:
            bin_acc = float(np.mean(y[in_bin]))
            bin_conf = float(np.mean(p[in_bin]))
            bin_accuracies.append(bin_acc)
            bin_confidences.append(bin_conf)

            diff = abs(bin_acc - bin_conf)
            ece += (count / n_samples) * diff
            if diff > mce:
                mce = diff
        else:
            bin_accuracies.append(float("nan"))
            bin_confidences.append(float("nan"))

    return {
        "ece": round(float(ece), 4),
        "mce": round(float(mce), 4),
        "brier_score": round(float(brier), 4),
        "bin_edges": [round(float(b), 3) for b in bin_edges],
        "bin_accuracies": [round(a, 4) if not np.isnan(a) else None for a in bin_accuracies],
        "bin_confidences": [round(c, 4) if not np.isnan(c) else None for c in bin_confidences],
        "bin_counts": bin_counts,
        "total_samples": n_samples,
    }


def compute_calibration_comparison(
    uncalibrated_probs: Any,
    calibrated_probs: Any,
    labels: Any,
    n_bins: int = 10,
) -> Dict[str, Any]:
    """Computes before vs after calibration metrics side-by-side."""
    before_metrics = compute_ece(uncalibrated_probs, labels, n_bins=n_bins)
    after_metrics = compute_ece(calibrated_probs, labels, n_bins=n_bins)

    ece_reduction = before_metrics["ece"] - after_metrics["ece"]
    pct_reduction = (ece_reduction / before_metrics["ece"] * 100.0) if before_metrics["ece"] > 0 else 0.0

    return {
        "before": before_metrics,
        "after": after_metrics,
        "ece_reduction": round(float(ece_reduction), 4),
        "ece_reduction_pct": round(float(pct_reduction), 2),
    }
