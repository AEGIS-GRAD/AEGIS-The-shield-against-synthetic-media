"""
AEGIS Debate & Arbitration Layer — Runtime Score Calibration Bridge.

Connects Task 3 probability calibrators (Platt scaling, Temperature scaling,
Isotonic regression saved under eval/calibration/checkpoints/) into the Debate
& Judge pipeline without requiring heavy GUI dependencies (e.g. matplotlib).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHECKPOINTS_DIR = _REPO_ROOT / "eval" / "calibration" / "checkpoints"

# Canonical mapping from runtime detector IDs to calibration checkpoints.
# Prefers real held-out detector-specific checkpoints when present, falling back
# to Task 3 modality-level artifacts.
DEFAULT_DETECTOR_CHECKPOINT_PREFERENCES: Dict[str, List[str]] = {
    "video-classifier": [
        "video_classifier_temperature_calibrator.json",
        "video_classifier_platt_calibrator.json",
        "video_temperature_calibrator.json",
        "video_platt_calibrator.json",
    ],
    "detector_image": [
        "detector_image_temperature_calibrator.json",
        "detector_image_platt_calibrator.json",
        "image_temperature_calibrator.json",
        "image_platt_calibrator.json",
    ],
    "image": [
        "detector_image_temperature_calibrator.json",
        "detector_image_platt_calibrator.json",
        "image_temperature_calibrator.json",
        "image_platt_calibrator.json",
    ],
    "detector_text": [
        "detector_text_platt_calibrator.json",
        "detector_text_temperature_calibrator.json",
        "text_platt_calibrator.json",
        "text_temperature_calibrator.json",
    ],
    "aasist": [
        "aasist_temperature_calibrator.json",
        "aasist_platt_calibrator.json",
        "audio_temperature_calibrator.json",
        "audio_platt_calibrator.json",
    ],
    "rppg": [
        "rppg_temperature_calibrator.json",
        "rppg_platt_calibrator.json",
    ],
    "syncnet": [
        "syncnet_temperature_calibrator.json",
        "syncnet_platt_calibrator.json",
    ],
}

# Known fallback/uncalibrated version markers that must NOT be sharply pushed
# into extreme confidence by synthetic/external calibrator slopes.
UNCALIBRATED_MODEL_VERSIONS = {
    "efficientnet-b0-v1.0",  # Month 1 CSV/baseline uninitialized/uncalibrated label
    "random-fallback",
    "uninitialized",
}


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _logit(p: float, eps: float = 1e-6) -> float:
    p_c = min(max(float(p), eps), 1.0 - eps)
    return math.log(p_c / (1.0 - p_c))


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


@dataclass(frozen=True)
class LoadedCalibrator:
    """Pure-Python runtime representation of a fitted Task 3 calibrator JSON."""

    calibrator_type: str
    checkpoint_name: str
    params: Dict[str, Any]
    metadata: Dict[str, Any]

    @property
    def is_placeholder_synthetic(self) -> bool:
        """True if artifact came from Task 3's n=100 simulated Beta dataset."""
        source = str(self.metadata.get("source", "")).lower()
        if source in {"heldout_real", "real_eval", "empirical_heldout"}:
            return False
        if source == "synthetic_placeholder":
            return True
        # Task 3 simulated checkpoints have num_samples == 100 and no explicit source key.
        return "source" not in self.metadata and self.metadata.get("num_samples") == 100

    def predict(self, prob: float) -> float:
        p = _clamp01(prob)
        ctype = self.calibrator_type.lower()
        if ctype == "platt":
            a = float(self.params["a"])
            b = float(self.params["b"])
            input_is_prob = bool(self.params.get("input_is_probability", True))
            z = _logit(p) if input_is_prob else float(prob)
            return _clamp01(_sigmoid(a * z + b))
        if ctype in {"temperature", "temperature_scaling"}:
            temp = max(float(self.params["temperature"]), 1e-4)
            input_is_prob = bool(self.params.get("input_is_probability", True))
            z = _logit(p) if input_is_prob else float(prob)
            return _clamp01(_sigmoid(z / temp))
        if ctype in {"isotonic", "isotonic_regression"}:
            xs: List[float] = self.params.get("x_thresholds") or []
            ys: List[float] = self.params.get("y_thresholds") or []
            if not xs or not ys or len(xs) != len(ys):
                return p
            if p <= xs[0]:
                return _clamp01(ys[0])
            if p >= xs[-1]:
                return _clamp01(ys[-1])
            for idx in range(len(xs) - 1):
                x0, x1 = xs[idx], xs[idx + 1]
                if x0 <= p <= x1:
                    if abs(x1 - x0) < 1e-12:
                        return _clamp01(ys[idx])
                    t = (p - x0) / (x1 - x0)
                    return _clamp01(ys[idx] + t * (ys[idx + 1] - ys[idx]))
            return p
        return p


