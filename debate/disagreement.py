"""
AEGIS Debate & Arbitration Protocol — Disagreement Detection Engine.
Calculates disagreement thresholds, polarity inversions, and distinguishes true conflicts from coverage gaps.
"""

from __future__ import annotations

from typing import List, Tuple
from debate.schemas import (
    ForensicClaim,
    ClaimPolarity,
    DisagreementAnalysis,
    DisagreementType,
)

# ── Disagreement & Threshold Constants ───────────────────────────────────────
DISAGREEMENT_SPREAD_THRESHOLD: float = 0.30
SYNTHETIC_POLARITY_THRESHOLD: float = 0.65
AUTHENTIC_POLARITY_THRESHOLD: float = 0.35

COVERAGE_GAP_FLAGS = {
    "not_applicable",
    "insufficient_signal",
    "insufficient_duration",
    "insufficient_lighting",
    "silent_video",
    "face_occluded",
}


def is_coverage_gap(claim: ForensicClaim) -> bool:
    """Returns True if a claim represents an unprocessable condition or missing modality."""
    if claim.coverage_gap:
        return True
    if claim.polarity in (ClaimPolarity.NOT_APPLICABLE, ClaimPolarity.INCONCLUSIVE):
        return True
    if any(flag in COVERAGE_GAP_FLAGS for flag in claim.flags):
        # If confidence is neutral 0.5 with a gap flag, treat as gap
        if 0.45 <= claim.confidence <= 0.55:
            return True
    return False


def evaluate_disagreement(claims: List[ForensicClaim]) -> DisagreementAnalysis:
    """Evaluates a collection of forensic claims from video detectors.

    Determines if arbitration is required due to polarity inversion, confidence spread,
    or heuristic collision, while separating benign coverage gaps.
    """
    if not claims:
        return DisagreementAnalysis(
            requires_arbitration=False,
            primary_disagreement_type=DisagreementType.CONSENSUS,
            confidence_spread=0.0,
            max_confidence=0.0,
            min_confidence=0.0,
            conflicting_detectors=[],
            coverage_gaps=[],
            conflict_summary="No claims provided for evaluation.",
        )

    active_claims: List[ForensicClaim] = []
    coverage_gaps: List[str] = []

    for c in claims:
        if is_coverage_gap(c):
            coverage_gaps.append(c.detector_id)
        else:
            active_claims.append(c)

    # If only one or zero active detectors, no mutual contradiction can exist
    if len(active_claims) <= 1:
        single_detector = active_claims[0].detector_id if active_claims else "None"
        conf = active_claims[0].effective_confidence if active_claims else 0.5
        gap_type = DisagreementType.COVERAGE_GAP_ONLY if coverage_gaps else DisagreementType.CONSENSUS
        return DisagreementAnalysis(
            requires_arbitration=False,
            primary_disagreement_type=gap_type,
            confidence_spread=0.0,
            max_confidence=conf,
            min_confidence=conf,
            conflicting_detectors=[],
            coverage_gaps=coverage_gaps,
            conflict_summary=(
                f"Single active detector ({single_detector}) with {len(coverage_gaps)} coverage gaps. "
                "No mutual conflict."
            ),
        )

    # Compute confidence spread across active detectors using effective (attenuated) confidence
    confidences = [c.effective_confidence for c in active_claims]
    max_c = max(confidences)
    min_c = min(confidences)
    spread = round(max_c - min_c, 4)

    # Detect polarity inversion
    synthetic_detectors = [
        c.detector_id
        for c in active_claims
        if c.polarity == ClaimPolarity.SYNTHETIC or c.effective_confidence >= SYNTHETIC_POLARITY_THRESHOLD
    ]
    authentic_detectors = [
        c.detector_id
        for c in active_claims
        if c.polarity == ClaimPolarity.AUTHENTIC or c.effective_confidence <= AUTHENTIC_POLARITY_THRESHOLD
    ]

    has_polarity_inversion = bool(synthetic_detectors and authentic_detectors)

    # Detect heuristic collisions
    collision_detectors: List[str] = []
    for c in active_claims:
        if "high_fake_probability" in c.flags or "sync_offset_detected" in c.flags:
            collision_detectors.append(c.detector_id)
        elif "lip_sync_verified" in c.flags or "authentic_frames" in c.flags:
            collision_detectors.append(c.detector_id)

    conflicting_detectors = list(set(synthetic_detectors + authentic_detectors))

    # Evaluate arbitration necessity
    if has_polarity_inversion:
        summary = (
            f"Polarity Inversion Detected: {synthetic_detectors} assert SYNTHETIC "
            f"while {authentic_detectors} assert AUTHENTIC. Spread: {spread:.2f}."
        )
        return DisagreementAnalysis(
            requires_arbitration=True,
            primary_disagreement_type=DisagreementType.POLARITY_INVERSION,
            confidence_spread=spread,
            max_confidence=max_c,
            min_confidence=min_c,
            conflicting_detectors=conflicting_detectors,
            coverage_gaps=coverage_gaps,
            conflict_summary=summary,
        )

    if spread >= DISAGREEMENT_SPREAD_THRESHOLD:
        summary = (
            f"Confidence Spread Threshold Exceeded: delta={spread:.2f} >= {DISAGREEMENT_SPREAD_THRESHOLD:.2f} "
            f"between {active_claims[confidences.index(max_c)].detector_id} ({max_c:.2f}) and "
            f"{active_claims[confidences.index(min_c)].detector_id} ({min_c:.2f})."
        )
        return DisagreementAnalysis(
            requires_arbitration=True,
            primary_disagreement_type=DisagreementType.CONFIDENCE_SPREAD,
            confidence_spread=spread,
            max_confidence=max_c,
            min_confidence=min_c,
            conflicting_detectors=[
                active_claims[confidences.index(max_c)].detector_id,
                active_claims[confidences.index(min_c)].detector_id,
            ],
            coverage_gaps=coverage_gaps,
            conflict_summary=summary,
        )

    # Otherwise: consensus within tolerance
    return DisagreementAnalysis(
        requires_arbitration=False,
        primary_disagreement_type=DisagreementType.CONSENSUS,
        confidence_spread=spread,
        max_confidence=max_c,
        min_confidence=min_c,
        conflicting_detectors=[],
        coverage_gaps=coverage_gaps,
        conflict_summary=f"Detectors in consensus within tolerance (spread={spread:.2f} < {DISAGREEMENT_SPREAD_THRESHOLD:.2f}).",
    )
