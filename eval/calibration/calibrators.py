"""
AEGIS Calibration Module — Calibrator Implementations
======================================================
Provides standard, reusable calibration methods:
  1. Platt Scaling (logistic scaling: a * z + b)
  2. Temperature Scaling (logit scaling by positive temperature T: z / T)
  3. Isotonic Regression (non-parametric monotonic step function)

Designed for modular usage across modalities: audio, image, text, and video.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import expit, logit
from sklearn.isotonic import IsotonicRegression


def _ensure_numpy(x: Any) -> np.ndarray:
    """Converts input array-like to a 1D float64 numpy array."""
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim == 2 and arr.shape[1] == 1:
        arr = arr.ravel()
    elif arr.ndim == 2 and arr.shape[1] == 2:
        # If 2D probability distribution [p0, p1], extract p1 (synthetic class)
        arr = arr[:, 1]
    if arr.ndim != 1:
        raise ValueError(f"Expected 1D or (N, 1)/(N, 2) array, got shape {arr.shape}")
    return arr


def _safe_logit(probs: np.ndarray, eps: float = 1e-7) -> np.ndarray:
    """Safely converts probabilities in [0, 1] to logits, clipping at eps."""
    clipped = np.clip(probs, eps, 1.0 - eps)
    return logit(clipped)


class BaseCalibrator(ABC):
    """Abstract base class for probability calibrators."""

    def __init__(self, name: str):
        self.name = name
        self.is_fitted: bool = False
        self.metadata: Dict[str, Any] = {}

    @abstractmethod
    def fit(self, scores: Any, labels: Any) -> "BaseCalibrator":
        """Fits the calibrator on validation/held-out scores and binary ground truth labels."""
        pass

    @abstractmethod
    def predict_proba(self, scores: Any) -> np.ndarray:
        """Transforms uncalibrated scores/logits into calibrated probabilities in [0, 1]."""
        pass

    def calibrate(self, scores: Any) -> np.ndarray:
        """Alias for predict_proba."""
        return self.predict_proba(scores)

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Serializes calibrator state to a dictionary."""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseCalibrator":
        """Deserializes calibrator from a dictionary."""
        pass

    def save(self, path: Union[str, Path]) -> None:
        """Saves calibrator parameters to a JSON file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "BaseCalibrator":
        """Loads calibrator parameters from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        calibrator_type = data.get("calibrator_type")
        if calibrator_type == "platt":
            return PlattCalibrator.from_dict(data)
        elif calibrator_type == "temperature":
            return TemperatureCalibrator.from_dict(data)
        elif calibrator_type == "isotonic":
            return IsotonicCalibrator.from_dict(data)
        else:
            raise ValueError(f"Unknown calibrator type in file: {calibrator_type}")


