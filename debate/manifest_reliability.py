"""
AEGIS Debate & Arbitration Layer — Manifest Per-Condition Reliability Engine.

Reads capability manifests (capability_manifests/*.json) and dynamically computes
per-detector authority tiers, condition-specific weights, confidence damping,
and cross-examination findings based on actual media OperatingConditions and
detector diagnostic flags/metrics.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from debate.schemas import (
    ClaimPolarity,
    CrossExaminationFinding,
    ForensicClaim,
    OperatingConditions,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFESTS_DIR = _REPO_ROOT / "capability_manifests"

DEFAULT_AUTHORITY_TIERS: Dict[str, str] = {
    "video-classifier": "primary",
    "syncnet": "primary",
    "aasist": "primary",
    "detector_image": "primary",
    "image": "primary",
    "detector_text": "primary",
    "rppg": "secondary_proxy",
    "streaming-rppg": "secondary_proxy",
}

DEFAULT_BASE_WEIGHTS: Dict[str, float] = {
    "video-classifier": 1.5,
    "detector_image": 1.5,
    "image": 1.5,
    "detector_text": 1.5,
    "syncnet": 1.2,
    "aasist": 1.2,
    "rppg": 0.45,
    "streaming-rppg": 0.45,
}

# Expected single-modality gaps (e.g. SyncNet when video has no audio track) should
# NOT force healthy visual/text/image evaluations into INTEGRITY_UNKNOWN.
ADVISORY_ONLY_GAP_DETECTORS = {"syncnet", "aasist"}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _shrink_toward_neutral(prob: float, factor: float) -> float:
    """Applies damping factor in [0, 1] relative to 0.50 neutral point."""
    f = _clamp01(factor)
    return _clamp01(0.5 + (float(prob) - 0.5) * f)


@dataclass
class ConditionReliabilityAssessment:
    """Computed reliability profile for a single detector claim under current conditions."""

    detector_id: str
    authority_tier: str
    base_weight: float
    weight_multiplier: float
    effective_weight: float
    confidence_damping: float
    adjusted_confidence: float
    is_fatal_gap: bool = False
    is_advisory_gap: bool = False
    cannot_solely_certify_synthetic: bool = False
    applied_conditions: List[str] = field(default_factory=list)
    findings: List[CrossExaminationFinding] = field(default_factory=list)


class ManifestReliabilityEngine:
    """
    Evaluates detector reliability conditioned on manifest rules, media
    OperatingConditions, and detector-level telemetry flags/metrics.
    """

    def __init__(self, manifests: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.manifests = manifests if manifests is not None else self.load_default_manifests()

    @staticmethod
    def load_default_manifests(manifests_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
        directory = manifests_dir or DEFAULT_MANIFESTS_DIR
        loaded: Dict[str, Dict[str, Any]] = {}
        if not directory.is_dir():
            return loaded
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                name = data.get("detector_name")
                if name:
                    loaded[name] = data
            except Exception as exc:
                logger.warning("Failed to load manifest %s: %s", path.name, exc)
        # Alias CommFor image manifest ('image.json') seamlessly onto 'detector_image'
        if "image" in loaded and "detector_image" in loaded:
            merged = dict(loaded["detector_image"])
            if "condition_reliability" not in merged and "condition_reliability" in loaded["image"]:
                merged["condition_reliability"] = loaded["image"]["condition_reliability"]
            loaded["detector_image_commfor"] = loaded["image"]
            loaded["detector_image"] = merged
        elif "image" in loaded and "detector_image" not in loaded:
            loaded["detector_image"] = loaded["image"]
        return loaded

    def get_manifest(self, detector_id: str, model_version: str = "") -> Dict[str, Any]:
        if detector_id == "detector_image" and "commfor" in (model_version or "").lower():
            if "image" in self.manifests:
                return self.manifests["image"]
        if detector_id in self.manifests:
            return self.manifests[detector_id]
        if detector_id == "detector_image" and "image" in self.manifests:
            return self.manifests["image"]
        if detector_id == "image" and "detector_image" in self.manifests:
            return self.manifests["detector_image"]
        return {}

    def evaluate_claim(
        self,
        claim: ForensicClaim,
        conditions: Optional[OperatingConditions] = None,
        *,
        is_coverage_gap: Optional[bool] = None,
        calibrated_confidence: Optional[float] = None,
        all_claims: Optional[List[ForensicClaim]] = None,
        extra_signals: Optional[Dict[str, Any]] = None,
    ) -> ConditionReliabilityAssessment:
        """Compute manifest-grounded weight, confidence damping, and cross-exam findings."""
        cond = conditions or claim.operating_conditions or OperatingConditions()
        manifest = self.get_manifest(claim.detector_id, claim.model_version)
        authority_tier = str(
            manifest.get("authority_tier")
            or DEFAULT_AUTHORITY_TIERS.get(claim.detector_id, "primary")
        )
        base_weight = float(
            manifest.get("base_reliability_weight")
            or DEFAULT_BASE_WEIGHTS.get(claim.detector_id, 1.0)
        )
        cannot_sole_synth = bool(
            manifest.get("cannot_solely_certify_synthetic", authority_tier == "secondary_proxy")
        )
        cond_rules: Dict[str, Any] = manifest.get("condition_reliability") or {}

        # Compute base post-attenuation score:
        # Preserve continuous score for calibrated outputs and primary Image/Text detectors
        # (so Rule 8 multi-signal tie-breaking can act on [0.35, 0.65] borderline scores).
        gap_flag = claim.coverage_gap if is_coverage_gap is None else bool(is_coverage_gap)
        comp_att = claim.attenuation_factors.composite_attenuation
        if calibrated_confidence is not None:
            base_conf = _shrink_toward_neutral(calibrated_confidence, comp_att)
        elif claim.detector_id in {"detector_image", "image", "detector_text"} and not gap_flag:
            base_conf = _shrink_toward_neutral(claim.confidence, comp_att)
        else:
            base_conf = _clamp01(claim.effective_confidence)
        weight_mult = 1.0
        cond_damping = 1.0
        adjusted = base_conf
        applied: List[str] = []
        findings: List[CrossExaminationFinding] = []
        fatal_gap = False
        advisory_gap = False
        det_id = claim.detector_id
        flags = set(claim.flags or [])
        manifest_src = f"manifest:{det_id}.json"

        # ── Handle coverage gaps (fatal vs advisory) ──────────────────────────
        if gap_flag or claim.polarity == ClaimPolarity.NOT_APPLICABLE:
            # Advisory only when an optional cross-modal detector (e.g. SyncNet/AASIST on
            # silent video) skips while at least one primary detector remains active.
            other_primary_active = any(
                (
                    c.detector_id != det_id
                    and DEFAULT_AUTHORITY_TIERS.get(c.detector_id, "primary") == "primary"
                    and not c.coverage_gap
                    and c.polarity != ClaimPolarity.NOT_APPLICABLE
                )
                for c in (all_claims or [])
            )
            if det_id in ADVISORY_ONLY_GAP_DETECTORS and other_primary_active and (
                cond.audio_present is False or "silent_video" in flags or "no_audio_track" in flags
            ):
                advisory_gap = True
                applied.append("advisory_modality_absent")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="advisory_coverage_gap",
                        severity="INFO",
                        finding=(
                            f"Detector '{det_id}' is not applicable (audio/prerequisite absent); "
                            "logged as an advisory coverage blind spot without invalidating active modalities."
                        ),
                        source=manifest_src,
                    )
                )
            else:
                fatal_gap = True
                applied.append("fatal_coverage_gap")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="coverage_gap",
                        severity="WARNING",
                        finding=f"Detector '{det_id}' reported a prerequisite failure or coverage gap.",
                        source=manifest_src,
                    )
                )
            return ConditionReliabilityAssessment(
                detector_id=det_id,
                authority_tier=authority_tier,
                base_weight=base_weight,
                weight_multiplier=0.0,
                effective_weight=0.0,
                confidence_damping=0.0,
                adjusted_confidence=0.5,
                is_fatal_gap=fatal_gap,
                is_advisory_gap=advisory_gap,
                cannot_solely_certify_synthetic=cannot_sole_synth,
                applied_conditions=applied,
                findings=findings,
            )

        # ── Detector-specific per-condition rules ─────────────────────────────
        already_attenuated = claim.attenuation_factors.composite_attenuation < 0.99

        if det_id in {"rppg", "streaming-rppg"}:
            # 1. Physiological BPM validity check (fixes 067.mp4 zero-BPM trap)
            bpm = (
                claim.observational_metrics.physiological.estimated_bpm
                if (claim.observational_metrics and claim.observational_metrics.physiological)
                else None
            )
            valid_range = cond_rules.get("invalid_or_zero_bpm", {}).get("valid_bpm_range", [40.0, 180.0])
            bpm_low, bpm_high = float(valid_range[0]), float(valid_range[1])

            if bpm is not None and (bpm <= 0.0 or bpm < bpm_low or bpm > bpm_high):
                rule_cfg = cond_rules.get("invalid_or_zero_bpm", {})
                w_mult = float(rule_cfg.get("weight_multiplier", 0.35))
                d_fac = float(rule_cfg.get("confidence_damping", 0.30))
                if adjusted > 0.50:
                    weight_mult *= w_mult
                    cond_damping = min(cond_damping, d_fac)
                    adjusted = _shrink_toward_neutral(adjusted, d_fac)
                    applied.append("rppg_invalid_bpm_synthetic_discount")
                    findings.append(
                        CrossExaminationFinding(
                            detector_id=det_id,
                            check_category="physiological_bpm_invalid",
                            severity="CRITICAL",
                            finding=(
                                f"rPPG asserted synthetic likelihood ({base_conf:.2f}) while reporting "
                                f"invalid estimated_bpm={bpm:.1f} outside physiological [{bpm_low:.0f}, {bpm_high:.0f}] BPM; "
                                "CHROM spectral proxy discounted per manifest reliability rules."
                            ),
                            source=manifest_src,
                        )
                    )
                else:
                    weight_mult *= 0.70
                    applied.append("rppg_out_of_band_bpm_caution")
                    findings.append(
                        CrossExaminationFinding(
                            detector_id=det_id,
                            check_category="physiological_bpm_invalid",
                            severity="WARNING",
                            finding=f"rPPG estimated_bpm={bpm:.1f} lies outside normal resting cardiac range.",
                            source=manifest_src,
                        )
                    )

            # 2. Luminance & duration condition degradation
            if cond.mean_luminance is not None and cond.mean_luminance < 18.0:
                w_mult = float(cond_rules.get("severe_dark_lum_lt_18", {}).get("weight_multiplier", 0.15))
                d_fac = float(cond_rules.get("severe_dark_lum_lt_18", {}).get("confidence_damping", 0.15))
                weight_mult *= w_mult
                if not already_attenuated and adjusted > 0.50:
                    cond_damping = min(cond_damping, d_fac)
                    adjusted = _shrink_toward_neutral(adjusted, d_fac)
                applied.append("rppg_severe_dark_lum_lt_18")
            elif cond.mean_luminance is not None and cond.mean_luminance < 40.0 or "low_light_attenuation" in flags:
                w_mult = float(cond_rules.get("dim_light_18_to_40", {}).get("weight_multiplier", 0.45))
                d_fac = float(cond_rules.get("dim_light_18_to_40", {}).get("confidence_damping", 0.35))
                weight_mult *= w_mult
                if not already_attenuated and adjusted > 0.50:
                    cond_damping = min(cond_damping, d_fac)
                    adjusted = _shrink_toward_neutral(adjusted, d_fac)
                applied.append("rppg_dim_light_attenuation")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="constraint_violation",
                        severity="CRITICAL",
                        finding=(
                            f"Mean luminance ({cond.mean_luminance}) below 40/255 threshold degrades "
                            "CHROM chrominance signal; Score-Inversion false-positive risk."
                        ),
                        source=manifest_src,
                    )
                )

            if cond.duration_seconds is not None and cond.duration_seconds < 2.0:
                weight_mult *= 0.10
                fatal_gap = True
                adjusted = 0.50
                applied.append("rppg_insufficient_duration_lt_2s")
            elif (
                (cond.duration_seconds is not None and cond.duration_seconds < 5.0)
                or "short_clip_attenuation" in flags
                or "marginal_duration" in flags
            ):
                w_mult = float(cond_rules.get("marginal_duration_2s_to_5s", {}).get("weight_multiplier", 0.55))
                weight_mult *= w_mult
                applied.append("rppg_short_duration_2_to_5s")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="constraint_violation",
                        severity="WARNING",
                        finding=(
                            f"Duration ({cond.duration_seconds}s) < 5.0s yields <= 3 cardiac cycles; "
                            "spectral purity weight reduced."
                        ),
                        source=manifest_src,
                    )
                )

            if cond.face_detected is False:
                fatal_gap = True
                weight_mult = 0.0
                adjusted = 0.50
                applied.append("rppg_face_absent")

        elif det_id == "video-classifier":
            if cond.face_detected is False:
                fatal_gap = True
                weight_mult = 0.0
                adjusted = 0.50
                applied.append("vc_face_absent")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="constraint_violation",
                        severity="CRITICAL",
                        finding="No face detected in video; spatial facial manipulation classifier unusable.",
                        source=manifest_src,
                    )
                )
            else:
                if cond.mean_luminance is not None and cond.mean_luminance < 18.0:
                    w_mult = float(cond_rules.get("severe_dark_lum_lt_18", {}).get("weight_multiplier", 0.35))
                    weight_mult *= w_mult
                    applied.append("vc_severe_dark")
                elif cond.mean_luminance is not None and cond.mean_luminance < 40.0:
                    w_mult = float(cond_rules.get("low_light_lum_lt_40", {}).get("weight_multiplier", 0.65))
                    weight_mult *= w_mult
                    applied.append("vc_low_light")
                    findings.append(
                        CrossExaminationFinding(
                            detector_id=det_id,
                            check_category="degraded_operating_condition",
                            severity="WARNING",
                            finding=f"Underexposed frames ({cond.mean_luminance:.1f}/255) reduce spatial residual fidelity.",
                            source=manifest_src,
                        )
                    )

                if cond.duration_seconds is not None and cond.duration_seconds < 2.0:
                    w_mult = float(cond_rules.get("short_clip_lt_2s", {}).get("weight_multiplier", 0.55))
                    weight_mult *= w_mult
                    applied.append("vc_short_clip_lt_2s")

                bitrate_kbps = getattr(cond, "video_bitrate_kbps", None)
                if bitrate_kbps is not None and bitrate_kbps < 500.0:
                    w_mult = float(cond_rules.get("heavy_compression_lt_500kbps", {}).get("weight_multiplier", 0.55))
                    weight_mult *= w_mult
                    applied.append("vc_heavy_compression")
                    findings.append(
                        CrossExaminationFinding(
                            detector_id=det_id,
                            check_category="known_failure_mode",
                            severity="WARNING",
                            finding=(
                                f"Heavy video compression ({bitrate_kbps:.0f} kbps < 500 kbps) "
                                "attenuates high-frequency spatial residuals."
                            ),
                            source=manifest_src,
                        )
                    )

        elif det_id == "syncnet":
            if cond.face_detected is False or (cond.mean_luminance is not None and cond.mean_luminance < 18.0):
                fatal_gap = True
                weight_mult = 0.0
                adjusted = 0.50
                applied.append("syncnet_unusable_visual")
            elif "low_language_confidence" in flags or "foreign_dubbing_risk" in flags:
                weight_mult *= 0.40
                cond_damping = min(cond_damping, 0.50)
                adjusted = _shrink_toward_neutral(adjusted, 0.50)
                applied.append("syncnet_dubbing_language_discount")

        elif det_id == "aasist":
            if cond.duration_seconds is not None and cond.duration_seconds < 1.0:
                fatal_gap = True
                weight_mult = 0.0
                adjusted = 0.50
                applied.append("aasist_audio_lt_1s")
            elif cond.duration_seconds is not None and cond.duration_seconds < 2.0:
                weight_mult *= float(cond_rules.get("short_audio_1s_to_2s", {}).get("weight_multiplier", 0.50))
                applied.append("aasist_short_audio_1s_to_2s")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="constraint_violation",
                        severity="WARNING",
                        finding="Audio duration 1.0–2.0s reduces spectro-temporal graph attention reliability (0.5x weight).",
                        source=manifest_src,
                    )
                )
            if "low_confidence" in flags or "high_noise_floor" in flags:
                weight_mult *= 0.60
                applied.append("aasist_noisy_audio")

        elif det_id in {"detector_image", "image"}:
            has_freq = "frequency_anomaly" in flags
            has_sw_tag = "software_tag_present" in flags
            has_exif_missing = "exif_missing" in flags
            has_low_res = "low_resolution" in flags or "heavy_compression" in flags

            if (has_freq or has_sw_tag) and 0.52 <= adjusted < 0.70:
                # Corroborated physical/frequency/provenance evidence resolves borderline synthetic images
                lift = 0.10 if (has_freq and has_sw_tag) else 0.08
                adjusted = _clamp01(adjusted + lift)
                weight_mult *= 1.15
                applied.append("image_forensic_signal_corroboration")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="multi_signal_corroboration",
                        severity="INFO",
                        finding=(
                            "Borderline ViT image score corroborated by secondary forensic artifact "
                            f"flags ({', '.join(sorted(flags & {'frequency_anomaly', 'software_tag_present'}))})."
                        ),
                        source=manifest_src,
                    )
                )
            elif has_exif_missing and not has_freq and not has_sw_tag and 0.32 <= adjusted <= 0.55:
                # Stripped EXIF alone is standard on re-encoded authentic social media images; prevent upward drift.
                weight_mult *= 0.90
                applied.append("image_exif_missing_non_dispositive")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="known_failure_mode",
                        severity="INFO",
                        finding="Missing EXIF metadata on web/re-encoded image is non-dispositive without visual/FFT artifacts.",
                        source=manifest_src,
                    )
                )
            if has_low_res:
                weight_mult *= 0.75
                applied.append("image_low_res_or_compressed")

        elif det_id == "detector_text":
            is_short_attenuated = "short_text_attenuated" in flags
            if is_short_attenuated:
                w_mult = float(cond_rules.get("marginal_40_to_149_words", {}).get("weight_multiplier", 0.65))
                weight_mult *= w_mult
                applied.append("text_marginal_length_40_to_149w")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="constraint_violation",
                        severity="WARNING",
                        finding=(
                            "Marginal word count (40–149 words) lowers baseline Desklib AUROC (0.883 vs 0.986); "
                            "reliability weight reduced per manifest."
                        ),
                        source=manifest_src,
                    )
                )

            bino_agree = "binoculars_corroborated" in flags
            bino_div = "binoculars_divergence" in flags
            ppl_low = "low_perplexity" in flags
            burst_low = "low_burstiness" in flags
            ppl_high = "high_perplexity" in flags
            burst_nat = "natural_burstiness" in flags
            style_synth = "stylometry_synthetic" in flags
            style_div = "stylometry_classifier_divergence" in flags
            chunk_div = "chunk_disagreement" in flags

            if (bino_agree or (ppl_low and burst_low) or ((ppl_low or burst_low) and style_synth)) and 0.52 <= adjusted < 0.68:
                lift = 0.08 if (bino_agree or (ppl_low and burst_low)) else 0.05
                adjusted = _clamp01(adjusted + lift)
                weight_mult *= 1.15
                applied.append("text_multi_signal_ai_corroboration")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="multi_signal_corroboration",
                        severity="INFO",
                        finding=(
                            "Moderate neural AI score corroborated by secondary perplexity/burstiness/Binoculars signals."
                        ),
                        source=manifest_src,
                    )
                )
            elif (ppl_high and burst_nat) and 0.34 <= adjusted <= 0.48 and not style_synth and not bino_div:
                adjusted = _clamp01(adjusted - 0.06)
                applied.append("text_multi_signal_human_corroboration")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="multi_signal_corroboration",
                        severity="INFO",
                        finding="High perplexity and natural sentence burstiness corroborate human authorship.",
                        source=manifest_src,
                    )
                )

            if chunk_div or style_div or bino_div:
                applied.append("text_internal_signal_divergence")
                # Moderate synthetic score contradicted by both heterogeneous chunks and natural human burstiness
                if chunk_div and (burst_nat or ppl_high) and 0.55 <= adjusted < 0.82:
                    cond_damping = min(cond_damping, 0.55)
                    adjusted = _shrink_toward_neutral(adjusted, 0.55)
                    weight_mult *= 0.80
                    applied.append("text_chunk_disagreement_damping")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="internal_signal_divergence",
                        severity="WARNING",
                        finding=(
                            "Internal text signals diverged across document chunks, perplexity/Binoculars, or stylometry "
                            "(possible hybrid human-AI editing or paraphrasing)."
                        ),
                        source=manifest_src,
                    )
                )

            if "adversarial_unicode_stripped" in flags:
                applied.append("text_adversarial_unicode")
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det_id,
                        check_category="adversarial_sanitization",
                        severity="WARNING",
                        finding="Hidden/bidi control characters were stripped prior to scoring.",
                        source=manifest_src,
                    )
                )

        if not applied:
            applied.append("nominal_conditions")

        eff_weight = 0.0 if fatal_gap else round(base_weight * weight_mult, 4)
        return ConditionReliabilityAssessment(
            detector_id=det_id,
            authority_tier=authority_tier,
            base_weight=base_weight,
            weight_multiplier=round(weight_mult, 4),
            effective_weight=eff_weight,
            confidence_damping=round(cond_damping, 4),
            adjusted_confidence=round(adjusted, 4),
            is_fatal_gap=fatal_gap,
            is_advisory_gap=advisory_gap,
            cannot_solely_certify_synthetic=cannot_sole_synth,
            applied_conditions=applied,
            findings=findings,
        )
