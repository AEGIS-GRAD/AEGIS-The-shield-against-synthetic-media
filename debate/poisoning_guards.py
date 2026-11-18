"""
AEGIS Poisoning Guards for the Judge — Week 11 Cybersecurity Task 2
===================================================================

Cheap, deterministic mitigations against poisoned or miscalibrated detector
outputs, found by the red-team harness ``security/redteam/poisoning_redteam.py``
(log: ``security/docs/poisoning_redteam_log.md``).

Pre-arbitration claim hygiene (``harden_claims``):
  PG1 one claim per detector (Sybil / ballot stuffing)
  PG2 domain binding: a detector may only speak in its registered evidence domain
  PG3 polarity/confidence consistency: contradictory claims become INCONCLUSIVE
  PG4 calibration cap: confidences clipped to [0.03, 0.97] (no detector is that sure)
  PG5 self-reported attenuation is honoured only when the measured operating
      conditions corroborate it (luminance, duration, bitrate)
  PG6 self-serving flags (low_light, short_clip, silent_video...) are honoured only
      when the measured operating conditions corroborate them
  PG7 operating conditions that contradict confident detector evidence (e.g. "no
      face" while face detectors report confidently) are treated as untrusted

Post-arbitration verdict guards (``apply_verdict_guards``):
  QG1 dissent veto: AUTHENTIC is not certified while any active, un-discounted
      detector credibly reports SYNTHETIC (asymmetric: hiding a deepfake is the
      costlier error, matching the anti-default mandate)
  QG2 primary-witness rule: a video cannot be certified AUTHENTIC without an
      active spatial (face-manipulation) witness supporting it
  QG3 outlier report: claims far from the robust consensus are listed for review

Framing attacks (one compromised *primary* detector pushing SYNTHETIC) are not
blocked here: at the claim level they are indistinguishable from a genuine face
swap or voice clone, which the precedence matrix deliberately lets one primary
detector certify. See the red-team log for the proposed redundancy control.

Disable with ``AEGIS_POISONING_GUARDS=0`` (e.g. to reproduce Week 10 behaviour).
"""

from __future__ import annotations

import os
import statistics
from typing import List, Optional, Tuple

from .disagreement import is_coverage_gap
from .schemas import (
    AttenuationFactors,
    ClaimPolarity,
    EvidenceDomain,
    ForensicClaim,
    JudgeVerdictClass,
    OperatingConditions,
)

PREFIX = "POISONING GUARD"

REGISTERED_DOMAINS = {
    "video-classifier": EvidenceDomain.SPATIAL_PIXEL,
    "rppg": EvidenceDomain.PHYSIOLOGICAL_BVP,
    "streaming-rppg": EvidenceDomain.PHYSIOLOGICAL_BVP,
    "syncnet": EvidenceDomain.AUDIOVISUAL_SYNC,
    "aasist": EvidenceDomain.AUDIO_ACOUSTIC,
    "detector_image": EvidenceDomain.IMAGE_FORENSIC,
    "image-mirror": EvidenceDomain.IMAGE_FORENSIC,
    "image-frequency": EvidenceDomain.IMAGE_FORENSIC,
    "detector_text": EvidenceDomain.TEXT_FORENSIC,
    "text-desklib": EvidenceDomain.TEXT_FORENSIC,
    "text-stylometry": EvidenceDomain.TEXT_FORENSIC,
    "text-perplexity": EvidenceDomain.TEXT_FORENSIC,
}
FACE_DEPENDENT = {"video-classifier", "rppg", "streaming-rppg"}
AUDIO_DEPENDENT = {"aasist", "syncnet"}
VIDEO_DOMAINS = {EvidenceDomain.SPATIAL_PIXEL, EvidenceDomain.PHYSIOLOGICAL_BVP, EvidenceDomain.AUDIOVISUAL_SYNC}

