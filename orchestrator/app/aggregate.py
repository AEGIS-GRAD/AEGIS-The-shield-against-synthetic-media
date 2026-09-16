from __future__ import annotations
from typing import List, Tuple
from models import DetectorResult

_DETECTOR_WEIGHTS: dict[str, float] = {
    "video-classifier": 1.5,
    "rppg": 1.2,
    "syncnet": 1.2,
    "aasist": 1.0,
}

_SYNTHETIC_THRESHOLD = 0.65
_AUTHENTIC_THRESHOLD = 0.35


def aggregate_results(results: List[DetectorResult]) -> Tuple[float, str]:
    usable = [r for r in results if r.status == "ok" and r.confidence is not None]

    if not usable:
        return 0.0, "NO_RESULTS"

    weighted_sum = sum(r.confidence * _DETECTOR_WEIGHTS.get(r.detector, 1.0) for r in usable)
    total_weight = sum(_DETECTOR_WEIGHTS.get(r.detector, 1.0) for r in usable)
    score = weighted_sum / total_weight

    if score >= _SYNTHETIC_THRESHOLD:
        verdict = "SYNTHETIC"
    elif score <= _AUTHENTIC_THRESHOLD:
        verdict = "AUTHENTIC"
    else:
        verdict = "UNCERTAIN"

    return round(score, 4), verdict