@dataclass(frozen=True)
class CalibrationOutcome:
    """Audit record returned when calibrating a single detector probability."""

    detector_id: str
    raw_confidence: float
    calibrated_confidence: float
    calibrator_applied: bool
    calibrator_type: str
    checkpoint_name: str
    provenance: str
    note: Optional[str] = None


class CalibratorRegistry:
    """
    Loads Task 3 JSON calibrators and applies provenance-safe probability calibration.

    Key forensic safeguards:
    1. Does NOT amplify uncalibrated/random-weight fallback borderline scores into false certainty.
    2. Guards against Task 3 synthetic-placeholder neutral shift (where Platt b != 0 shifts 0.50 -> 0.59).
    3. Can apply an explicit real checkpoint calibrator or manifest-referenced calibrator file cleanly.
    """

    def __init__(
        self,
        checkpoints_dir: Optional[Path] = None,
        allow_synthetic_placeholders: bool = False,
        apply_calibrated_video_checkpoint: bool = False,
    ) -> None:
        self.checkpoints_dir = Path(checkpoints_dir) if checkpoints_dir else DEFAULT_CHECKPOINTS_DIR
        self.allow_synthetic_placeholders = allow_synthetic_placeholders
        self.apply_calibrated_video_checkpoint = apply_calibrated_video_checkpoint
        self._cache: Dict[str, Optional[LoadedCalibrator]] = {}

    @staticmethod
    def load_file(path: Path) -> LoadedCalibrator:
        data = json.loads(path.read_text(encoding="utf-8"))
        ctype = str(data.get("calibrator_type") or data.get("name") or "unknown")
        return LoadedCalibrator(
            calibrator_type=ctype,
            checkpoint_name=path.name,
            params=data,
            metadata=dict(data.get("metadata", {})),
        )

    def get_calibrator(
        self,
        detector_id: str,
        manifest: Optional[Dict[str, Any]] = None,
    ) -> Optional[LoadedCalibrator]:
        cache_key = f"{detector_id}:{(manifest or {}).get('version', '')}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 1. Check manifest explicit calibration specification if provided
        if manifest and isinstance(manifest.get("calibration"), dict):
            cal_spec = manifest["calibration"]
            ckpt_rel = cal_spec.get("checkpoint")
            if ckpt_rel:
                candidate = _REPO_ROOT / ckpt_rel
                if not candidate.exists():
                    candidate = self.checkpoints_dir / Path(ckpt_rel).name
                if candidate.exists():
                    loaded = self.load_file(candidate)
                    self._cache[cache_key] = loaded
                    return loaded

        # 2. Check preferred checkpoint candidates in checkpoints_dir
        if self.checkpoints_dir.is_dir():
            for filename in DEFAULT_DETECTOR_CHECKPOINT_PREFERENCES.get(detector_id, []):
                candidate = self.checkpoints_dir / filename
                if candidate.exists():
                    loaded = self.load_file(candidate)
                    self._cache[cache_key] = loaded
                    return loaded

        self._cache[cache_key] = None
        return None

    def calibrate_score(
        self,
        detector_id: str,
        raw_confidence: float,
        *,
        model_version: str = "",
        coverage_gap: bool = False,
        manifest: Optional[Dict[str, Any]] = None,
        force_apply: bool = False,
    ) -> CalibrationOutcome:
        """
        Calibrates `raw_confidence` into a well-behaved probability in [0.0, 1.0].

        When the available calibrator is only Task 3's simulated synthetic placeholder
        or the detector emitted from an uncalibrated/random Month 1 baseline version,
        we conservatively pass through the wrapped score rather than sharpening
        borderline errors (e.g., 067.mp4's 0.6111 -> 0.914).
        """
        raw = _clamp01(raw_confidence)

        if coverage_gap:
            return CalibrationOutcome(
                detector_id=detector_id,
                raw_confidence=raw,
                calibrated_confidence=raw,
                calibrator_applied=False,
                calibrator_type="none",
                checkpoint_name="",
                provenance="coverage_gap",
                note="Skipped calibration for coverage-gap / non-applicable claim.",
            )

        mv_lower = (model_version or "").strip().lower()
        is_uncalibrated_mv = mv_lower in UNCALIBRATED_MODEL_VERSIONS and not self.apply_calibrated_video_checkpoint
        if is_uncalibrated_mv and not force_apply:
            return CalibrationOutcome(
                detector_id=detector_id,
                raw_confidence=raw,
                calibrated_confidence=raw,
                calibrator_applied=False,
                calibrator_type="pass_through",
                checkpoint_name="",
                provenance="uncalibrated_baseline_checkpoint",
                note=(
                    f"Model version '{model_version}' marks uncalibrated baseline/fallback weights; "
                    "avoided aggressive calibration stretching."
                ),
            )

        cal = self.get_calibrator(detector_id, manifest=manifest)
        if cal is None:
            return CalibrationOutcome(
                detector_id=detector_id,
                raw_confidence=raw,
                calibrated_confidence=raw,
                calibrator_applied=False,
                calibrator_type="none",
                checkpoint_name="",
                provenance="no_calibrator_available",
            )

        if cal.is_placeholder_synthetic and not (self.allow_synthetic_placeholders or force_apply):
            # Task 3 checkpoints (n=100 simulated Betas) can warp neutral/borderline values
            # if applied blindly. Wait until a real held-out or checkpoint-calibrated JSON lands.
            return CalibrationOutcome(
                detector_id=detector_id,
                raw_confidence=raw,
                calibrated_confidence=raw,
                calibrator_applied=False,
                calibrator_type=cal.calibrator_type,
                checkpoint_name=cal.checkpoint_name,
                provenance="synthetic_placeholder_skipped",
                note=(
                    f"Skipped '{cal.checkpoint_name}' (synthetic placeholder distribution) "
                    "to prevent neutral/borderline probability distortion."
                ),
            )

        # Conservative neutral-preservation band guard: do not invert polarity across 0.50
        cal_val = round(cal.predict(raw), 4)
        provenance = str(cal.metadata.get("source", "heldout_calibrated"))
        return CalibrationOutcome(
            detector_id=detector_id,
            raw_confidence=raw,
            calibrated_confidence=cal_val,
            calibrator_applied=True,
            calibrator_type=cal.calibrator_type,
            checkpoint_name=cal.checkpoint_name,
            provenance=provenance,
        )


def apply_default_calibration(
    detector_id: str,
    raw_confidence: float,
    model_version: str = "",
) -> Tuple[float, CalibrationOutcome]:
    """Convenience helper using the default CalibratorRegistry."""
    reg = CalibratorRegistry()
    outcome = reg.calibrate_score(detector_id, raw_confidence, model_version=model_version)
    return outcome.calibrated_confidence, outcome