CONF_FLOOR, CONF_CEIL = 0.03, 0.97
CREDIBLE_MARGIN = 0.15        # |p - 0.5| at which a claim counts as taking a side
LOW_LIGHT_LUMINANCE = 60.0    # arbitrator's low-light rule fires below 40; allow margin
SHORT_CLIP_S = 3.0            # arbitrator's short-clip rule fires below 2 s
LOW_BITRATE_KBPS = 800.0


def guards_enabled() -> bool:
    return os.environ.get("AEGIS_POISONING_GUARDS", "1") != "0"


def spatial_witness_required() -> bool:
    """QG2 changes what the judge may certify for video (no AUTHENTIC without the spatial
    detector), so it is opt-in until the AI team signs off (alignment study B)."""
    return os.environ.get("AEGIS_REQUIRE_SPATIAL_WITNESS", "0") == "1"


def _explicit(cond: Optional[OperatingConditions], name: str) -> bool:
    return cond is not None and name in cond.model_fields_set and getattr(cond, name) is not None


def _side(c: ForensicClaim) -> Optional[str]:
    if is_coverage_gap(c) or c.polarity not in (ClaimPolarity.AUTHENTIC, ClaimPolarity.SYNTHETIC):
        return None
    if c.confidence >= 0.5 + CREDIBLE_MARGIN:
        return "SYNTHETIC"
    if c.confidence <= 0.5 - CREDIBLE_MARGIN:
        return "AUTHENTIC"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Pre-arbitration
# ─────────────────────────────────────────────────────────────────────────────
def harden_claims(
    claims: List[ForensicClaim], conditions: Optional[OperatingConditions]
) -> Tuple[List[ForensicClaim], Optional[OperatingConditions], List[str]]:
    notes: List[str] = []
    out: List[ForensicClaim] = []
    seen = set()

    for c in claims:
        if c.detector_id in seen:  # PG1
            notes.append(f"{PREFIX} PG1: dropped duplicate claim from '{c.detector_id}' (one vote per detector).")
            continue
        seen.add(c.detector_id)
        upd = {}

        reg = REGISTERED_DOMAINS.get(c.detector_id)  # PG2
        if reg is not None and c.domain != reg:
            notes.append(f"{PREFIX} PG2: '{c.detector_id}' claimed domain '{c.domain.value}', rebound to '{reg.value}'.")
            upd["domain"] = reg

        conf = c.confidence  # PG3
        if (c.polarity == ClaimPolarity.SYNTHETIC and conf < 0.45) or (c.polarity == ClaimPolarity.AUTHENTIC and conf > 0.55):
            notes.append(f"{PREFIX} PG3: '{c.detector_id}' polarity {c.polarity.value} contradicts P(synthetic)={conf:.2f}; treated as INCONCLUSIVE.")
            upd["polarity"] = ClaimPolarity.INCONCLUSIVE

        clipped = min(CONF_CEIL, max(CONF_FLOOR, conf))  # PG4
        if clipped != conf:
            notes.append(f"{PREFIX} PG4: '{c.detector_id}' confidence {conf:.3f} capped to {clipped:.2f}.")
            upd["confidence"] = clipped

        att = c.attenuation_factors  # PG5
        lum_ok = _explicit(conditions, "mean_luminance") and conditions.mean_luminance >= LOW_LIGHT_LUMINANCE
        dur_ok = _explicit(conditions, "duration_seconds") and conditions.duration_seconds >= SHORT_CLIP_S
        br_ok = _explicit(conditions, "video_bitrate_kbps") and conditions.video_bitrate_kbps >= LOW_BITRATE_KBPS
        new_att = AttenuationFactors(
            luminance_factor=1.0 if lum_ok else att.luminance_factor,
            duration_factor=1.0 if dur_ok else att.duration_factor,
            compression_factor=1.0 if br_ok else att.compression_factor,
            occlusion_factor=max(0.5, att.occlusion_factor),
        )
        if new_att != att:
            notes.append(f"{PREFIX} PG5: '{c.detector_id}' self-reported attenuation not corroborated by measured conditions; reset.")
            upd["attenuation_factors"] = new_att

        flags = list(c.flags)  # PG6
        drop = set()
        if lum_ok:
            drop |= {"low_light_attenuation", "insufficient_lighting"}
        if dur_ok:
            drop |= {"short_clip_attenuation"}
        if _explicit(conditions, "audio_present") and conditions.audio_present:
            drop |= {"silent_video"}
        stripped = [f for f in flags if f in drop]
        if stripped:
            notes.append(f"{PREFIX} PG6: '{c.detector_id}' flags {stripped} contradicted by measured conditions; ignored.")
            upd["flags"] = [f for f in flags if f not in drop]

        out.append(c.model_copy(update=upd) if upd else c)

    # PG7: conditions that contradict confident detector evidence are untrusted.
    if conditions is not None:
        contradictions = []
        if _explicit(conditions, "face_detected") and conditions.face_detected is False:
            contradictions += [c.detector_id for c in out if c.detector_id in FACE_DEPENDENT and _side(c)]
        if _explicit(conditions, "audio_present") and conditions.audio_present is False:
            contradictions += [c.detector_id for c in out if c.detector_id in AUDIO_DEPENDENT and _side(c)]
        if contradictions:
            notes.append(f"{PREFIX} PG7: operating conditions contradict confident evidence from {sorted(set(contradictions))}; "
                         "conditions treated as untrusted and ignored.")
            conditions = None
    return out, conditions, notes


