"""
bundle_fusion.py
================
Fuses per-modality detector results into a single BundleVerdict.

Strategy:
  1. For each modality, run the existing aggregate_results() to get
     (score, verdict) — same logic as the single-file /orchestrate path.
  2. Combine modality verdicts using weighted-average of their scores.
  3. Apply AEGIS thresholds (>=0.65 → SYNTHETIC, <=0.35 → AUTHENTIC).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from models import DetectorResult
from aggregate import aggregate_results, AggregateOutcome   # already exists!

# Weights for each modality in the final bundle fusion.
# Mirrors aggregate.py's _DETECTOR_WEIGHTS logic but at modality level.
MODALITY_WEIGHTS: Dict[str, float] = {
    "video": 1.5,   # highest — visual manipulation is primary threat
    "image": 1.2,
    "audio": 1.0,
    "text":  0.8,   # text alone is less conclusive for synthetic media
}

SYNTHETIC_THRESHOLD = 0.65
AUTHENTIC_THRESHOLD = 0.35


@dataclass
class ModalityScore:
    modality: str
    detector: str
    score: float          # 0.0 = AUTHENTIC … 1.0 = SYNTHETIC
    verdict: str          # AUTHENTIC | SYNTHETIC | UNCERTAIN | NO_RESULTS
    claim: str            # human-readable evidence claim
    flags: List[str] = field(default_factory=list)


@dataclass
class BundleFusionResult:
    bundle_id: str
    bundle_score: float              # weighted average of modality scores
    bundle_verdict: str              # AUTHENTIC | SYNTHETIC | UNCERTAIN | NO_RESULTS
    modality_scores: List[ModalityScore] = field(default_factory=list)
    num_modalities: int = 0


def fuse_bundle(
    bundle_id: str,
    modality_results: Dict[str, List[DetectorResult]],
) -> BundleFusionResult:
    """
    Fuse per-modality DetectorResult lists into a BundleFusionResult.

    Args:
        bundle_id: The unique bundle identifier.
        modality_results: dict of modality → list of DetectorResult
                          (output of bundle_router.route_bundle)
    """
    modality_scores: List[ModalityScore] = []
    weighted_score_sum = 0.0
    weight_sum = 0.0

    for modality, results in modality_results.items():
        # Use existing aggregate_results() — same function used in main.py
        score, verdict = aggregate_results(results)

        # Get claim from first successful result
        claim = ""
        flags: List[str] = []
        for r in results:
            if r.status == "ok" and r.evidence:
                claim = r.evidence.claim
                flags = r.evidence.flags or []
                break

        modality_scores.append(ModalityScore(
            modality=modality,
            detector=results[0].detector if results else "unknown",
            score=score,
            verdict=verdict,
            claim=claim,
            flags=flags,
        ))

        # Only include in weighted fusion if we have a real score
        if verdict != AggregateOutcome.NO_RESULTS.value:
            w = MODALITY_WEIGHTS.get(modality, 1.0)
            weighted_score_sum += score * w
            weight_sum += w

    # Compute bundle-level score
    if weight_sum == 0:
        bundle_score = 0.0
        bundle_verdict = AggregateOutcome.NO_RESULTS.value
    else:
        bundle_score = round(weighted_score_sum / weight_sum, 4)
        if bundle_score >= SYNTHETIC_THRESHOLD:
            bundle_verdict = AggregateOutcome.SYNTHETIC.value
        elif bundle_score <= AUTHENTIC_THRESHOLD:
            bundle_verdict = AggregateOutcome.AUTHENTIC.value
        else:
            bundle_verdict = AggregateOutcome.UNCERTAIN.value

    return BundleFusionResult(
        bundle_id=bundle_id,
        bundle_score=bundle_score,
        bundle_verdict=bundle_verdict,
        modality_scores=modality_scores,
        num_modalities=len(modality_scores),
    )