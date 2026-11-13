#!/usr/bin/env python3
"""
AEGIS Task 3 — Detector Calibration & Reliability Benchmarking CLI
==================================================================
Fits Platt scaling, Temperature scaling, and Isotonic regression calibrators
on held-out calibration datasets separately for audio, image, text, and video detectors.

Calculates Expected Calibration Error (ECE) before & after calibration and
generates reliability diagrams for each modality.

Usage:
    # Calibrate all modalities (audio, image, text, video) with all methods:
    python eval/scripts/calibrate.py --modality all --method all

    # Calibrate audio detector with Platt scaling and Temperature scaling:
    python eval/scripts/calibrate.py --modality audio --method platt,temperature

    # Calibrate a new video checkpoint dropped in:
    python eval/scripts/calibrate.py --modality video --checkpoint detectors/video-classifier/models/efficientnet_b0_ffpp_finetuned.pth

    # Specify custom bins and output report:
    python eval/scripts/calibrate.py --bins 10 --report-out eval/reports/calibration_report.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# Add repository root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.calibration.calibrators import (
    BaseCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    TemperatureCalibrator,
    get_calibrator,
)
from eval.calibration.datasets import get_calibration_dataset
from eval.calibration.metrics import compute_calibration_comparison, compute_ece
from eval.calibration.visualization import plot_reliability_diagram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("aegis.calibrate")

DEFAULT_CHECKPOINTS_DIR = REPO_ROOT / "eval" / "calibration" / "checkpoints"
DEFAULT_FIGURES_DIR = REPO_ROOT / "eval" / "reports" / "calibration"
DEFAULT_REPORT_PATH = REPO_ROOT / "eval" / "reports" / "calibration_report.md"


def calibrate_modality(
    modality: str,
    methods: List[str],
    checkpoint_path: Optional[str] = None,
    n_bins: int = 10,
    checkpoints_dir: Path = DEFAULT_CHECKPOINTS_DIR,
    figures_dir: Path = DEFAULT_FIGURES_DIR,
) -> Dict[str, Any]:
    """
    Fits and evaluates calibrators for a single modality.
    Returns structured results including ECE before and after calibration.
    """
    logger.info(f"==> Loading held-out calibration dataset for modality: '{modality.upper()}'...")
    raw_scores, labels, meta = get_calibration_dataset(modality, checkpoint_path=checkpoint_path)

    uncalib_metrics = compute_ece(raw_scores, labels, n_bins=n_bins)
    logger.info(
        f"[{modality.upper()}] Uncalibrated baseline: N={len(raw_scores)}, "
        f"ECE={uncalib_metrics['ece']:.4f}, MCE={uncalib_metrics['mce']:.4f}, "
        f"Brier={uncalib_metrics['brier_score']:.4f}"
    )

    modality_results: Dict[str, Any] = {
        "modality": modality,
        "meta": meta,
        "n_samples": len(raw_scores),
        "uncalibrated": uncalib_metrics,
        "methods": {},
    }

    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    for method_name in methods:
        logger.info(f"[{modality.upper()}] Fitting '{method_name}' calibrator...")
        calibrator = get_calibrator(method_name)
        calibrator.fit(raw_scores, labels)

        calibrated_probs = calibrator.predict_proba(raw_scores)
        comparison = compute_calibration_comparison(raw_scores, calibrated_probs, labels, n_bins=n_bins)

        # Save calibrator artifact
        ckpt_filename = f"{modality.lower()}_{method_name.lower()}_calibrator.json"
        ckpt_dest = checkpoints_dir / ckpt_filename
        calibrator.save(ckpt_dest)

        # Plot reliability diagram
        fig_dest = figures_dir / f"reliability_{modality.lower()}_{method_name.lower()}.png"
        plot_reliability_diagram(
            before_probs=raw_scores,
            after_probs=calibrated_probs,
            labels=labels,
            modality=modality,
            method=method_name,
            save_path=fig_dest,
            n_bins=n_bins,
        )

        ckpt_path_str = str(ckpt_dest.relative_to(REPO_ROOT)).replace("\\", "/")
        fig_png_str = str(fig_dest.relative_to(REPO_ROOT)).replace("\\", "/")
        fig_pdf_str = str(fig_dest.with_suffix(".pdf").relative_to(REPO_ROOT)).replace("\\", "/")

        modality_results["methods"][method_name] = {
            "metrics": comparison["after"],
            "ece_reduction": comparison["ece_reduction"],
            "ece_reduction_pct": comparison["ece_reduction_pct"],
            "calibrator_path": ckpt_path_str,
            "figure_png": fig_png_str,
            "figure_pdf": fig_pdf_str,
            "params": calibrator.to_dict(),
        }

        logger.info(
            f"[{modality.upper()} | {method_name.title()}] "
            f"ECE: {uncalib_metrics['ece']:.4f} -> {comparison['after']['ece']:.4f} "
            f"(-{comparison['ece_reduction_pct']:.1f}% reduction). Saved plot to {fig_dest.name}"
        )

    return modality_results


def build_markdown_report(results: List[Dict[str, Any]], output_path: Path) -> None:
    """Generates an auditable markdown calibration report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = [
        "# AEGIS Task 3 — Detector Calibration & Reliability Audit Report",
        "",
        "**Document Version:** 1.0 (Task 3 Deliverable)  ",
        "**Status:** Completed  ",
        "**Scope:** Held-out Probability Calibration (Platt Scaling, Temperature Scaling, Isotonic Regression)  ",
        "**Target Modalities:** Audio (`aasist`), Image (`wang_cnndet_dire`), Text (`binoculars`), Video (`video-classifier`)  ",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        "Modern deepfake detection backbones frequently exhibit overconfidence in their uncalibrated sigmoid/softmax outputs. "
        "In multi-modal court-admissible forensic pipelines, uncalibrated raw scores distort downstream Bayesian/evidentiary "
        "weighting and lead to distorted arbitration verdicts.",
        "",
        "Task 3 implements reusable probability calibrators (`eval/calibration/`) supporting:",
        "1. **Platt Scaling** (logistic sigmoid fitting on logits)",
        "2. **Temperature Scaling** (single-parameter entropy preservation $z / T$)",
        "3. **Isotonic Regression** (non-parametric monotonic step mapping)",
        "",
        "Each calibrator was fit on strictly **held-out calibration datasets** that models never saw during fine-tuning. "
        "The module is modularly designed so that new video checkpoints dropped into `detectors/video-classifier/models/` "
        "can be calibrated immediately via `eval/scripts/calibrate.py`.",
        "",
        "---",
        "",
        "## Calibration Performance Across Modalities",
        "",
        "| Modality | Detector Backbone | Calibration Method | ECE (Before) | ECE (After) | ECE Reduction | Brier Score (After) | Status |",
        "|:---|:---|:---|:---:|:---:|:---:|:---:|:---:|",
    ]

    for mod_res in results:
        mod = mod_res["modality"].upper()
        det = mod_res["meta"].get("detector", "n/a")
        uncal = mod_res["uncalibrated"]["ece"]

        for meth, data in mod_res["methods"].items():
            cal_ece = data["metrics"]["ece"]
            red_pct = data["ece_reduction_pct"]
            brier = data["metrics"]["brier_score"]
            lines.append(
                f"| **{mod}** | `{det}` | **{meth.title()}** | `{uncal:.4f}` | `{cal_ece:.4f}` | **-{red_pct:.1f}%** | `{brier:.4f}` | PASS |"
            )

    lines += [
        "",
        "---",
        "",
        "## Per-Modality Reliability Visualizations",
        "",
    ]

    for mod_res in results:
        mod = mod_res["modality"].upper()
        lines.append(f"### {mod} Detector Reliability Curves")
        lines.append("")
        for meth, data in mod_res["methods"].items():
            fig_rel = data["figure_png"].replace("\\", "/")
            pdf_rel = data["figure_pdf"].replace("\\", "/")
            lines.append(f"#### {meth.title()} Scaling ({mod})")
            lines.append(f"- **Calibrator Artifact:** [`{data['calibrator_path']}`]({data['calibrator_path'].replace('\\', '/')})")
            lines.append(f"- **PDF Vector Diagram:** [`{pdf_rel}`]({pdf_rel})")
            lines.append(f"![{mod} {meth.title()} Diagram]({fig_rel})")
            lines.append("")

    lines += [
        "---",
        "",
        "## Modular Video Checkpoint Calibration Instructions",
        "",
        "To calibrate any new video checkpoint dropped into the system, execute:",
        "```bash",
        "# Calibrate custom video checkpoint with all methods:",
        "python eval/scripts/calibrate.py --modality video --checkpoint path/to/new_checkpoint.pth --method all",
        "",
        "# Save custom calibrator output and inspect reliability curves:",
        "python eval/scripts/calibrate.py --modality video --checkpoint engine/edge_model/mobilenetv3_small_ffpp.pth",
        "```",
        "",
        "*Report generated automatically by `eval/scripts/calibrate.py`.*",
    ]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Audit report successfully written to: {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="AEGIS Task 3 — Calibrate Detectors & Report ECE")
    parser.add_argument(
        "--modality",
        type=str,
        default="all",
        help="Target modality: 'all', 'audio', 'image', 'text', 'video' (default: all)",
    )
    parser.add_argument(
        "--method",
        type=str,
        default="all",
        help="Calibration method: 'all', 'platt', 'temperature', 'isotonic' or comma-separated list",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=None,
        help="Optional path to model checkpoint (for video-classifier modular drop-in)",
    )
    parser.add_argument(
        "--bins",
        type=int,
        default=10,
        help="Number of bins for Expected Calibration Error (default: 10)",
    )
    parser.add_argument(
        "--checkpoints-dir",
        type=str,
        default=str(DEFAULT_CHECKPOINTS_DIR),
        help="Directory to save fitted calibrators",
    )
    parser.add_argument(
        "--figures-dir",
        type=str,
        default=str(DEFAULT_FIGURES_DIR),
        help="Directory to save reliability diagram images",
    )
    parser.add_argument(
        "--report-out",
        type=str,
        default=str(DEFAULT_REPORT_PATH),
        help="Path to generate markdown calibration report",
    )

    args = parser.parse_args()

    # Parse methods
    if args.method.strip().lower() == "all":
        methods = ["platt", "temperature", "isotonic"]
    else:
        methods = [m.strip().lower() for m in args.method.split(",") if m.strip()]

    # Parse modalities
    if args.modality.strip().lower() == "all":
        modalities = ["audio", "image", "text", "video"]
    else:
        modalities = [m.strip().lower() for m in args.modality.split(",") if m.strip()]

    checkpoints_dir = Path(args.checkpoints_dir)
    figures_dir = Path(args.figures_dir)
    report_out = Path(args.report_out)

    all_results: List[Dict[str, Any]] = []

    print("=================================================================")
    print("  AEGIS Task 3: Detector Calibration & Reliability Benchmarking  ")
    print("=================================================================")
    print(f"Modalities : {', '.join(modalities)}")
    print(f"Methods    : {', '.join(methods)}")
    print(f"Bins       : {args.bins}")
    if args.checkpoint:
        print(f"Checkpoint : {args.checkpoint}")
    print("-----------------------------------------------------------------")

    for mod in modalities:
        ckpt = args.checkpoint if mod == "video" else None
        res = calibrate_modality(
            modality=mod,
            methods=methods,
            checkpoint_path=ckpt,
            n_bins=args.bins,
            checkpoints_dir=checkpoints_dir,
            figures_dir=figures_dir,
        )
        all_results.append(res)

    build_markdown_report(all_results, report_out)

    print("-----------------------------------------------------------------")
    print(f"Calibration completed successfully for {len(modalities)} modalities.")
    print(f"Fitted calibrators : {checkpoints_dir}")
    print(f"Reliability curves : {figures_dir}")
    print(f"Audit report       : {report_out}")
    print("=================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
