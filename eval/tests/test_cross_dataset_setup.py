"""
Validation Test Suite for Cross-Dataset Generalization Setup (Phase 1).
======================================================================
Tests:
1. DATA.md contains full documentation for Celeb-DF v2, Wild Deepfake, DF40,
   Deepfake-Eval-2024, and DeepSpeak v2.
2. Licensing and access statuses are properly documented with explicit Day 1 submissions.
3. data_paths.yaml has valid YAML syntax and contains the video_generalization config block.
4. Model checkpoint paths referenced in config exist on disk.
"""

from pathlib import Path
import yaml
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_MD = REPO_ROOT / "eval" / "DATA.md"
CONFIG_YAML = REPO_ROOT / "eval" / "config" / "data_paths.yaml"


def test_data_md_cross_dataset_entries():
    """Verify DATA.md contains all required dataset entries, access statuses, and guidelines."""
    assert DATA_MD.exists(), "eval/DATA.md does not exist"
    content = DATA_MD.read_text(encoding="utf-8")

    # Required datasets
    required_datasets = [
        "Celeb-DF v2",
        "Wild Deepfake",
        "DF40",
        "Deepfake-Eval-2024",
        "DeepSpeak v2",
    ]
    for ds in required_datasets:
        assert ds in content, f"Missing dataset {ds} in eval/DATA.md"

    # Status & day 1 tracking
    assert "PENDING_INSTITUTIONAL_APPROVAL" in content
    assert "PENDING_ACCESS_CONFIRMATION" in content
    assert "Leave-One-Method-Out (LOMO)" in content or "leave-one-method-out" in content.lower()
    assert "TPR @ FAR = 0.01" in content or "1% False-Alarm Rate" in content
    assert "efficientnet_b0_ffpp_ckpt_ep10.pth" in content
    assert "efficientnet_b0_ffpp_finetuned.pth" in content


def test_data_paths_yaml_generalization_block():
    """Verify data_paths.yaml is valid YAML and has the video_generalization configuration."""
    assert CONFIG_YAML.exists(), "eval/config/data_paths.yaml does not exist"
    with open(CONFIG_YAML, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    assert "video_generalization" in cfg, "video_generalization block missing in data_paths.yaml"
    vg = cfg["video_generalization"]

    assert "models" in vg
    assert "raw_roots" in vg
    assert "metrics" in vg
    assert vg["metrics"].get("far_target") == 0.01

    # Verify model files exist in repository
    baseline_rel = vg["models"]["baseline"]
    finetuned_rel = vg["models"]["finetuned"]

    assert (REPO_ROOT / baseline_rel).exists(), f"Baseline model not found at {baseline_rel}"
    assert (REPO_ROOT / finetuned_rel).exists(), f"Finetuned model not found at {finetuned_rel}"

