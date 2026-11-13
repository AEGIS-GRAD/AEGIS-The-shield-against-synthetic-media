"""
AEGIS Detector Calibration Framework
====================================
Subpackage providing:
  - Per-detector probability calibration (Platt scaling, Temperature scaling, Isotonic regression)
  - Calibration metrics (Expected Calibration Error - ECE, MCE, Brier score)
  - Visualisation (publication-quality Reliability Diagrams before & after calibration)
  - Held-out datasets for audio, image, text, and video
"""

from eval.calibration.calibrators import (
    BaseCalibrator,
    PlattCalibrator,
    TemperatureCalibrator,
    IsotonicCalibrator,
    get_calibrator,
)
from eval.calibration.metrics import (
    compute_ece,
    compute_calibration_comparison,
)
from eval.calibration.visualization import (
    plot_reliability_diagram,
)
from eval.calibration.datasets import (
    get_calibration_dataset,
    load_audio_calibration_data,
    load_image_calibration_data,
    load_text_calibration_data,
    load_video_calibration_data,
)

__all__ = [
    "BaseCalibrator",
    "PlattCalibrator",
    "TemperatureCalibrator",
    "IsotonicCalibrator",
    "get_calibrator",
    "compute_ece",
    "compute_calibration_comparison",
    "plot_reliability_diagram",
    "get_calibration_dataset",
    "load_audio_calibration_data",
    "load_image_calibration_data",
    "load_text_calibration_data",
    "load_video_calibration_data",
]
