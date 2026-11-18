"""
AEGIS Debate & Arbitration Protocol — Master Arbitrator & Judge Engine.
Implements the Forensic Precedence Matrix, claim adjudication, and court-admissible verdict generation.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from debate.calibration import (
    UNCALIBRATED_MODEL_VERSIONS,
    CalibrationOutcome,
    CalibratorRegistry,
)
from debate.disagreement import (
    AUTHENTIC_POLARITY_THRESHOLD,
    SYNTHETIC_POLARITY_THRESHOLD,
    evaluate_disagreement,
    is_coverage_gap,
)
from debate.manifest_reliability import (
    ConditionReliabilityAssessment,
    ManifestReliabilityEngine,
)
from debate.poisoning_guard import (
    PoisoningMitigationConfig,
    apply_adjudication_mitigations,
    check_corroboration_quorum,
    detect_outlier_detectors,
    inspect_claim_miscalibration,
)
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
    "detector_image": 1.5,
    "image": 1.5,
    "image-mirror": 1.5,
    "image-frequency": 0.8,
    "image-exif": 0.5,
    "detector_text": 1.5,
    "text-desklib": 1.5,
    "text-stylometry": 0.7,
    "text-perplexity": 0.7,
    "syncnet": 1.2,
    "aasist": 1.2,
    "rppg": 0.45,  # Aligned with rppg.json manifest base_reliability_weight
    "streaming-rppg": 0.45,
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
    """The Judge Agent and Arbitration Engine for multimodal forensic evidence."""

    def __init__(
        self,
        weights: Optional[dict] = None,
        reliability_engine: Optional[ManifestReliabilityEngine] = None,
        calibrator_registry: Optional[CalibratorRegistry] = None,
        apply_calibrated_video_checkpoint: bool = False,
        mitigate_poisoning: bool = False,
        poisoning_config: Optional[PoisoningMitigationConfig] = None,
    ):
        self._custom_weights = weights is not None
        self.weights = weights or DEFAULT_DETECTOR_WEIGHTS.copy()
        self.reliability_engine = reliability_engine or ManifestReliabilityEngine()
        self.apply_calibrated_video_checkpoint = apply_calibrated_video_checkpoint
        self.mitigate_poisoning = mitigate_poisoning
        self.poisoning_config = poisoning_config or PoisoningMitigationConfig()
        self.calibrator_registry = calibrator_registry or CalibratorRegistry(
            apply_calibrated_video_checkpoint=apply_calibrated_video_checkpoint
        )

    def _assess_claims(
        self,
        claims: List[ForensicClaim],
        conditions: Optional[OperatingConditions],
    ) -> Tuple[
        Dict[str, CalibrationOutcome],
        Dict[str, ConditionReliabilityAssessment],
        List[str],
        List[str],
    ]:
        """Run Task 3 calibration and manifest per-condition reliability over all claims."""
        cal_outcomes: Dict[str, CalibrationOutcome] = {}
        assessments: Dict[str, ConditionReliabilityAssessment] = {}
        all_warnings: List[str] = []
        fatal_warnings: List[str] = []

        for c in claims:
            manifest = self.reliability_engine.get_manifest(c.detector_id, c.model_version)
            gap = is_coverage_gap(c)
            cal_out = self.calibrator_registry.calibrate_score(
                c.detector_id,
                c.confidence,
                model_version=c.model_version,
                coverage_gap=gap,
                manifest=manifest,
            )
            cal_for_eval = cal_out.calibrated_confidence if cal_out.calibrator_applied else None
            claim_for_eval = c
            if self.mitigate_poisoning and conditions is not None and c.flags:
                filtered_flags = list(c.flags)
                if conditions.mean_luminance is not None and conditions.mean_luminance >= 55.0:
                    filtered_flags = [
                        fl for fl in filtered_flags
                        if fl not in ("low_light_attenuation", "insufficient_lighting")
                    ]
                if conditions.duration_seconds is not None and conditions.duration_seconds >= 5.0:
                    filtered_flags = [
                        fl for fl in filtered_flags
                        if fl not in ("short_clip_attenuation", "marginal_duration")
                    ]
                if filtered_flags != c.flags:
                    claim_for_eval = c.model_copy(update={"flags": filtered_flags})
            assess = self.reliability_engine.evaluate_claim(
                claim_for_eval,
                conditions=conditions,
                is_coverage_gap=gap,
                calibrated_confidence=cal_for_eval,
                all_claims=claims,
            )
            cal_outcomes[c.detector_id] = cal_out
            assessments[c.detector_id] = assess

            if gap:
                if assess.is_advisory_gap:
                    all_warnings.append(
                        f"Advisory Gap: Detector '{c.detector_id}' not applicable due to absent secondary modality."
                    )
                else:
                    msg = (
                        f"Coverage Gap: Detector '{c.detector_id}' could not evaluate input due to "
                        "missing modality or prerequisite."
                    )
                    all_warnings.append(msg)
                    fatal_warnings.append(msg)
            elif assess.is_fatal_gap:
                msg = (
                    f"Fatal Reliability Gap: Detector '{c.detector_id}' violated critical operating "
                    f"constraint ({', '.join(assess.applied_conditions)})."
                )
                all_warnings.append(msg)
                fatal_warnings.append(msg)

        return cal_outcomes, assessments, all_warnings, fatal_warnings

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

        # Step 1: Calibrate, evaluate manifest condition reliability, and analyze disagreement
        cal_outcomes, assessments, coverage_warnings, fatal_warnings = self._assess_claims(claims, conditions)
        analysis: DisagreementAnalysis = evaluate_disagreement(claims)

        # Step 2: Route by dispute necessity
        if not analysis.requires_arbitration:
            return self._synthesize_consensus_verdict(
                claims=claims,
                analysis=analysis,
                verdict_id=verdict_id,
                job_id=resolved_job_id,
                evidence_hash=evidence_hash,
                coverage_warnings=coverage_warnings,
                fatal_warnings=fatal_warnings,
                cal_outcomes=cal_outcomes,
                assessments=assessments,
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
            fatal_warnings=fatal_warnings,
            cal_outcomes=cal_outcomes,
            assessments=assessments,
        )

    def _synthesize_consensus_verdict(
        self,
        claims: List[ForensicClaim],
        analysis: DisagreementAnalysis,
        verdict_id: str,
        job_id: str,
        evidence_hash: str,
        coverage_warnings: List[str],
        fatal_warnings: Optional[List[str]] = None,
        cal_outcomes: Optional[Dict[str, CalibrationOutcome]] = None,
        assessments: Optional[Dict[str, ConditionReliabilityAssessment]] = None,
    ) -> CourtAdmissibleVerdict:
        """Fast-path consensus synthesis with Task 3 calibration & manifest reliability."""
        if cal_outcomes is None or assessments is None:
            cal_outcomes, assessments, coverage_warnings, fatal_warnings = self._assess_claims(claims, None)
        fatal_list = fatal_warnings or []

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
                    "All submitted detectors reported coverage gaps or inapplicable inputs. "
                    "Per AEGIS Forensic Integrity standards, inconclusive media cannot be certified authentic."
                ),
                coverage_warnings=coverage_warnings,
                siem_alert_tier="P2_ELEVATED",
                evidence_manifest_hash=evidence_hash,
            )

        adjudications: List[ClaimAdjudication] = []
        weighted_conf_sum = 0.0
        total_weight = 0.0
        notes: List[str] = []

        for c in active_claims:
            cal_out = cal_outcomes[c.detector_id]
            assess = assessments[c.detector_id]
            w = (
                self.weights.get(c.detector_id, assess.base_weight) * assess.weight_multiplier
                if self._custom_weights
                else assess.effective_weight
            )
            eff_conf = assess.adjusted_confidence
            discount_note = None

            if "rppg_invalid_bpm_synthetic_discount" in assess.applied_conditions:
                eff_conf = 0.50
                w *= 0.15
                discount_note = "Rule 7 Applied (Secondary Zero/Invalid BPM Proxy Discounted)"
                notes.append(discount_note)
            elif "image_forensic_signal_corroboration" in assess.applied_conditions:
                discount_note = "Rule 8 Applied (Image FFT/Metadata Corroboration)"
                notes.append(discount_note)
            elif "text_multi_signal_ai_corroboration" in assess.applied_conditions:
                discount_note = "Rule 8 Applied (Text Perplexity/Burstiness/Binoculars AI Corroboration)"
                notes.append(discount_note)
            elif "text_multi_signal_human_corroboration" in assess.applied_conditions:
                discount_note = "Rule 8 Applied (Text Natural Perplexity/Burstiness Human Corroboration)"
                notes.append(discount_note)

            weighted_conf_sum += eff_conf * w
            total_weight += w

            adjudications.append(
                ClaimAdjudication(
                    detector_id=c.detector_id,
                    original_polarity=c.polarity,
                    original_confidence=c.confidence,
                    accepted_confidence=round(eff_conf, 4),
                    weight_assigned=round(w, 4),
                    discount_reason=discount_note,
                    findings_retained=[c.claim],
                    authority_tier=assess.authority_tier,
                    pre_calibration_confidence=round(c.confidence, 4),
                    calibration_checkpoint=cal_out.checkpoint_name if cal_out.calibrator_applied else None,
                    applied_conditions=list(assess.applied_conditions),
                )
            )

        calibrated_score = round(weighted_conf_sum / max(total_weight, 1e-6), 4)

        rejected_detectors: set[str] = set()
        if self.mitigate_poisoning:
            calibrated_score, pg_report = apply_adjudication_mitigations(
                active_claims=active_claims,
                adjudications=adjudications,
                cfg=self.poisoning_config,
            )
            rejected_detectors = set(pg_report.rejected_detectors)
            notes.extend(pg_report.notes)
            has_img_corrob = check_corroboration_quorum(
                active_claims,
                ("image-mirror", "detector_image"),
                ("image-frequency",),
                ("frequency_anomaly",),
                rejected_detectors=rejected_detectors,
            )
            has_txt_corrob = check_corroboration_quorum(
                active_claims,
                ("text-desklib", "detector_text"),
                ("text-stylometry", "text-perplexity"),
                ("uniform_low_perplexity", "stylometry_synthetic"),
                rejected_detectors=rejected_detectors,
            )
        else:
            # Multi-signal corroboration boost in consensus
            has_img_corrob = any(c.detector_id in ("image-mirror", "detector_image") and c.confidence >= 0.70 for c in active_claims) and any("frequency_anomaly" in c.flags or (c.detector_id == "image-frequency" and c.confidence >= 0.70) for c in active_claims)
            has_txt_corrob = any(c.detector_id in ("text-desklib", "detector_text") and c.confidence >= 0.70 for c in active_claims) and any("uniform_low_perplexity" in c.flags or "stylometry_synthetic" in c.flags or (c.detector_id in ("text-stylometry", "text-perplexity") and c.confidence >= 0.70) for c in active_claims)

        if has_img_corrob:
            calibrated_score = max(calibrated_score, 0.90)
        if has_txt_corrob:
            calibrated_score = max(calibrated_score, 0.92)

        # Secondary proxy authority safeguard: a secondary proxy alone cannot push verdict >= SYNTHETIC
        non_gap_primary_synth = any(
            not assessments[c.detector_id].cannot_solely_certify_synthetic
            and assessments[c.detector_id].adjusted_confidence >= SYNTHETIC_POLARITY_THRESHOLD
            for c in active_claims
        )
        any_secondary_synth = any(
            assessments[c.detector_id].cannot_solely_certify_synthetic
            and (c.confidence >= SYNTHETIC_POLARITY_THRESHOLD or assessments[c.detector_id].adjusted_confidence >= 0.55)
            for c in active_claims
        )
        if any_secondary_synth and not non_gap_primary_synth and calibrated_score >= SYNTHETIC_VERDICT_THRESHOLD:
            calibrated_score = min(calibrated_score, 0.58)
            notes.append(
                "Secondary Authority Cap: Secondary proxy synthetic claim without primary corroboration "
                "cannot certify SYNTHETIC; held in UNCERTAIN."
            )

        # Uncalibrated baseline single-witness safeguard for AUTHENTIC in multi-detector runs (e.g. M2-L12)
        auth_witnesses = [
            adj for adj in adjudications
            if adj.accepted_confidence <= AUTHENTIC_POLARITY_THRESHOLD
        ]
        all_auth_uncalibrated = bool(auth_witnesses) and all(
            (c.model_version or "").strip().lower() in UNCALIBRATED_MODEL_VERSIONS
            and not cal_outcomes[c.detector_id].calibrator_applied
            and not self.apply_calibrated_video_checkpoint
            for c in active_claims
            if any(a.detector_id == c.detector_id for a in auth_witnesses)
        )
        uncalibrated_auth_hold = (
            calibrated_score <= AUTHENTIC_VERDICT_THRESHOLD
            and len(claims) > 1
            and len(auth_witnesses) < 2
            and all_auth_uncalibrated
        )
        if uncalibrated_auth_hold:
            calibrated_score = round(max(calibrated_score, 0.40), 4)
            uncal_note = (
                "Uncalibrated Primary Abstention (M2-L12): Uncalibrated baseline detector asserting AUTHENTIC "
                "without corroboration held in UNCERTAIN to prevent false-authentics."
            )
            notes.append(uncal_note)
            for adj in auth_witnesses:
                if adj.discount_reason is None:
                    adj.discount_reason = uncal_note

        if calibrated_score >= SYNTHETIC_VERDICT_THRESHOLD:
            final_verdict = JudgeVerdictClass.SYNTHETIC
            siem_tier = "P1_CRITICAL"
        elif calibrated_score <= AUTHENTIC_VERDICT_THRESHOLD:
            final_verdict = JudgeVerdictClass.AUTHENTIC
            siem_tier = "P4_INFORMATIONAL"
        elif fatal_list:
            final_verdict = JudgeVerdictClass.INTEGRITY_UNKNOWN
            siem_tier = "P2_ELEVATED"
        else:
            final_verdict = JudgeVerdictClass.UNCERTAIN
            siem_tier = "P2_ELEVATED"

        conf_margin = round(analysis.confidence_spread / 2.0, 3)
        interval = [max(0.0, round(calibrated_score - conf_margin, 3)), min(1.0, round(calibrated_score + conf_margin, 3))]

        note_suffix = (" Constraints: " + "; ".join(notes)) if notes else ""
        justification = (
            f"CONSENSUS RULING: Detectors operate in alignment (confidence spread {analysis.confidence_spread:.2f} "
            f"< threshold). Calibrated ensemble score of {calibrated_score:.2f} confirms {final_verdict.value} status."
            f"{note_suffix}"
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
        fatal_warnings: Optional[List[str]] = None,
        cal_outcomes: Optional[Dict[str, CalibrationOutcome]] = None,
        assessments: Optional[Dict[str, ConditionReliabilityAssessment]] = None,
    ) -> CourtAdmissibleVerdict:
        """Full Forensic Precedence Matrix dispute resolution."""
        if cal_outcomes is None or assessments is None:
            cal_outcomes, assessments, coverage_warnings, fatal_warnings = self._assess_claims(claims, conditions)
        fatal_list = fatal_warnings or []

        claims_by_id = {c.detector_id: c for c in claims}
        adjudications: List[ClaimAdjudication] = []
        discount_reasons: List[str] = []

        # Operating environment facts
        mean_lum = conditions.mean_luminance if conditions and conditions.mean_luminance is not None else 100.0
        duration_s = conditions.duration_seconds if conditions and conditions.duration_seconds is not None else 10.0

        vc_claim = claims_by_id.get("video-classifier")
        rppg_claim = claims_by_id.get("rppg")
        sync_claim = claims_by_id.get("syncnet")
        aasist_claim = claims_by_id.get("aasist")
        img_claim = claims_by_id.get("detector_image") or claims_by_id.get("image")
        txt_claim = claims_by_id.get("detector_text")

        def _conf(cl: Optional[ForensicClaim]) -> float:
            if cl is None:
                return 0.5
            return assessments[cl.detector_id].adjusted_confidence

        active_claims_pre = [c for c in claims if not is_coverage_gap(c)]
        blocked_poisoned_ids: set[str] = set()
        if self.mitigate_poisoning and active_claims_pre:
            if self.poisoning_config.enable_outlier_rejection:
                pre_outliers, _, _ = detect_outlier_detectors(
                    active_claims_pre,
                    {c.detector_id: assessments[c.detector_id].adjusted_confidence for c in active_claims_pre},
                    self.poisoning_config,
                )
                blocked_poisoned_ids.update(pre_outliers)
            if self.poisoning_config.enable_reliability_caps:
                for cl in active_claims_pre:
                    is_bad, _ = inspect_claim_miscalibration(cl, self.poisoning_config)
                    if is_bad:
                        blocked_poisoned_ids.add(cl.detector_id)

        def _trusted(cl: Optional[ForensicClaim]) -> bool:
            return cl is not None and not is_coverage_gap(cl) and cl.detector_id not in blocked_poisoned_ids

        vc_conf = _conf(vc_claim)
        rppg_conf = _conf(rppg_claim)
        sync_conf = _conf(sync_claim)
        aasist_conf = _conf(aasist_claim)

        # ── Precedence Rule 1: Low-Light Score Inversion Trap on rPPG ─────────
        rppg_discounted = False
        rppg_rule7_mode: Optional[str] = None  # "7A_uncertain" or "7B_calibrated"
        if rppg_claim and not is_coverage_gap(rppg_claim):
            has_low_light_flag = "low_light_attenuation" in rppg_claim.flags or "insufficient_lighting" in rppg_claim.flags
            if self.mitigate_poisoning and conditions and conditions.mean_luminance is not None and conditions.mean_luminance >= 55.0:
                has_low_light_flag = False
            if mean_lum < 40.0 or has_low_light_flag:
                if rppg_claim.confidence > 0.60:
                    rppg_discounted = True
                    discount_reasons.append(
                        f"Rule 1 Applied (Low-Light Inversion): rPPG synthetic claim (conf={rppg_claim.confidence:.2f}) "
                        f"discounted due to low luminance ({mean_lum:.1f}/255). Chrominance collapse mimics synthetic flatness."
                    )

        # ── Precedence Rule 2: Short Clip on rPPG (< 2.0s) ────────────────────
        if rppg_claim and not is_coverage_gap(rppg_claim) and not rppg_discounted:
            has_short_flag = "short_clip_attenuation" in rppg_claim.flags
            if self.mitigate_poisoning and conditions and conditions.duration_seconds is not None and conditions.duration_seconds >= 5.0:
                has_short_flag = False
            if duration_s < 2.0 or has_short_flag:
                rppg_discounted = True
                discount_reasons.append(
                    f"Rule 2 Applied (Short Duration): rPPG signal discounted (duration {duration_s:.1f}s < 2.0s "
                    "filter convergence minimum)."
                )

        # ── Precedence Rule 3: Face-Swap Pulse Preservation ───────────────────
        face_swap_case = False
        if _trusted(vc_claim) and rppg_claim and not is_coverage_gap(rppg_claim):
            if vc_conf >= 0.70 and rppg_conf <= 0.35 and not rppg_discounted:
                face_swap_case = True
                discount_reasons.append(
                    "Rule 3 Applied (Face-Swap Inpainting): video-classifier detected spatial warping / boundary anomalies, "
                    "while rPPG detected authentic cardiac rhythm. Physiological pulse is preserved from original donor body; "
                    "spatial face manipulation overrides authentic physiological signal."
                )

        # ── Precedence Rule 4: Dubbing / Non-English Content on SyncNet ───────
        dubbing_case = False
        if sync_claim and not is_coverage_gap(sync_claim):
            if sync_conf >= 0.70:
                other_authentic = []
                if vc_claim and not is_coverage_gap(vc_claim) and vc_conf <= 0.35:
                    other_authentic.append(vc_claim)
                if rppg_claim and not is_coverage_gap(rppg_claim) and not rppg_discounted and rppg_conf <= 0.35:
                    other_authentic.append(rppg_claim)
                if aasist_claim and not is_coverage_gap(aasist_claim) and aasist_conf <= 0.35:
                    other_authentic.append(aasist_claim)

                if len(other_authentic) >= 1 and (not self.mitigate_poisoning or len(other_authentic) >= 2 or len(active_claims_pre) <= 2):
                    dubbing_case = True
                    discount_reasons.append(
                        "Rule 4 Applied (Audio Dubbing): SyncNet lip-desync discounted as post-production translation "
                        "or dubbing because spatial and physiological detectors verify authentic visual human presence."
                    )

        # ── Precedence Rule 5: Synthetic Voice / Audio Clone Injection ────────
        voice_clone_case = False
        if _trusted(aasist_claim):
            if aasist_conf >= 0.70:
                visual_authentic = []
                if vc_claim and not is_coverage_gap(vc_claim) and vc_conf <= 0.35:
                    visual_authentic.append(vc_claim.detector_id)
                if rppg_claim and not is_coverage_gap(rppg_claim) and not rppg_discounted and rppg_conf <= 0.35:
                    visual_authentic.append(rppg_claim.detector_id)

                if visual_authentic:
                    voice_clone_case = True
                    discount_reasons.append(
                        f"Rule 5 Applied (Synthetic Voice / Audio Clone Injection): AASIST detected synthetic/cloned speech "
                        f"(conf={aasist_conf:.2f}) while visual detectors ({visual_authentic}) verify authentic footage. "
                        "In multi-modal forensics, synthetic audio overrides visual donor authenticity to confirm a voice-clone attack."
                    )

        # ── Precedence Rule 6: Visual Tampering Over Authentic Audio ─────────
        visual_tampering_case = False
        if _trusted(vc_claim) and vc_conf >= 0.70:
            if aasist_claim and not is_coverage_gap(aasist_claim) and aasist_conf <= 0.35:
                visual_tampering_case = True
                discount_reasons.append(
                    "Rule 6 Applied (Visual Tampering Over Authentic Audio): video-classifier detected spatial manipulation "
                    f"(conf={vc_conf:.2f}) over authentic human speech. Spatial tampering overrides authentic audio track."
                )

        # ── Precedence Rule 7: Zero / Out-of-Band BPM Proxy Conflict ──────────
        if (
            rppg_claim
            and not is_coverage_gap(rppg_claim)
            and not rppg_discounted
            and "rppg_invalid_bpm_synthetic_discount" in assessments[rppg_claim.detector_id].applied_conditions
        ):
            rppg_discounted = True
            vc_is_calibrated = bool(
                vc_claim
                and (
                    cal_outcomes[vc_claim.detector_id].calibrator_applied
                    or self.apply_calibrated_video_checkpoint
                )
            )
            if vc_claim and vc_conf <= AUTHENTIC_VERDICT_THRESHOLD and not vc_is_calibrated:
                rppg_rule7_mode = "7A_uncertain"
                discount_reasons.append(
                    "Rule 7A Applied (Secondary Zero-BPM Proxy Invalidated; Uncalibrated Primary Held in UNCERTAIN): "
                    "rPPG emitted synthetic score with 0.0/invalid BPM, while video-classifier carries uncalibrated baseline "
                    "weights; holding UNCERTAIN rather than certifying AUTHENTIC or INTEGRITY_UNKNOWN."
                )
            else:
                rppg_rule7_mode = "7B_calibrated"
                discount_reasons.append(
                    "Rule 7B Applied (Secondary Zero-BPM Proxy Discounted Against Verified Primary): "
                    "rPPG spectral anomaly with 0.0/invalid BPM discounted per capability manifest."
                )

        # ── Precedence Rule 8: Image Intra-Modality Arbitration (MIRROR vs. Frequency vs. EXIF) ──
        mirror_claim = claims_by_id.get("image-mirror") or img_claim
        freq_claim = claims_by_id.get("image-frequency")
        exif_claim = claims_by_id.get("image-exif")

        exif_discounted = False
        freq_discounted = False
        image_corroborated_synthetic = False

        img_flags = set()
        if img_claim:
            img_flags.update(img_claim.flags)
        if freq_claim:
            img_flags.update(freq_claim.flags)
        if exif_claim:
            img_flags.update(exif_claim.flags)

        has_freq_anomaly = "frequency_anomaly" in img_flags or (freq_claim is not None and freq_claim.confidence >= 0.65)
        has_exif_missing = "exif_missing" in img_flags or (exif_claim is not None and exif_claim.confidence >= 0.50)

        # 7A: Missing EXIF on clean visual/spectral image is non-inculpatory (social media stripping)
        if mirror_claim and not is_coverage_gap(mirror_claim) and mirror_claim.confidence <= 0.35 and not has_freq_anomaly:
            if has_exif_missing or exif_claim:
                exif_discounted = True
                discount_reasons.append(
                    "Rule 7A Applied (Benign Metadata Stripping): Absent EXIF metadata discounted because visual "
                    "backbone and frequency spectrum confirm authentic structure; metadata stripping is standard on web/social platforms."
                )

        # 7B: Deepfake spatial artifacts override intact camera EXIF (forged / pasted metadata)
        if _trusted(mirror_claim) and mirror_claim.confidence >= 0.70:
            if exif_claim and exif_claim.confidence <= 0.35:
                exif_discounted = True
                discount_reasons.append(
                    f"Rule 7B Applied (Spoofed EXIF Metadata): Visual backbone detected deepfake synthesis "
                    f"(conf={mirror_claim.confidence:.2f}) over intact camera EXIF. EXIF containers are easily copied or preserved "
                    "from original donor captures and do not override spatial manipulation."
                )
            if freq_claim and freq_claim.confidence <= 0.35:
                freq_discounted = True
                discount_reasons.append(
                    f"Rule 7B Applied (Visual Manipulation Over Frequency): Visual backbone detected deepfake synthesis "
                    f"(conf={mirror_claim.confidence:.2f}) over clean frequency spectrum; advanced synthesis bypasses crude grid checks."
                )

        # 7C: Corroboration of Deepfake Model and Frequency-Domain Grid Artifacts
        if mirror_claim and not is_coverage_gap(mirror_claim) and mirror_claim.confidence >= 0.65 and has_freq_anomaly:
            image_corroborated_synthetic = True
            discount_reasons.append(
                "Rule 7C Applied (Frequency Corroboration): Visual deepfake detection corroborated by high-frequency upsampling "
                "grid artifacts. Multi-signal alignment indicates synthetic generator architecture."
            )

        # 7D: Isolated Frequency Anomaly on Clean Visual/Authentic Canvas
        if mirror_claim and not is_coverage_gap(mirror_claim) and mirror_claim.confidence <= 0.30 and has_freq_anomaly:
            freq_discounted = True
            discount_reasons.append(
                "Rule 7D Applied (Isolated Spectral Anomaly): Frequency anomaly attenuated because visual structure shows no "
                "synthesis artifacts; likely attributable to JPEG block recompression or resizing."
            )

        # ── Precedence Rule 8: Text Intra-Modality Arbitration (Desklib vs. Stylometric vs. Perplexity) ──
        text_claim = claims_by_id.get("detector_text")
        desklib_claim = claims_by_id.get("text-desklib") or text_claim
        stylo_claim = claims_by_id.get("text-stylometry")
        perp_claim = claims_by_id.get("text-perplexity")

        stylo_discounted = False
        perp_discounted = False
        text_corroborated_synthetic = False

        text_flags = set()
        if text_claim:
            text_flags.update(text_claim.flags)
        if stylo_claim:
            text_flags.update(stylo_claim.flags)
        if perp_claim:
            text_flags.update(perp_claim.flags)

        has_stylo_synthetic = "stylometry_synthetic" in text_flags or "low_vocabulary_diversity" in text_flags or (stylo_claim is not None and stylo_claim.confidence >= 0.65)
        has_low_perp = "uniform_low_perplexity" in text_flags or (perp_claim is not None and perp_claim.confidence >= 0.65)

        # 8A: Corroborated Neural + Stylometric / Perplexity Synthetic Signal
        if desklib_claim and not is_coverage_gap(desklib_claim) and desklib_claim.confidence >= 0.65:
            if has_stylo_synthetic or has_low_perp:
                text_corroborated_synthetic = True
                discount_reasons.append(
                    "Rule 8A Applied (Multi-Signal AI Authorship): Desklib neural classifier corroborated by uniformly low "
                    "perplexity and low sentence-length variation, confirming synthetic text generation."
                )

        # 8B: Repetitive Technical/Academic Human Text (Vocabulary Compression)
        if desklib_claim and not is_coverage_gap(desklib_claim) and desklib_claim.confidence <= 0.35:
            if has_stylo_synthetic or (stylo_claim is not None and stylo_claim.confidence >= 0.60):
                stylo_discounted = True
                discount_reasons.append(
                    "Rule 8B Applied (Technical Jargon Exception): Stylometric repetition / low vocabulary diversity discounted "
                    "because semantic neural classifier confirms authentic human authorship; typical of legal or scientific terminology."
                )

        # 8C: Paraphrased / Polished AI Text (Neural Precedence Over Stylometric Burstiness)
        if _trusted(desklib_claim) and desklib_claim.confidence >= 0.70:
            if stylo_claim is not None and stylo_claim.confidence <= 0.35:
                stylo_discounted = True
                discount_reasons.append(
                    "Rule 8C Applied (Neural Precedence in Paraphrased AI): Desklib deep semantic features detect LLM synthesis "
                    f"(conf={desklib_claim.confidence:.2f}) despite human-like stylometric variation (paraphrasing/prompt engineering)."
                )
            if perp_claim is not None and perp_claim.confidence <= 0.35:
                perp_discounted = True
                discount_reasons.append(
                    "Rule 8C Applied (Neural Precedence Over Perplexity): Desklib deep semantic features detect LLM synthesis "
                    f"(conf={desklib_claim.confidence:.2f}) despite high perplexity variance."
                )

        # ── Precedence Rule Multi-Signal Corroboration Note ──
        for mod_claim in (img_claim, txt_claim):
            if mod_claim and not is_coverage_gap(mod_claim):
                mod_assess = assessments[mod_claim.detector_id]
                if "image_forensic_signal_corroboration" in mod_assess.applied_conditions:
                    discount_reasons.append(
                        f"Rule Corroboration Applied (Image): {mod_claim.detector_id} reinforced by FFT/metadata signals."
                    )
                elif any(
                    k in mod_assess.applied_conditions
                    for k in ("text_multi_signal_ai_corroboration", "text_multi_signal_human_corroboration")
                ):
                    discount_reasons.append(
                        f"Rule Corroboration Applied (Text): {mod_claim.detector_id} reinforced by perplexity/burstiness/Binoculars."
                    )

        # ── Execute Weighting & Adjudication ──────────────────────────────────
        active_claims = [c for c in claims if not is_coverage_gap(c)]
        weighted_conf_sum = 0.0
        total_weight = 0.0

        for c in active_claims:
            cal_out = cal_outcomes[c.detector_id]
            assess = assessments[c.detector_id]
            base_w = (
                self.weights.get(c.detector_id, assess.base_weight) * assess.weight_multiplier
                if self._custom_weights
                else assess.effective_weight
            )
            accepted_conf = assess.adjusted_confidence
            discount_note = None

            if c.detector_id == "rppg" and rppg_discounted:
                if rppg_rule7_mode is not None:
                    base_w *= 0.15
                    accepted_conf = 0.50
                    discount_note = (
                        "Discounted under Rule 7A (Zero-BPM Proxy Invalidated; Uncalibrated Primary)"
                        if rppg_rule7_mode == "7A_uncertain"
                        else "Discounted under Rule 7B (Zero-BPM Proxy vs Verified Primary)"
                    )
                else:
                    base_w *= 0.10  # 90% discount for Rules 1 & 2
                    accepted_conf = 0.50
                    discount_note = "Discounted under Precedence Rule (Low Light or Short Clip)"
            elif c.detector_id == "rppg" and face_swap_case:
                base_w *= 0.20  # 80% discount
                discount_note = "Discounted under Face-Swap Inpainting Rule"
            elif c.detector_id == "syncnet" and dubbing_case:
                base_w *= 0.20  # 80% discount
                discount_note = "Discounted under Audio Dubbing Rule"
            elif c.detector_id in ("video-classifier", "rppg") and voice_clone_case:
                base_w *= 0.25  # 75% discount
                discount_note = "Discounted under Synthetic Voice Injection Rule (authentic visual donor footage)"
            elif c.detector_id == "aasist" and visual_tampering_case:
                base_w *= 0.25  # 75% discount
                discount_note = "Discounted under Visual Tampering Rule (authentic speech over manipulated video)"
            elif c.detector_id == "image-exif" and exif_discounted:
                base_w *= 0.15  # 85% discount
                accepted_conf = 0.50
                discount_note = "Discounted under Rule 7A / Rule 7B (EXIF subordinate to spatial/spectral analysis)"
            elif c.detector_id == "image-frequency" and freq_discounted:
                base_w *= 0.35  # 65% discount
                accepted_conf = 0.45
                discount_note = "Discounted under Rule 7B / Rule 7D (isolated frequency anomaly on authentic visual)"
            elif c.detector_id == "text-stylometry" and stylo_discounted:
                base_w *= 0.25  # 75% discount
                accepted_conf = 0.50
                discount_note = "Discounted under Rule 8B / Rule 8C (stylometry subordinate to deep neural classifier)"
            elif c.detector_id == "text-perplexity" and perp_discounted:
                base_w *= 0.20  # 80% discount
                accepted_conf = 0.50
                discount_note = "Discounted under Rule 8C (perplexity subordinate to deep neural classifier)"

            weighted_conf_sum += accepted_conf * base_w
            total_weight += base_w

            adjudications.append(
                ClaimAdjudication(
                    detector_id=c.detector_id,
                    original_polarity=c.polarity,
                    original_confidence=c.confidence,
                    accepted_confidence=round(accepted_conf, 4),
                    weight_assigned=round(base_w, 4),
                    discount_reason=discount_note,
                    findings_retained=[c.claim],
                    authority_tier=assess.authority_tier,
                    pre_calibration_confidence=round(c.confidence, 4),
                    calibration_checkpoint=cal_out.checkpoint_name if cal_out.calibrator_applied else None,
                    applied_conditions=list(assess.applied_conditions),
                )
            )

        calibrated_score = round(weighted_conf_sum / max(total_weight, 1e-6), 4)

        rejected_detectors: set[str] = set()
        if self.mitigate_poisoning:
            calibrated_score, pg_report = apply_adjudication_mitigations(
                active_claims=active_claims,
                adjudications=adjudications,
                cfg=self.poisoning_config,
            )
            rejected_detectors = set(pg_report.rejected_detectors) | set(blocked_poisoned_ids)
            discount_reasons.extend(pg_report.notes)
            has_img_corrob = check_corroboration_quorum(
                active_claims,
                ("image-mirror", "detector_image"),
                ("image-frequency",),
                ("frequency_anomaly",),
                rejected_detectors=rejected_detectors,
            )
            has_txt_corrob = check_corroboration_quorum(
                active_claims,
                ("text-desklib", "detector_text"),
                ("text-stylometry", "text-perplexity"),
                ("uniform_low_perplexity", "stylometry_synthetic"),
                rejected_detectors=rejected_detectors,
            )
            if not has_img_corrob:
                image_corroborated_synthetic = False
            if not has_txt_corrob:
                text_corroborated_synthetic = False
        else:
            # Multi-signal corroboration boost in consensus
            has_img_corrob = any(c.detector_id in ("image-mirror", "detector_image") and c.confidence >= 0.70 for c in active_claims) and any("frequency_anomaly" in c.flags or (c.detector_id == "image-frequency" and c.confidence >= 0.70) for c in active_claims)
            has_txt_corrob = any(c.detector_id in ("text-desklib", "detector_text") and c.confidence >= 0.70 for c in active_claims) and any("uniform_low_perplexity" in c.flags or "stylometry_synthetic" in c.flags or (c.detector_id in ("text-stylometry", "text-perplexity") and c.confidence >= 0.70) for c in active_claims)

        if has_img_corrob:
            calibrated_score = max(calibrated_score, 0.90)
        if has_txt_corrob:
            calibrated_score = max(calibrated_score, 0.92)

        # If face-swap or voice-clone or visual tampering detected, enforce minimum synthetic score of 0.85
        if face_swap_case:
            calibrated_score = max(calibrated_score, 0.85)
        if voice_clone_case:
            calibrated_score = max(calibrated_score, 0.85)
        if visual_tampering_case:
            calibrated_score = max(calibrated_score, 0.85)
        if image_corroborated_synthetic and calibrated_score < 0.90:
            calibrated_score = max(calibrated_score, 0.92)
        if text_corroborated_synthetic and calibrated_score < 0.90:
            calibrated_score = max(calibrated_score, 0.93)

        if rppg_rule7_mode == "7A_uncertain":
            # Hold uncalibrated primary vs invalidated zero-BPM proxy safely inside UNCERTAIN band
            calibrated_score = round(min(max(calibrated_score, 0.42), 0.58), 4)

        # Secondary proxy authority safeguard inside dispute resolution
        non_gap_primary_synth = any(
            not assessments[c.detector_id].cannot_solely_certify_synthetic
            and c.detector_id not in rejected_detectors
            and assessments[c.detector_id].adjusted_confidence >= SYNTHETIC_POLARITY_THRESHOLD
            for c in active_claims
        )
        if not non_gap_primary_synth and calibrated_score >= SYNTHETIC_VERDICT_THRESHOLD:
            calibrated_score = 0.58

        # Step 4: Final Verdict Classification
        if calibrated_score >= SYNTHETIC_VERDICT_THRESHOLD:
            final_verdict = JudgeVerdictClass.SYNTHETIC
            siem_tier = "P1_CRITICAL"
        elif calibrated_score <= AUTHENTIC_VERDICT_THRESHOLD:
            final_verdict = JudgeVerdictClass.AUTHENTIC
            siem_tier = "P4_INFORMATIONAL"
        elif fatal_list:
            final_verdict = JudgeVerdictClass.INTEGRITY_UNKNOWN
            siem_tier = "P2_ELEVATED"
        else:
            final_verdict = JudgeVerdictClass.UNCERTAIN
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
