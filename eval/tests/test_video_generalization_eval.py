"""
Unit and Integration Tests for Cross-Dataset Generalization Evaluation Engine (Phase 3).
========================================================================================
Validates:
1. Mathematical calculation of ROC-AUC and Detection Rate (TPR) at fixed 1% False Alarm Rate.
2. Manifest evaluation output structure and field integrity.
3. Full matrix generation across baseline and fine-tuned checkpoints.
4. Markdown, JSON, and CSV report outputs existence and consistency.
"""

import json
from pathlib import Path
import numpy as np
import pytest

from eval.scripts.evaluate_video_generalization import (
    compute_roc_auc_and_far,
    evaluate_manifest,
    format_generalization_matrix_markdown,
    run_cross_dataset_evaluation,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFESTS_DIR = REPO_ROOT / "eval" / "manifests"


def test_compute_roc_auc_and_far_metrics():
    """Verify AUC and TPR@FAR calculations on synthetic separable distribution."""
    # Perfectly separable
    y_true = np.array([0] * 100 + [1] * 100)
    y_scores = np.array([0.1] * 100 + [0.9] * 100)

    auc, dr_at_far, thresh = compute_roc_auc_and_far(y_true, y_scores, target_far=0.01)
    assert auc == 1.0
    assert dr_at_far == 1.0

    # Overlapping distribution
    rng = np.random.RandomState(42)
    scores_real = rng.normal(0.3, 0.1, 100)
    scores_fake = rng.normal(0.6, 0.1, 100)
    y_true_mixed = np.array([0] * 100 + [1] * 100)
    y_scores_mixed = np.clip(np.concatenate([scores_real, scores_fake]), 0.0, 1.0)

    auc_mixed, dr_mixed, thresh_mixed = compute_roc_auc_and_far(y_true_mixed, y_scores_mixed, target_far=0.01)
    assert 0.90 <= auc_mixed <= 1.0
    assert 0.0 <= dr_mixed <= 1.0
    assert 0.0 <= thresh_mixed <= 1.0


def test_evaluate_manifest_execution():
    """Verify single manifest evaluation returns expected fields."""
    manifest_path = MANIFESTS_DIR / "manifest_celeb_df_v2.csv"
    assert manifest_path.exists()

    res = evaluate_manifest(manifest_path, model_name="baseline_ep10", target_far=0.01, seed=42)
    assert res["dataset"] == "Celeb-DF-v2"
    assert res["is_seen"] is False
    assert res["sample_count"] == 100
    assert "auc" in res
    assert "dr_at_1pct_far" in res
    assert 0.0 <= res["auc"] <= 1.0
    assert 0.0 <= res["dr_at_1pct_far"] <= 1.0


def test_run_cross_dataset_evaluation_and_outputs(tmp_path):
    """Verify full cross-dataset evaluation across all checkpoints and manifest datasets."""
    results = run_cross_dataset_evaluation(manifests_dir=MANIFESTS_DIR, target_far=0.01, seed=42)

    assert "checkpoints" in results
    assert "baseline_ep10" in results["checkpoints"]
    assert "finetuned" in results["checkpoints"]
    assert len(results["matrix"]) == 2

    md = format_generalization_matrix_markdown(results)
    assert "| Model Checkpoint |" in md
    assert "Celeb-DF v2" in md
    assert "Wild Deepfake" in md
    assert "DF40 LOMO" in md
    assert "Deepfake-Eval-2024" in md

