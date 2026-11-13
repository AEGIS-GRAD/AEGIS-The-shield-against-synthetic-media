"""
AEGIS Calibration Module — Visualization
=========================================
Generates reliability diagrams (reliability curves) before and after calibration.
Saves publication-quality figures in PNG and PDF formats.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union
import numpy as np

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend suitable for headless servers & CI
import matplotlib.pyplot as plt
from eval.calibration.metrics import compute_ece


def plot_reliability_diagram(
    before_probs: Any,
    after_probs: Any,
    labels: Any,
    modality: str,
    method: str,
    save_path: Optional[Union[str, Path]] = None,
    n_bins: int = 10,
) -> Path:
    """
    Renders a publication-ready 2-panel figure:
      Panel 1 (Top): Reliability Curves (Empirical Accuracy vs. Confidence)
                     showing uncalibrated vs. calibrated against ideal y=x line.
      Panel 2 (Bottom): Confidence Histograms (sample count distribution per bin).

    Args:
        before_probs: Uncalibrated probabilities.
        after_probs: Calibrated probabilities.
        labels: Ground truth binary labels (0/1).
        modality: Name of modality ('audio', 'image', 'text', 'video').
        method: Calibration method name ('Platt', 'Temperature', 'Isotonic').
        save_path: Destination path for the plot. If None, saves in eval/reports/calibration/.
        n_bins: Number of bins.

    Returns:
        Path to the saved figure.
    """
    m_before = compute_ece(before_probs, labels, n_bins=n_bins)
    m_after = compute_ece(after_probs, labels, n_bins=n_bins)

    bin_centers = [
        0.5 * (m_before["bin_edges"][i] + m_before["bin_edges"][i + 1])
        for i in range(n_bins)
    ]

    # Filter out empty bins for line plotting
    before_x, before_y = [], []
    for conf, acc in zip(m_before["bin_confidences"], m_before["bin_accuracies"]):
        if conf is not None and acc is not None:
            before_x.append(conf)
            before_y.append(acc)

    after_x, after_y = [], []
    for conf, acc in zip(m_after["bin_confidences"], m_after["bin_accuracies"]):
        if conf is not None and acc is not None:
            after_x.append(conf)
            after_y.append(acc)

    fig, (ax_rel, ax_hist) = plt.subplots(
        2, 1, figsize=(7.5, 8.5), gridspec_kw={"height_ratios": [2.5, 1.0]}, sharex=True
    )
    fig.patch.set_facecolor("#ffffff")

    # ── Panel 1: Reliability Diagram ──────────────────────────────────────────
    ax_rel.set_facecolor("#fafafa")
    ax_rel.plot([0, 1], [0, 1], "k--", alpha=0.65, label="Perfect Calibration (y = x)")

    # Uncalibrated curve
    ax_rel.plot(
        before_x,
        before_y,
        marker="o",
        color="#d9534f",
        linewidth=2.0,
        markersize=6,
        label=f"Before Calibration (ECE = {m_before['ece']:.3f}, Brier = {m_before['brier_score']:.3f})",
    )

    # Calibrated curve
    ax_rel.plot(
        after_x,
        after_y,
        marker="s",
        color="#2b7bba",
        linewidth=2.2,
        markersize=6,
        label=f"After {method.title()} (ECE = {m_after['ece']:.3f}, Brier = {m_after['brier_score']:.3f})",
    )

    ax_rel.set_xlim(-0.02, 1.02)
    ax_rel.set_ylim(-0.02, 1.02)
    ax_rel.set_ylabel("Empirical Accuracy P(Y=1 | Bin)", fontsize=11, fontweight="bold")
    ax_rel.set_title(
        f"Reliability Diagram: {modality.upper()} Detector ({method.title()} Calibration)",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax_rel.grid(True, linestyle=":", alpha=0.5, color="#888888")
    ax_rel.legend(loc="upper left", framealpha=0.9, fontsize=9.5)

    # ── Panel 2: Sample Distribution Histogram ────────────────────────────────
    ax_hist.set_facecolor("#fafafa")
    width = 0.8 / n_bins
    offsets = [c - width * 0.22 for c in bin_centers]
    offsets_after = [c + width * 0.22 for c in bin_centers]

    ax_hist.bar(
        offsets,
        m_before["bin_counts"],
        width=width * 0.44,
        color="#d9534f",
        alpha=0.6,
        label="Before Count",
    )
    ax_hist.bar(
        offsets_after,
        m_after["bin_counts"],
        width=width * 0.44,
        color="#2b7bba",
        alpha=0.6,
        label="After Count",
    )

    ax_hist.set_xlabel("Confidence Bin", fontsize=11, fontweight="bold")
    ax_hist.set_ylabel("Sample Count", fontsize=10)
    ax_hist.grid(True, linestyle=":", alpha=0.5, color="#888888")
    ax_hist.legend(loc="upper center", framealpha=0.9, fontsize=9)

    plt.tight_layout()

    if save_path is None:
        reports_dir = Path(__file__).resolve().parent.parent / "reports" / "calibration"
        reports_dir.mkdir(parents=True, exist_ok=True)
        save_path = reports_dir / f"reliability_{modality.lower()}_{method.lower()}.png"
    else:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

    fig.savefig(save_path, dpi=300, bbox_inches="tight")
    # Also save PDF version for court/academic report inclusion
    pdf_path = save_path.with_suffix(".pdf")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)

    return save_path
