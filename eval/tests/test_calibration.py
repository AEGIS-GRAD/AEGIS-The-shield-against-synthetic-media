"""
Unit and Integration Tests for AEGIS Task 3 Calibration Module
==============================================================
Tests:
  - Platt scaling, Temperature scaling, and Isotonic regression
  - ECE, MCE, and Brier score calculations
  - Saving and loading calibrator parameters
  - Reliability diagram generation (PNG & PDF)
  - Modality dataset loaders (audio, image, text, video)
  - Modular video checkpoint calibration
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import numpy as np
import pytest

from eval.calibration.calibrators import (
    BaseCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    TemperatureCalibrator,
    get_calibrator,
)
from eval.calibration.datasets import (
    get_calibration_dataset,
    load_audio_calibration_data,
    load_image_calibration_data,
    load_text_calibration_data,
    load_video_calibration_data,
)
from eval.calibration.metrics import compute_calibration_comparison, compute_ece
from eval.calibration.visualization import plot_reliability_diagram


# ── 1. Calibrator Unit Tests ──────────────────────────────────────────────────

def test_platt_calibrator_fit_and_predict():
    """Platt scaling should fit logistic curve and reduce calibration error."""
    np.random.seed(42)
    # Generate overconfident probabilities
    logits = np.random.normal(0.0, 2.0, size=200)
    # Ground truth generated with milder slope
    true_probs = 1.0 / (1.0 + np.exp(-0.5 * logits))
    labels = (np.random.rand(200) < true_probs).astype(int)
    raw_probs = 1.0 / (1.0 + np.exp(-logits))

    calibrator = PlattCalibrator()
    calibrator.fit(raw_probs, labels)
    assert calibrator.is_fitted is True

    calibrated = calibrator.predict_proba(raw_probs)
    assert calibrated.shape == (200,)
    assert np.all(calibrated >= 0.0) and np.all(calibrated <= 1.0)

    # ECE should improve
    before_ece = compute_ece(raw_probs, labels)["ece"]
    after_ece = compute_ece(calibrated, labels)["ece"]
    assert after_ece <= before_ece


def test_temperature_calibrator_fit_and_predict():
    """Temperature scaling should optimize T > 0 and preserve ranking order."""
    np.random.seed(42)
    logits = np.random.normal(0.0, 2.5, size=200)
    true_probs = 1.0 / (1.0 + np.exp(-0.8 * logits))
    labels = (np.random.rand(200) < true_probs).astype(int)
    raw_probs = 1.0 / (1.0 + np.exp(-logits))

    calibrator = TemperatureCalibrator()
    calibrator.fit(raw_probs, labels)
    assert calibrator.is_fitted is True
    assert calibrator.temperature > 0.0

    calibrated = calibrator.predict_proba(raw_probs)
    assert calibrated.shape == (200,)
    assert np.all(calibrated >= 0.0) and np.all(calibrated <= 1.0)

    # Monotonicity: ranking order must be strictly preserved
    assert np.all(np.argsort(raw_probs) == np.argsort(calibrated))


def test_isotonic_calibrator_fit_and_monotonicity():
    """Isotonic regression must be non-decreasing."""
    np.random.seed(42)
    raw_probs = np.linspace(0.01, 0.99, 100)
    labels = (raw_probs + np.random.normal(0.0, 0.1, 100) > 0.5).astype(int)

    calibrator = IsotonicCalibrator()
    calibrator.fit(raw_probs, labels)
    assert calibrator.is_fitted is True

    calibrated = calibrator.predict_proba(raw_probs)
    # Check non-decreasing monotonicity
    diffs = np.diff(calibrated)
    assert np.all(diffs >= -1e-7)


def test_calibrator_serialization_roundtrip():
    """All calibrators should save to JSON and restore identically."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        scores = np.array([0.1, 0.3, 0.4, 0.7, 0.8, 0.9])
        labels = np.array([0, 0, 0, 1, 1, 1])

        # Platt
        p_cal = PlattCalibrator().fit(scores, labels)
        p_file = tmp_path / "platt.json"
        p_cal.save(p_file)
        p_loaded = BaseCalibrator.load(p_file)
        assert isinstance(p_loaded, PlattCalibrator)
        assert np.allclose(p_cal.predict_proba(scores), p_loaded.predict_proba(scores))

        # Temperature
        t_cal = TemperatureCalibrator().fit(scores, labels)
        t_file = tmp_path / "temp.json"
        t_cal.save(t_file)
        t_loaded = BaseCalibrator.load(t_file)
        assert isinstance(t_loaded, TemperatureCalibrator)
        assert np.allclose(t_cal.predict_proba(scores), t_loaded.predict_proba(scores))

        # Isotonic
        i_cal = IsotonicCalibrator().fit(scores, labels)
        i_file = tmp_path / "iso.json"
        i_cal.save(i_file)
        i_loaded = BaseCalibrator.load(i_file)
        assert isinstance(i_loaded, IsotonicCalibrator)
        assert np.allclose(i_cal.predict_proba(scores), i_loaded.predict_proba(scores))


