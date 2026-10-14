"""
AEGIS Debate & Arbitration Protocol — Master Arbitrator & Judge Engine.
Implements the Forensic Precedence Matrix, claim adjudication, and court-admissible verdict generation.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from debate.disagreement import evaluate_disagreement, is_coverage_gap
from debate.schemas import (
    ClaimAdjudication,
    ClaimPolarity,
    CourtAdmissibleVerdict,
    DisagreementAnalysis,
    DisagreementType,
    ForensicClaim,
    JudgeVerdictClass,
    OperatingConditions,
)

# ── Baseline Weights & Thresholds ───────────────────────────────────────────
DEFAULT_DETECTOR_WEIGHTS = {
    "video-classifier": 1.5,
    "syncnet": 1.2,
    "rppg": 0.8,  # Calibrated down from Month 1's 1.2 due to 10% benchmark agreement
}

SYNTHETIC_VERDICT_THRESHOLD = 0.65
AUTHENTIC_VERDICT_THRESHOLD = 0.35


def compute_evidence_hash(claims: List[ForensicClaim], job_id: str) -> str:
    """Calculates SHA-256 cryptographic digest over all ingested claims for court admissibility."""
    manifest_entries = []
    for c in sorted(claims, key=lambda x: x.detector_id):
        entry = {
            "detector_id": c.detector_id,
            "version": c.model_version,
            "confidence": c.confidence,
            "effective_confidence": c.effective_confidence,
            "polarity": c.polarity.value,
            "claim": c.claim,
            "flags": sorted(c.flags),
            "evidence_hash": c.evidence_hash,
        }
        manifest_entries.append(entry)

    raw_bytes = json.dumps({"job_id": job_id, "claims": manifest_entries}, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


class JudgeArbitrator:
    """The Judge Agent and Arbitration Engine for conflicting video evidence."""

    def __init__(self, weights: Optional[dict] = None):
        self.weights = weights or DEFAULT_DETECTOR_WEIGHTS.copy()

    def arbitrate(
        self,
        claims: List[ForensicClaim],
        job_id: Optional[str] = None,
        conditions: Optional[OperatingConditions] = None,
    ) -> CourtAdmissibleVerdict:
        """Executes full arbitration protocol over submitted detector claims."""
        resolved_job_id = job_id or (claims[0].job_id if claims else str(uuid.uuid4()))
        verdict_id = f"vrd-{uuid.uuid4().hex[:12]}"
        evidence_hash = compute_evidence_hash(claims, resolved_job_id)

        if not claims:
            return CourtAdmissibleVerdict(
                verdict_id=verdict_id,
                job_id=resolved_job_id,
                final_verdict=JudgeVerdictClass.INTEGRITY_UNKNOWN,
                calibrated_score=0.5,
                confidence_interval=[0.5, 0.5],
                arbitration_mode="no_evidence_fallback",
                adjudications=[],
                forensic_justification="No forensic evidence provided for arbitration. Defaulting to INTEGRITY_UNKNOWN.",
                coverage_warnings=["Total absence of detector claims."],
                siem_alert_tier="P2_ELEVATED",
                evidence_manifest_hash=evidence_hash,
            )

        # Step 1: Disagreement Analysis
        analysis: DisagreementAnalysis = evaluate_disagreement(claims)

        coverage_warnings = []
        for gap_detector in analysis.coverage_gaps:
            coverage_warnings.append(
                f"Coverage Gap: Detector '{gap_detector}' could not evaluate input due to missing modality or prerequisite."
            )

        # Step 2: Route by dispute necessity
        if not analysis.requires_arbitration:
            return self._synthesize_consensus_verdict(
                claims=claims,
                analysis=analysis,
                verdict_id=verdict_id,
                job_id=resolved_job_id,
                evidence_hash=evidence_hash,
                coverage_warnings=coverage_warnings,
            )

        # Step 3: Full Dispute Arbitration via Forensic Precedence Matrix
        return self._adjudicate_dispute(
            claims=claims,
            analysis=analysis,
            conditions=conditions,
            verdict_id=verdict_id,
            job_id=resolved_job_id,
            evidence_hash=evidence_hash,
            coverage_warnings=coverage_warnings,
        )

    def _synthesize_consensus_verdict(
        self,
        claims: List[ForensicClaim],
        analysis: DisagreementAnalysis,
        verdict_id: str,
        job_id: str,
        evidence_hash: str,
        coverage_warnings: List[str],
    ) -> CourtAdmissibleVerdict:
        """Fast-path consensus synthesis when detectors agree within tolerance."""
        active_claims = [c for c in claims if not is_coverage_gap(c)]

        if not active_claims:
            return CourtAdmissibleVerdict(
                verdict_id=verdict_id,
                job_id=job_id,
                final_verdict=JudgeVerdictClass.INTEGRITY_UNKNOWN,
                calibrated_score=0.5,
                confidence_interval=[0.5, 0.5],
                arbitration_mode="consensus_fast_path",
                adjudications=[],
                forensic_justification=(
                    "All submitted detectors reported coverage gaps or inconclusive results. "
                    "Per AEGIS Forensic Integrity standards, inconclusive media cannot be certified authentic."
                ),
                coverage_warnings=coverage_warnings,
                siem_alert_tier="P2_ELEVATED",
                evidence_manifest_hash=evidence_hash,
            )

        adjudications: List[ClaimAdjudication] = []
        weighted_conf_sum = 0.0
        total_weight = 0.0

        for c in active_claims:
            w = self.weights.get(c.detector_id, 1.0)
            eff_conf = c.effective_confidence
            weighted_conf_sum += eff_conf * w
            total_weight += w

            adjudications.append(
                ClaimAdjudication(
                    detector_id=c.detector_id,
                    original_polarity=c.polarity,
                    original_confidence=c.confidence,
                    accepted_confidence=eff_conf,
                    weight_assigned=w,
                    discount_reason=None,
                    findings_retained=[c.claim],
                )
            )

        calibrated_score = round(weighted_conf_sum / max(total_weight, 1e-6), 4)

        if calibrated_score >= SYNTHETIC_VERDICT_THRESHOLD:
            final_verdict = JudgeVerdictClass.SYNTHETIC
            siem_tier = "P1_CRITICAL"
        elif calibrated_score <= AUTHENTIC_VERDICT_THRESHOLD:
            final_verdict = JudgeVerdictClass.AUTHENTIC
            siem_tier = "P4_INFORMATIONAL"
        else:
            final_verdict = JudgeVerdictClass.INTEGRITY_UNKNOWN
            siem_tier = "P2_ELEVATED"

        conf_margin = round(analysis.confidence_spread / 2.0, 3)
        interval = [max(0.0, round(calibrated_score - conf_margin, 3)), min(1.0, round(calibrated_score + conf_margin, 3))]

        justification = (
            f"CONSENSUS RULING: Detectors operate in alignment (confidence spread {analysis.confidence_spread:.2f} "
            f"< threshold). Calibrated ensemble score of {calibrated_score:.2f} confirms {final_verdict.value} status."
        )

        return CourtAdmissibleVerdict(
            verdict_id=verdict_id,
            job_id=job_id,
            final_verdict=final_verdict,
            calibrated_score=calibrated_score,
            confidence_interval=interval,
            arbitration_mode="consensus_fast_path",
            adjudications=adjudications,
            forensic_justification=justification,
            coverage_warnings=coverage_warnings,
            siem_alert_tier=siem_tier,
            evidence_manifest_hash=evidence_hash,
        )

    def _adjudicate_dispute(
        self,
        claims: List[ForensicClaim],
        analysis: DisagreementAnalysis,
        conditions: Optional[OperatingConditions],
        verdict_id: str,
        job_id: str,
        evidence_hash: str,
        coverage_warnings: List[str],
    ) -> CourtAdmissibleVerdict:
        """Full Forensic Precedence Matrix dispute resolution."""
        claims_by_id = {c.detector_id: c for c in claims}
        adjudications: List[ClaimAdjudication] = []
        discount_reasons: List[str] = []

        # Operating environment facts
        mean_lum = conditions.mean_luminance if conditions and conditions.mean_luminance is not None else 100.0
        duration_s = conditions.duration_seconds if conditions and conditions.duration_seconds is not None else 10.0

        vc_claim = claims_by_id.get("video-classifier")
        rppg_claim = claims_by_id.get("rppg")
        sync_claim = claims_by_id.get("syncnet")

        # ── Precedence Rule 1: Low-Light Score Inversion Trap on rPPG ─────────
        rppg_discounted = False
        if rppg_claim and not is_coverage_gap(rppg_claim):
            has_low_light_flag = "low_light_attenuation" in rppg_claim.flags or "insufficient_lighting" in rppg_claim.flags
            if mean_lum < 40.0 or has_low_light_flag:
                if rppg_claim.confidence > 0.60:
                    rppg_discounted = True
                    discount_reasons.append(
                        f"Rule 1 Applied (Low-Light Inversion): rPPG synthetic claim (conf={rppg_claim.confidence:.2f}) "
                        f"discounted due to low luminance ({mean_lum:.1f}/255). Chrominance collapse mimics synthetic flatness."
                    )

        # ── Precedence Rule 2: Short Clip on rPPG (< 2.0s) ────────────────────
        if rppg_claim and not is_coverage_gap(rppg_claim) and not rppg_discounted:
            if duration_s < 2.0 or "short_clip_attenuation" in rppg_claim.flags:
                rppg_discounted = True
                discount_reasons.append(
                    f"Rule 2 Applied (Short Duration): rPPG signal discounted (duration {duration_s:.1f}s < 2.0s "
                    "filter convergence minimum)."
                )

        # ── Precedence Rule 3: Face-Swap Pulse Preservation ───────────────────
        face_swap_case = False
        if vc_claim and rppg_claim and not is_coverage_gap(vc_claim) and not is_coverage_gap(rppg_claim):
            if vc_claim.confidence >= 0.70 and rppg_claim.confidence <= 0.35 and not rppg_discounted:
                face_swap_case = True
                discount_reasons.append(
                    "Rule 3 Applied (Face-Swap Inpainting): video-classifier detected spatial warping / boundary anomalies, "
                    "while rPPG detected authentic cardiac rhythm. Physiological pulse is preserved from original donor body; "
                    "spatial face manipulation overrides authentic physiological signal."
                )

        # ── Precedence Rule 4: Dubbing / Non-English Content on SyncNet ───────
        dubbing_case = False
        if sync_claim and not is_coverage_gap(sync_claim):
            if sync_claim.confidence >= 0.70:
                other_authentic = []
                if vc_claim and not is_coverage_gap(vc_claim) and vc_claim.confidence <= 0.35:
                    other_authentic.append(vc_claim)
                if rppg_claim and not is_coverage_gap(rppg_claim) and not rppg_discounted and rppg_claim.confidence <= 0.35:
                    other_authentic.append(rppg_claim)

                if len(other_authentic) >= 1:
                    dubbing_case = True
                    discount_reasons.append(
                        "Rule 4 Applied (Audio Dubbing): SyncNet lip-desync discounted as post-production translation "
                        "or dubbing because spatial and physiological detectors verify authentic visual human presence."
                    )

        # ── Execute Weighting & Adjudication ──────────────────────────────────
        active_claims = [c for c in claims if not is_coverage_gap(c)]
        weighted_conf_sum = 0.0
        total_weight = 0.0

        for c in active_claims:
            base_w = self.weights.get(c.detector_id, 1.0)
            accepted_conf = c.effective_confidence
            discount_note = None

            if c.detector_id == "rppg" and rppg_discounted:
                base_w *= 0.10  # 90% discount
                accepted_conf = 0.50
                discount_note = "Discounted under Precedence Rule (Low Light or Short Clip)"
            elif c.detector_id == "rppg" and face_swap_case:
                base_w *= 0.20  # 80% discount
                discount_note = "Discounted under Face-Swap Inpainting Rule"
            elif c.detector_id == "syncnet" and dubbing_case:
                base_w *= 0.20  # 80% discount
                discount_note = "Discounted under Audio Dubbing Rule"

            weighted_conf_sum += accepted_conf * base_w
            total_weight += base_w

            adjudications.append(
                ClaimAdjudication(
                    detector_id=c.detector_id,
                    original_polarity=c.polarity,
                    original_confidence=c.confidence,
                    accepted_confidence=round(accepted_conf, 4),
                    weight_assigned=round(base_w, 3),
                    discount_reason=discount_note,
                    findings_retained=[c.claim],
                )
            )

        calibrated_score = round(weighted_conf_sum / max(total_weight, 1e-6), 4)

        # If face-swap detected, enforce minimum synthetic score of 0.85
        if face_swap_case:
            calibrated_score = max(calibrated_score, 0.85)

        # Step 4: Final Verdict Classification
        if calibrated_score >= SYNTHETIC_VERDICT_THRESHOLD:
            final_verdict = JudgeVerdictClass.SYNTHETIC
            siem_tier = "P1_CRITICAL"
        elif calibrated_score <= AUTHENTIC_VERDICT_THRESHOLD:
            final_verdict = JudgeVerdictClass.AUTHENTIC
            siem_tier = "P4_INFORMATIONAL"
        else:
            final_verdict = JudgeVerdictClass.INTEGRITY_UNKNOWN
            siem_tier = "P2_ELEVATED"

        # Forensic Justification Narrative
        ruling_parts = [
            f"ARBITRATION RULING ({analysis.primary_disagreement_type.value}):",
            f"Conflict between {analysis.conflicting_detectors} (Spread: {analysis.confidence_spread:.2f}).",
        ]
        if discount_reasons:
            ruling_parts.append("Applied Precedence Rules:")
            ruling_parts.extend([f"• {r}" for r in discount_reasons])
        ruling_parts.append(
            f"Final calibrated forensic score: {calibrated_score:.2f} resulting in {final_verdict.value}."
        )

        forensic_justification = " \n".join(ruling_parts)
        conf_margin = round(max(0.05, analysis.confidence_spread / 3.0), 3)
        interval = [max(0.0, round(calibrated_score - conf_margin, 3)), min(1.0, round(calibrated_score + conf_margin, 3))]

        return CourtAdmissibleVerdict(
            verdict_id=verdict_id,
            job_id=job_id,
            final_verdict=final_verdict,
            calibrated_score=calibrated_score,
            confidence_interval=interval,
            arbitration_mode="expert_deterministic_judge",
            adjudications=adjudications,
            forensic_justification=forensic_justification,
            coverage_warnings=coverage_warnings,
            siem_alert_tier=siem_tier,
            evidence_manifest_hash=evidence_hash,
        )
