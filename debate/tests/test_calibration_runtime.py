"""
Unit tests for Task 7 runtime calibration bridge (`debate/calibration.py`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from debate.calibration import CalibratorRegistry, LoadedCalibrator, apply_default_calibration


def test_registry_loads_heldout_text_calibrator_and_skips_synthetic_placeholders(tmp_path: Path):
    synth = {
        "calibrator_type": "platt",
        "name": "platt",
        "a": 2.1,
        "b": 0.45,
        "input_is_probability": True,
        "metadata": {"num_samples": 100, "source": "synthetic_placeholder"},
    }
    heldout = {
        "calibrator_type": "platt",
        "name": "platt",
        "a": 1.15,
        "b": -0.25,
        "input_is_probability": True,
        "metadata": {"num_samples": 72, "source": "heldout_real"},
    }
    (tmp_path / "video_platt_calibrator.json").write_text(json.dumps(synth), encoding="utf-8")
    (tmp_path / "detector_text_platt_calibrator.json").write_text(json.dumps(heldout), encoding="utf-8")

    reg = CalibratorRegistry(checkpoints_dir=tmp_path)

    # Synthetic placeholder must NOT distort probabilities by default
    vc_out = reg.calibrate_score("video-classifier", 0.50, model_version="v2")
    assert vc_out.calibrator_applied is False
    assert vc_out.calibrated_confidence == 0.50
    assert vc_out.provenance == "synthetic_placeholder_skipped"

    # Opt-in synthetic override works when explicitly enabled
    vc_forced = reg.calibrate_score("video-classifier", 0.50, model_version="v2", force_apply=True)
    assert vc_forced.calibrator_applied is True
    assert vc_forced.calibrated_confidence != 0.50

    # Real held-out calibrator applies automatically
    txt_out = reg.calibrate_score("detector_text", 0.70, model_version="desklib-v1.01-fp16")
    assert txt_out.calibrator_applied is True
    assert txt_out.provenance == "heldout_real"
    assert txt_out.checkpoint_name == "detector_text_platt_calibrator.json"
    assert 0.0 < txt_out.calibrated_confidence < 0.70


def test_uncalibrated_baseline_model_version_is_passed_through():
    reg = CalibratorRegistry(apply_calibrated_video_checkpoint=False)
    out = reg.calibrate_score("video-classifier", 0.6111, model_version="efficientnet-b0-v1.0")
    assert out.calibrator_applied is False
    assert out.calibrated_confidence == 0.6111
    assert out.provenance == "uncalibrated_baseline_checkpoint"


def test_coverage_gap_never_calibrated():
    reg = CalibratorRegistry()
    out = reg.calibrate_score("detector_text", 0.50, coverage_gap=True)
    assert out.calibrator_applied is False
    assert out.provenance == "coverage_gap"


def test_loaded_calibrator_supports_temperature_and_isotonic():
    temp_cal = LoadedCalibrator(
        calibrator_type="temperature",
        checkpoint_name="temp.json",
        params={"temperature": 2.0, "input_is_probability": True},
        metadata={"source": "heldout_real"},
    )
    # T > 1 softens extreme confidence toward 0.50
    softened = temp_cal.predict(0.90)
    assert 0.50 < softened < 0.90

    iso_cal = LoadedCalibrator(
        calibrator_type="isotonic",
        checkpoint_name="iso.json",
        params={"x_thresholds": [0.0, 0.5, 1.0], "y_thresholds": [0.05, 0.45, 0.92]},
        metadata={"source": "heldout_real"},
    )
    assert iso_cal.predict(0.25) == pytest.approx(0.25, abs=1e-6)
    assert iso_cal.predict(0.75) == pytest.approx(0.685, abs=1e-6)


def test_default_registry_applies_repo_heldout_text_calibrator():
    cal_val, outcome = apply_default_calibration("detector_text", 0.75, model_version="desklib-v1.01-fp16")
    assert outcome.calibrator_applied is True
    assert outcome.checkpoint_name == "detector_text_platt_calibrator.json"
    assert 0.0 < cal_val < 1.0