class PlattCalibrator(BaseCalibrator):
    """
    Platt Scaling Calibrator.
    Maps uncalibrated scores/logits z to calibrated probabilities using logistic regression:
        P(Y = 1 | z) = 1 / (1 + exp(-(a * z + b)))
    """

    def __init__(self, a: float = 1.0, b: float = 0.0, input_is_probability: bool = True):
        super().__init__("platt")
        self.a: float = float(a)
        self.b: float = float(b)
        self.input_is_probability = input_is_probability

    def fit(self, scores: Any, labels: Any) -> "PlattCalibrator":
        s = _ensure_numpy(scores)
        y = _ensure_numpy(labels).astype(int)

        if len(s) != len(y):
            raise ValueError(f"Scores length {len(s)} does not match labels length {len(y)}")
        if len(np.unique(y)) < 2:
            raise ValueError("Labels must contain at least both classes (0 and 1) to fit Platt scaling.")

        # Determine if input looks like probabilities [0, 1]
        if self.input_is_probability or (np.all(s >= 0.0) and np.all(s <= 1.0)):
            z = _safe_logit(s)
            self.input_is_probability = True
        else:
            z = s
            self.input_is_probability = False

        # Loss function: Negative Log-Likelihood (Binary Cross Entropy) + light L2 penalty
        def _loss(params):
            a_val, b_val = params
            linear = a_val * z + b_val
            # Log-sum-exp trick for numerical stability
            # nll = sum(log(1 + exp(linear)) - y * linear)
            p = expit(linear)
            p = np.clip(p, 1e-12, 1.0 - 1e-12)
            nll = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
            reg = 1e-4 * (a_val**2 + b_val**2)
            return nll + reg

        res = minimize(_loss, x0=[1.0, 0.0], method="L-BFGS-B")
        self.a = float(res.x[0])
        self.b = float(res.x[1])
        self.is_fitted = True
        self.metadata = {
            "loss": float(res.fun),
            "converged": bool(res.success),
            "num_samples": len(s),
        }
        return self

    def predict_proba(self, scores: Any) -> np.ndarray:
        s = _ensure_numpy(scores)
        if self.input_is_probability or (np.all(s >= 0.0) and np.all(s <= 1.0)):
            z = _safe_logit(s)
        else:
            z = s
        calibrated = expit(self.a * z + self.b)
        return np.clip(calibrated, 0.0, 1.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calibrator_type": "platt",
            "name": self.name,
            "a": self.a,
            "b": self.b,
            "input_is_probability": self.input_is_probability,
            "is_fitted": self.is_fitted,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlattCalibrator":
        inst = cls(
            a=data.get("a", 1.0),
            b=data.get("b", 0.0),
            input_is_probability=data.get("input_is_probability", True),
        )
        inst.is_fitted = data.get("is_fitted", True)
        inst.metadata = data.get("metadata", {})
        return inst


class TemperatureCalibrator(BaseCalibrator):
    """
    Temperature Scaling Calibrator.
    A single-parameter variant of Platt scaling:
        P(Y = 1 | z) = 1 / (1 + exp(-z / T))
    where T > 0 is the learned temperature.
    """

    def __init__(self, temperature: float = 1.0, input_is_probability: bool = True):
        super().__init__("temperature")
        self.temperature: float = float(temperature)
        self.input_is_probability = input_is_probability

    def fit(self, scores: Any, labels: Any) -> "TemperatureCalibrator":
        s = _ensure_numpy(scores)
        y = _ensure_numpy(labels).astype(int)

        if len(s) != len(y):
            raise ValueError(f"Scores length {len(s)} does not match labels length {len(y)}")
        if len(np.unique(y)) < 2:
            raise ValueError("Labels must contain both classes (0 and 1) to fit temperature scaling.")

        if self.input_is_probability or (np.all(s >= 0.0) and np.all(s <= 1.0)):
            z = _safe_logit(s)
            self.input_is_probability = True
        else:
            z = s
            self.input_is_probability = False

        # Loss function: NLL with respect to scalar temperature T > 0
        def _nll(temp):
            if temp <= 0.0:
                return 1e9
            scaled_z = z / temp
            p = expit(scaled_z)
            p = np.clip(p, 1e-12, 1.0 - 1e-12)
            return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))

        res = minimize_scalar(_nll, bounds=(0.01, 50.0), method="bounded")
        self.temperature = float(res.x)
        self.is_fitted = True
        self.metadata = {
            "loss": float(res.fun),
            "converged": bool(res.success),
            "num_samples": len(s),
        }
        return self

    def predict_proba(self, scores: Any) -> np.ndarray:
        s = _ensure_numpy(scores)
        if self.input_is_probability or (np.all(s >= 0.0) and np.all(s <= 1.0)):
            z = _safe_logit(s)
        else:
            z = s
        t = max(self.temperature, 1e-4)
        calibrated = expit(z / t)
        return np.clip(calibrated, 0.0, 1.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calibrator_type": "temperature",
            "name": self.name,
            "temperature": self.temperature,
            "input_is_probability": self.input_is_probability,
            "is_fitted": self.is_fitted,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemperatureCalibrator":
        inst = cls(
            temperature=data.get("temperature", 1.0),
            input_is_probability=data.get("input_is_probability", True),
        )
        inst.is_fitted = data.get("is_fitted", True)
        inst.metadata = data.get("metadata", {})
        return inst


class IsotonicCalibrator(BaseCalibrator):
    """
    Isotonic Regression Calibrator.
    Fits a non-parametric piecewise constant monotonic step function:
        P(Y = 1 | s) = m(s)
    """

    def __init__(self):
        super().__init__("isotonic")
        self._regressor = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        self._x_thresholds: Optional[List[float]] = None
        self._y_thresholds: Optional[List[float]] = None

    def fit(self, scores: Any, labels: Any) -> "IsotonicCalibrator":
        s = _ensure_numpy(scores)
        y = _ensure_numpy(labels).astype(int)

        if len(s) != len(y):
            raise ValueError(f"Scores length {len(s)} does not match labels length {len(y)}")
        if len(np.unique(y)) < 2:
            raise ValueError("Labels must contain both classes (0 and 1) to fit isotonic regression.")

        self._regressor.fit(s, y)
        self.is_fitted = True

        # Extract thresholds for pure-JSON serialization
        if hasattr(self._regressor, "X_thresholds_") and hasattr(self._regressor, "y_thresholds_"):
            self._x_thresholds = [float(x) for x in self._regressor.X_thresholds_]
            self._y_thresholds = [float(y_val) for y_val in self._regressor.y_thresholds_]

        self.metadata = {
            "num_samples": len(s),
            "num_thresholds": len(self._x_thresholds) if self._x_thresholds else 0,
        }
        return self

    def predict_proba(self, scores: Any) -> np.ndarray:
        s = _ensure_numpy(scores)
        if self._x_thresholds is not None and self._y_thresholds is not None:
            # Pure numpy interpolation based on stored thresholds
            calibrated = np.interp(
                s,
                self._x_thresholds,
                self._y_thresholds,
                left=self._y_thresholds[0],
                right=self._y_thresholds[-1],
            )
        else:
            calibrated = self._regressor.predict(s)
        return np.clip(calibrated, 0.0, 1.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calibrator_type": "isotonic",
            "name": self.name,
            "x_thresholds": self._x_thresholds,
            "y_thresholds": self._y_thresholds,
            "is_fitted": self.is_fitted,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IsotonicCalibrator":
        inst = cls()
        inst._x_thresholds = data.get("x_thresholds")
        inst._y_thresholds = data.get("y_thresholds")
        inst.is_fitted = data.get("is_fitted", True)
        inst.metadata = data.get("metadata", {})
        return inst


def get_calibrator(method: str) -> BaseCalibrator:
    """Factory creating a calibrator instance by method name."""
    m = method.strip().lower()
    if m == "platt":
        return PlattCalibrator()
    elif m in ("temperature", "temperature_scaling", "temp"):
        return TemperatureCalibrator()
    elif m in ("isotonic", "isotonic_regression"):
        return IsotonicCalibrator()
    else:
        raise ValueError(f"Unknown calibration method '{method}'. Supported: 'platt', 'temperature', 'isotonic'.")