# ── 2. Metrics Unit Tests ─────────────────────────────────────────────────────

def test_compute_ece_perfect_calibration():
    """Perfect predictions should yield near-zero ECE."""
    # 50 samples with prob 0.0 labeled 0; 50 samples with prob 1.0 labeled 1
    probs = np.array([0.05] * 50 + [0.95] * 50)
    labels = np.array([0] * 50 + [1] * 50)
    metrics = compute_ece(probs, labels, n_bins=10)
    assert metrics["ece"] < 0.10
    assert metrics["brier_score"] < 0.05


def test_compute_ece_severe_miscalibration():
    """Overconfident inverted predictions should yield high ECE and Brier score."""
    probs = np.array([0.99] * 50 + [0.01] * 50)
    labels = np.array([0] * 50 + [1] * 50)
    metrics = compute_ece(probs, labels, n_bins=10)
    assert metrics["ece"] > 0.85
    assert metrics["brier_score"] > 0.80


# ── 3. Visualisation Unit Tests ───────────────────────────────────────────────

def test_plot_reliability_diagram_generation():
    """plot_reliability_diagram should write both PNG and PDF files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_dest = Path(tmpdir) / "test_diagram.png"
        np.random.seed(7)
        before = np.random.uniform(0.1, 0.9, size=60)
        labels = (before > 0.5).astype(int)
        after = (before + labels) / 2.0

        out_path = plot_reliability_diagram(
            before_probs=before,
            after_probs=after,
            labels=labels,
            modality="test_modality",
            method="platt",
            save_path=tmp_dest,
        )

        assert out_path.is_file()
        assert out_path.stat().st_size > 1000
        # Corresponding PDF must also be created
        pdf_path = out_path.with_suffix(".pdf")
        assert pdf_path.is_file()
        assert pdf_path.stat().st_size > 1000


# ── 4. Dataset Loader Unit Tests ──────────────────────────────────────────────

@pytest.mark.parametrize("modality", ["audio", "image", "text", "video"])
def test_modality_datasets_load_cleanly(modality):
    """Every supported modality dataset loader must return matching arrays and metadata."""
    scores, labels, meta = get_calibration_dataset(modality)
    assert len(scores) >= 50
    assert len(scores) == len(labels)
    assert np.all((scores >= 0.0) & (scores <= 1.0))
    assert set(np.unique(labels)).issubset({0, 1})
    assert meta["modality"] == modality


def test_video_checkpoint_modular_dropin():
    """Passing a custom checkpoint path to video calibration must be accepted."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    finetuned_ckpt = repo_root / "detectors" / "video-classifier" / "models" / "efficientnet_b0_ffpp_finetuned.pth"

    scores, labels, meta = load_video_calibration_data(checkpoint_path=str(finetuned_ckpt))
    assert len(scores) == 100
    assert meta["checkpoint_name"] == "efficientnet_b0_ffpp_finetuned.pth"