# ─────────────────────────────────────────────────────────────────────────────
# Post-arbitration
# ─────────────────────────────────────────────────────────────────────────────
def apply_verdict_guards(verdict, claims: List[ForensicClaim]) -> Tuple[object, List[str], List[str]]:
    """Returns (verdict, downgrade_notes, informational_notes)."""
    notes: List[str] = []
    info: List[str] = []
    discounted = {a.detector_id for a in verdict.adjudications if getattr(a, "discount_reason", None)}
    active = [c for c in claims if not is_coverage_gap(c)]

    if verdict.final_verdict == JudgeVerdictClass.AUTHENTIC:
        dissent = [c for c in active if _side(c) == "SYNTHETIC" and c.detector_id not in discounted]
        if dissent:  # QG1
            _downgrade(verdict, f"{PREFIX} QG1 (dissent veto): {[c.detector_id for c in dissent]} credibly report SYNTHETIC "
                                "and no precedence rule explains it; AUTHENTIC cannot be certified.", notes)
        elif spatial_witness_required() and any(c.domain in VIDEO_DOMAINS for c in claims):  # QG2
            spatial = [c for c in active if c.domain == EvidenceDomain.SPATIAL_PIXEL and _side(c) == "AUTHENTIC"]
            if not spatial:
                _downgrade(verdict, f"{PREFIX} QG2 (primary witness): video certified AUTHENTIC without an active spatial "
                                    "face-manipulation witness; face swaps preserve pulse, voice and lip sync.", notes)

    sides = [c.confidence for c in active if c.polarity in (ClaimPolarity.AUTHENTIC, ClaimPolarity.SYNTHETIC)]
    if len(sides) >= 3:  # QG3
        med = statistics.median(sides)
        outliers = [c.detector_id for c in active if abs(c.confidence - med) > 0.45]
        if outliers:
            info.append(f"{PREFIX} QG3 (outlier report): {outliers} deviate > 0.45 from the consensus median {med:.2f}; "
                        "flagged for detector-integrity review.")
    return verdict, notes, info


def _downgrade(verdict, note: str, notes: List[str]) -> None:
    verdict.final_verdict = JudgeVerdictClass.UNCERTAIN
    verdict.calibrated_score = round(min(max(verdict.calibrated_score, 0.36), 0.64), 4)
    verdict.siem_alert_tier = "P2_ELEVATED"
    verdict.forensic_justification += f"\n\n[POISONING GUARD]: {note}"
    notes.append(note)
