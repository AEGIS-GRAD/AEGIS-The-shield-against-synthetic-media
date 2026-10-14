"""
Feed Fusion Engine for AEGIS.
Combines Cybersecurity feed-integrity signals (hash-chain, timestamp/sequence anomalies, PRNU)
with the AI track's rolling content-anomaly score into a single unified verdict.

Verdict States:
- AUTHENTIC: Feed integrity intact and AI score low (authentic).
- SYNTHETIC: Feed intact or metadata forged, but content anomaly score indicates fake.
- INTEGRITY_UNKNOWN: Feed integrity broken (hash mismatch, timestamp/sequence gaps/regressions, PRNU foreign sensor).
  Per AEGIS core tenets, integrity failures must NEVER resolve to AUTHENTIC.
- UNCERTAIN: Content/integrity signals in borderline or ambiguous range.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class FusionResult:
    """Represents the fused verdict and detailed breakdown for a single window."""
    verdict: str
    combined_score: float
    integrity_score: float
    ai_score: float
    integrity_ok: bool
    evidence: Dict[str, Any] = field(default_factory=dict)


class FeedFusionEngine:
    """
    Fuses feed-integrity indicators with AI content anomaly scores.

    Weights:
        w_integrity: Weight given to integrity score (default: 0.5)
        w_ai: Weight given to AI anomaly score (default: 0.5)
        synthetic_threshold: Threshold above which content is deemed synthetic (default: 0.65)
        authentic_threshold: Threshold below which content is deemed authentic (default: 0.35)
    """

    def __init__(
        self,
        w_integrity: float = 0.5,
        w_ai: float = 0.5,
        synthetic_threshold: float = 0.65,
        authentic_threshold: float = 0.35,
    ):
        self.w_integrity = w_integrity
        self.w_ai = w_ai
        self.synthetic_threshold = synthetic_threshold
        self.authentic_threshold = authentic_threshold

    def compute_integrity_score(
        self,
        hash_chain_ok: bool,
        anomaly_count: int,
        prnu_ok: bool,
    ) -> float:
        """
        Maps integrity signals to a normalized 0.0 - 1.0 anomaly penalty score.
        0.0 = fully clean/intact, 1.0 = severely tampered.
        """
        score = 0.0
        if not hash_chain_ok:
            score += 1.0
        if not prnu_ok:
            score += 0.8
        if anomaly_count > 0:
            # 3 or more stream timestamp/sequence anomalies saturates to full 1.0
            score += min(1.0, anomaly_count / 3.0)

        return min(1.0, score)

    def fuse(
        self,
        hash_chain_ok: bool,
        integrity_anomalies: Optional[List[Any]] = None,
        prnu_ok: bool = True,
        prnu_pce: float = 100.0,
        ai_score: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> FusionResult:
        """
        Fuses the integrity indicators with AI anomaly score for the rolling window.

        Args:
            hash_chain_ok: True if hash chain verified successfully for all frames in window.
            integrity_anomalies: List of timestamp/sequence anomalies (from StreamValidator).
            prnu_ok: True if PRNU sensor fingerprint matched baseline.
            prnu_pce: PCE value from PRNU computation.
            ai_score: Rolling content-anomaly score from AI detector [0.0 - 1.0].
            details: Optional extra debugging/forensics metadata.

        Returns:
            FusionResult containing combined score and verdict.
        """
        if integrity_anomalies is None:
            integrity_anomalies = []

        anomaly_count = len(integrity_anomalies)
        integrity_ok = hash_chain_ok and prnu_ok and (anomaly_count == 0)

        integrity_score = self.compute_integrity_score(
            hash_chain_ok=hash_chain_ok,
            anomaly_count=anomaly_count,
            prnu_ok=prnu_ok,
        )

        # Normalize weights
        total_w = self.w_integrity + self.w_ai
        norm_w_integrity = self.w_integrity / total_w if total_w > 0 else 0.5
        norm_w_ai = self.w_ai / total_w if total_w > 0 else 0.5

        combined_score = (norm_w_integrity * integrity_score) + (norm_w_ai * ai_score)

        # Verdict logic:
        # 1. Non-negotiable: Any integrity compromise must NEVER be AUTHENTIC.
        # If integrity is failed, verdict must be INTEGRITY_UNKNOWN.
        if not integrity_ok:
            verdict = "INTEGRITY_UNKNOWN"
        elif combined_score >= self.synthetic_threshold or ai_score >= self.synthetic_threshold:
            # Even if headers are pristine, AI detecting synthetic artifacts triggers SYNTHETIC
            verdict = "SYNTHETIC"
        elif combined_score <= self.authentic_threshold and ai_score <= self.authentic_threshold:
            verdict = "AUTHENTIC"
        else:
            verdict = "UNCERTAIN"

        evidence = {
            "hash_chain_ok": hash_chain_ok,
            "anomaly_count": anomaly_count,
            "anomalies": [str(a) for a in integrity_anomalies],
            "prnu_ok": prnu_ok,
            "prnu_pce": prnu_pce,
            "ai_score": ai_score,
            "integrity_score": integrity_score,
            "combined_score": combined_score,
        }
        if details:
            evidence.update(details)

        return FusionResult(
            verdict=verdict,
            combined_score=combined_score,
            integrity_score=integrity_score,
            ai_score=ai_score,
            integrity_ok=integrity_ok,
            evidence=evidence,
        )
