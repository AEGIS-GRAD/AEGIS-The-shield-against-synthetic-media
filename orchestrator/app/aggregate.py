from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from models import DetectorResult

# ── Aggregation weights (calibrated baselines) ────────────────────────────────
_DETECTOR_WEIGHTS: dict[str, float] = {
    "video-classifier": 1.5,
    "rppg": 1.2,
    "syncnet": 1.2,
    "aasist": 1.0,
}

_SYNTHETIC_THRESHOLD = 0.65
_AUTHENTIC_THRESHOLD = 0.35


class AggregateOutcome(str, Enum):
    """Explicit aggregate outcome classes.
    
    Under AEGIS forensic policy, UNCERTAIN is a first-class explicit verdict,
    strictly distinguished from AUTHENTIC to prevent false-authentic safety risks.
    """
    AUTHENTIC = "AUTHENTIC"
    SYNTHETIC = "SYNTHETIC"
    UNCERTAIN = "UNCERTAIN"
    NO_RESULTS = "NO_RESULTS"


def is_decisive(verdict: str) -> bool:
    """Returns True if the verdict is decisive (AUTHENTIC or SYNTHETIC),
    and False if the verdict is UNCERTAIN, INTEGRITY_UNKNOWN, or NO_RESULTS.
    """
    return (verdict or "").strip().upper() in (AggregateOutcome.AUTHENTIC.value, AggregateOutcome.SYNTHETIC.value)


def aggregate_results(results: List[DetectorResult]) -> Tuple[float, str]:
    """Aggregates detector results using weighted confidence averaging.
    
    Returns:
        Tuple[float, str]: (aggregated_score, explicit_verdict)
        where explicit_verdict is strictly one of:
          - 'SYNTHETIC' (score >= 0.65)
          - 'AUTHENTIC' (score <= 0.35)
          - 'UNCERTAIN' (0.35 < score < 0.65) — explicit outcome, NEVER folded into authentic.
          - 'NO_RESULTS' (no usable detector results)
    """
    usable = [r for r in results if r.status == "ok" and r.confidence is not None]

    if not usable:
        return 0.0, AggregateOutcome.NO_RESULTS.value

    weighted_sum = sum(r.confidence * _DETECTOR_WEIGHTS.get(r.detector, 1.0) for r in usable)
    total_weight = sum(_DETECTOR_WEIGHTS.get(r.detector, 1.0) for r in usable)
    score = weighted_sum / max(total_weight, 1e-6)

    if score >= _SYNTHETIC_THRESHOLD:
        verdict = AggregateOutcome.SYNTHETIC.value
    elif score <= _AUTHENTIC_THRESHOLD:
        verdict = AggregateOutcome.AUTHENTIC.value
    else:
        verdict = AggregateOutcome.UNCERTAIN.value

    return round(score, 4), verdict


def evaluate_explicit_outcome(verdict: str, true_label: str) -> Dict[str, Any]:
    """Evaluates an aggregation verdict against true binary label with explicit UNCERTAIN handling.
    
    Prevents folding UNCERTAIN into authentic.
    
    Args:
        verdict: 'AUTHENTIC', 'SYNTHETIC', 'UNCERTAIN', or 'NO_RESULTS'.
        true_label: 'REAL' (authentic) or 'FAKE' (synthetic).
        
    Returns:
        Dict with categorization:
          - outcome: 'CORRECT_AUTHENTIC', 'CORRECT_SYNTHETIC', 'FALSE_AUTHENTIC',
                     'FALSE_SYNTHETIC', 'EXPLICIT_UNCERTAIN', or 'NO_RESULTS'.
          - is_correct: True only for correct decisive verdicts.
          - is_decisive: True for decisive verdicts.
          - is_false_authentic: True only if true label is FAKE and verdict is asserted AUTHENTIC.
    """
    v = (verdict or "").strip().upper()
    tl = (true_label or "").strip().upper()
    is_fake = tl in ("FAKE", "SYNTHETIC", "1")
    is_real = tl in ("REAL", "AUTHENTIC", "0", "BONAFIDE")

    if v == AggregateOutcome.NO_RESULTS.value:
        return {
            "outcome": "NO_RESULTS",
            "is_correct": False,
            "is_decisive": False,
            "is_false_authentic": False,
        }

    if v == AggregateOutcome.UNCERTAIN.value:
        # Crucial: UNCERTAIN is NOT counted as authentic/correct real!
        return {
            "outcome": "EXPLICIT_UNCERTAIN",
            "is_correct": False,
            "is_decisive": False,
            "is_false_authentic": False,
        }

    if v == AggregateOutcome.AUTHENTIC.value:
        if is_real:
            return {"outcome": "CORRECT_AUTHENTIC", "is_correct": True, "is_decisive": True, "is_false_authentic": False}
        else:
            return {"outcome": "FALSE_AUTHENTIC", "is_correct": False, "is_decisive": True, "is_false_authentic": True}

    if v == AggregateOutcome.SYNTHETIC.value:
        if is_fake:
            return {"outcome": "CORRECT_SYNTHETIC", "is_correct": True, "is_decisive": True, "is_false_authentic": False}
        else:
            return {"outcome": "FALSE_SYNTHETIC", "is_correct": False, "is_decisive": True, "is_false_authentic": False}

    return {
        "outcome": "UNKNOWN",
        "is_correct": False,
        "is_decisive": False,
        "is_false_authentic": False,
    }
