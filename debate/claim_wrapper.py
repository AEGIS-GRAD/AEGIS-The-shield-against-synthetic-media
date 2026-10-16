"""
AEGIS Debate Layer — Claim-and-Evidence Wrapper (video detectors).
===================================================================

Turns the raw JSON a video detector returns from `/detect` into a
`debate.schemas.ForensicClaim`: a polarity (AUTHENTIC / SYNTHETIC /
INCONCLUSIVE / NOT_APPLICABLE), a calibrated P(synthetic), structured
metrics, and — the point of this module — a human-readable claim sentence
instead of a bare number.

Covers the three video detectors only:
    video-classifier -> EvidenceDomain.SPATIAL_PIXEL
    rppg             -> EvidenceDomain.PHYSIOLOGICAL_BVP
    syncnet          -> EvidenceDomain.AUDIOVISUAL_SYNC

Contract decisions (each one is deliberate — see the notes below)
------------------------------------------------------------------
1. ForensicClaim.confidence ALWAYS means P(synthetic): 0.0 = authentic,
   1.0 = synthetic. This is what detector_response.schema.json says, and it is
   what debate/disagreement.py and debate/arbitrator.py assume.

2. rPPG is the odd one out. Its /detect response has BOTH `score`
   (= P(synthetic)) and `confidence` (= |score - 0.5| * 2 * input_quality,
   i.e. "how sure", NOT "how fake"). Passing rPPG's `confidence` through as-is
   would turn an authentic video with a strong pulse (score 0.05 -> confidence
   0.90) into a 0.90 "synthetic" claim. So for rPPG this module reads `score`.
   It also means rPPG's own attenuation (input_quality) is applied exactly
   once: `score` is un-attenuated, and the attenuation travels in
   `attenuation_factors`, which ForensicClaim.effective_confidence applies.

3. Polarity uses the same thresholds as debate/disagreement.py (imported, not
   copied, so they cannot drift): P >= 0.65 SYNTHETIC, P <= 0.35 AUTHENTIC,
   anything in between INCONCLUSIVE.
   Known consequence: disagreement.is_coverage_gap() treats every INCONCLUSIVE
   claim as a coverage gap, so a *borderline but real* score is dropped from
   the vote and reported as a gap. That is a debate-layer decision; this
   wrapper just labels the polarity honestly.

4. A detector that could not judge says so itself (SyncNet: flag
   `not_applicable`; rPPG: verdict `inconclusive`). In those cases the
   detector's own sentence already explains why, so it is kept verbatim.

5. `flags` are passed through unchanged. disagreement.py / arbitrator.py match
   on exact flag names (`low_light_attenuation`, `short_clip_attenuation`,
   `not_applicable`, `lip_sync_verified`, ...), so inventing new ones here
   would silently break those rules.

6. `evidence_hash` is the SHA-256 of the raw detector response, so every claim
   can be traced back to the exact output that produced it.

Usage
-----
    from debate.claim_wrapper import wrap_detector_response, wrap_video_detector_outputs

    claim  = wrap_detector_response("rppg", raw_rppg_response)
    claims = wrap_video_detector_outputs({
        "video-classifier": raw_vc, "rppg": raw_rppg, "syncnet": raw_sync,
    })
    verdict = JudgeArbitrator().arbitrate(claims)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from debate.disagreement import (
    AUTHENTIC_POLARITY_THRESHOLD,
    SYNTHETIC_POLARITY_THRESHOLD,
)
from debate.schemas import (
    AttenuationFactors,
    AudioVisualMetrics,
    ClaimPolarity,
    EvidenceDomain,
    ForensicClaim,
    ObservationalMetrics,
    OperatingConditions,
    PhysiologicalMetrics,
    SpatialMetrics,
)

logger = logging.getLogger(__name__)

NOT_APPLICABLE_FLAG = "not_applicable"

# detectors/video_classifier/main.py samples 10 frames (sample_n=10).
VIDEO_CLASSIFIER_SAMPLED_FRAMES = 10
# detectors/syncnet/infer.py converts frames to ms as abs_offset * 40 (25 fps).
SYNCNET_MS_PER_FRAME = 40.0

DOMAIN_BY_DETECTOR: Dict[str, EvidenceDomain] = {
    "video-classifier": EvidenceDomain.SPATIAL_PIXEL,
    "rppg": EvidenceDomain.PHYSIOLOGICAL_BVP,
    "syncnet": EvidenceDomain.AUDIOVISUAL_SYNC,
}

# Order used by wrap_video_detector_outputs (matches the arbitrator's precedence rules).
VIDEO_DETECTOR_ORDER = ("video-classifier", "rppg", "syncnet")


# ── Internal result of a per-detector adapter ───────────────────────────────
@dataclass
class _Adapted:
    p_synthetic: float
    polarity: ClaimPolarity
    claim: str
    coverage_gap: bool = False
    metrics: Optional[ObservationalMetrics] = None
    attenuation: AttenuationFactors = field(default_factory=AttenuationFactors)


# ── Shared helpers ───────────────────────────────────────────────────────────
def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _polarity_from_p(p: float) -> ClaimPolarity:
    if p >= SYNTHETIC_POLARITY_THRESHOLD:
        return ClaimPolarity.SYNTHETIC
    if p <= AUTHENTIC_POLARITY_THRESHOLD:
        return ClaimPolarity.AUTHENTIC
    return ClaimPolarity.INCONCLUSIVE


def _strength(p: float) -> str:
    """strong / moderate / weak, by distance from the neutral 0.5."""
    d = abs(p - 0.5) * 2.0
    if d >= 0.7:
        return "strong"
    if d >= 0.4:
        return "moderate"
    return "weak"


_ADVERB = {"strong": "strongly", "moderate": "moderately", "weak": "weakly"}


def _frames(n: int) -> str:
    """'0 frames', '1 frame', '5 frames' (sign dropped: it lives in the metrics)."""
    n = abs(int(n))
    return f"{n} frame" if n == 1 else f"{n} frames"


def _evidence_hash(response: Dict[str, Any]) -> str:
    raw = json.dumps(response, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ── video-classifier ─────────────────────────────────────────────────────────
def _adapt_video_classifier(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    p = _clamp01(r["confidence"])  # already P(synthetic)
    polarity = _polarity_from_p(p)
    pct = f"{p:.0%}"

    if polarity == ClaimPolarity.SYNTHETIC:
        claim = (
            f"Frame-level analysis found {_strength(p)} spatial evidence of face manipulation "
            f"(estimated {pct} probability of synthetic content across the sampled frames)."
        )
    elif polarity == ClaimPolarity.AUTHENTIC:
        claim = (
            "Frame-level analysis found no significant manipulation artifacts across the sampled frames "
            f"(estimated {pct} probability of synthetic content)."
        )
    else:
        claim = (
            f"Frame-level analysis was borderline ({pct} probability of synthetic content): "
            "the spatial evidence neither confirms nor rules out manipulation."
        )

    return _Adapted(
        p_synthetic=p,
        polarity=polarity,
        claim=claim,
        metrics=ObservationalMetrics(
            spatial=SpatialMetrics(sampled_frames=VIDEO_CLASSIFIER_SAMPLED_FRAMES)
        ),
    )


# ── rPPG ─────────────────────────────────────────────────────────────────────
def _bpm_text(bpm: Optional[float], reliable: bool = True) -> str:
    """A stable pulse yields a measured rate; without one the rate is only a best guess."""
    if not bpm:
        return ""
    return f", estimated {bpm:.0f} BPM" if reliable else f", best-guess rate {bpm:.0f} BPM"


def _adapt_rppg(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    detector_claim = (r.get("evidence") or {}).get("claim", "")
    verdict = r.get("verdict")

    # See contract note 2: P(synthetic) lives in `score`, not `confidence`.
    if r.get("score") is not None:
        p = _clamp01(r["score"])
    else:
        logger.warning(
            "rPPG response has no `score`; assuming legacy contract where `confidence` is P(synthetic)."
        )
        p = _clamp01(r["confidence"])

    input_quality = r.get("input_quality")
    iq = 1.0 if input_quality is None else _clamp01(input_quality)
    bpm = r.get("estimated_bpm")
    bpm = bpm if bpm and bpm > 0 else None

    # Attenuation: rPPG exposes one composite number (min of luminance and
    # duration factors) and flags saying which one(s) applied. Because the
    # composite is a min(), assigning it to each flagged factor reproduces it.
    lum = iq if "low_light_attenuation" in flags else 1.0
    dur = iq if "short_clip_attenuation" in flags else 1.0
    attenuation = AttenuationFactors(luminance_factor=lum, duration_factor=dur)

    # ── Detector could not judge ──
    if verdict == "inconclusive":
        guardrail = iq == 0.0  # preprocess guardrail: its own claim already says why
        if guardrail:
            claim = detector_claim or "Heartbeat analysis was skipped: the clip failed an input guardrail."
            metrics = None
        else:
            reasons = []
            if "low_light_attenuation" in flags:
                reasons.append("poor lighting")
            if "short_clip_attenuation" in flags:
                reasons.append("a short clip")
            why = f" ({' and '.join(reasons)})" if reasons else ""
            claim = (
                f"Heartbeat analysis is unreliable for this clip: input quality is only {iq:.0%}{why}, "
                "so no verdict on physiological consistency can be given."
            )
            metrics = ObservationalMetrics(
                physiological=PhysiologicalMetrics(estimated_bpm=bpm, spectral_purity=round(1.0 - p, 4))
            )
        return _Adapted(
            p_synthetic=0.5,
            polarity=ClaimPolarity.INCONCLUSIVE,
            claim=claim,
            coverage_gap=True,
            metrics=metrics,
            attenuation=attenuation,
        )

    # ── Detector produced a score ──
    polarity = _polarity_from_p(p)
    quality = 1.0 - p  # rPPG defines score = 1 - signal_quality
    q_pct = f"{quality:.0%}"

    if polarity == ClaimPolarity.SYNTHETIC:
        claim = (
            "No stable heartbeat signal consistent with a live face was found in the facial skin region "
            f"(signal quality {q_pct}{_bpm_text(bpm, reliable=False)}), {_ADVERB[_strength(p)]} suggesting synthetic generation."
        )
    elif polarity == ClaimPolarity.AUTHENTIC:
        claim = (
            "A stable, periodic pulse consistent with a live face was detected "
            f"(signal quality {q_pct}{_bpm_text(bpm)})."
        )
    else:
        claim = (
            f"The heartbeat signal is ambiguous (signal quality {q_pct}{_bpm_text(bpm, reliable=False)}): "
            "it neither clearly confirms nor rules out a live face."
        )

    if "atypical_heart_rate" in flags and bpm:
        claim += f" The estimated rate of {bpm:.0f} BPM is outside the typical human range."
    if "low_light_attenuation" in flags:
        claim += " Reliability reduced: the footage is poorly lit."
    if "short_clip_attenuation" in flags:
        claim += " Reliability reduced: the clip is short."

    return _Adapted(
        p_synthetic=p,
        polarity=polarity,
        claim=claim,
        metrics=ObservationalMetrics(
            physiological=PhysiologicalMetrics(estimated_bpm=bpm, spectral_purity=round(quality, 4))
        ),
        attenuation=attenuation,
    )


# ── SyncNet ──────────────────────────────────────────────────────────────────
def _adapt_syncnet(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    detector_claim = (r.get("evidence") or {}).get("claim", "")

    # SyncNet signals "could not judge" through the not_applicable flag (see infer.py).
    if NOT_APPLICABLE_FLAG in flags:
        return _Adapted(
            p_synthetic=0.5,
            polarity=ClaimPolarity.NOT_APPLICABLE,
            claim=detector_claim or "Lip-sync analysis was not applicable to this input.",
            coverage_gap=True,
        )

    p = _clamp01(r["confidence"])  # already P(synthetic)
    polarity = _polarity_from_p(p)

    raw = r.get("raw_score")
    offset = int(round(float(raw))) if raw is not None else 0  # raw_score = optimal offset in frames
    abs_off = abs(offset)
    ms = abs_off * SYNCNET_MS_PER_FRAME

    if "audio_visual_mismatch" in flags:
        direction = "leads" if offset > 0 else "lags"  # same convention as infer.py
        claim = (
            f"Severe lip-sync mismatch: the audio {direction} the video by {_frames(abs_off)} "
            f"(~{ms:.0f} ms), consistent with dubbed audio or synthetic generation."
        )
    elif "sync_offset_detected" in flags:
        claim = (
            f"A mild lip-audio offset of {_frames(abs_off)} (~{ms:.0f} ms) was detected, "
            "slightly above the natural range of speech variation."
        )
    elif "lip_sync_verified" in flags:
        claim = f"Lip movements are tightly synchronized with the audio (offset {_frames(abs_off)})."
    elif "in_sync" in flags:
        claim = (
            f"Lip-sync is within the natural range of speech variation "
            f"(offset {_frames(abs_off)}, ~{ms:.0f} ms)."
        )
    else:
        claim = (
            f"Lip-sync analysis returned a {p:.0%} probability of synthetic content "
            f"(audio-video offset {_frames(abs_off)})."
        )

    return _Adapted(
        p_synthetic=p,
        polarity=polarity,
        claim=claim,
        metrics=ObservationalMetrics(
            audiovisual=AudioVisualMetrics(
                optimal_offset_frames=offset,
                offset_ms=float(offset) * SYNCNET_MS_PER_FRAME,
            )
        ),
    )


_ADAPTERS: Dict[str, Callable[[Dict[str, Any], List[str]], _Adapted]] = {
    "video-classifier": _adapt_video_classifier,
    "rppg": _adapt_rppg,
    "syncnet": _adapt_syncnet,
}


# ── Public API ───────────────────────────────────────────────────────────────
def wrap_detector_response(
    detector_id: str,
    response: Dict[str, Any],
    conditions: Optional[OperatingConditions] = None,
) -> ForensicClaim:
    """Wraps ONE video detector's raw /detect response into a ForensicClaim."""
    adapter = _ADAPTERS.get(detector_id)
    if adapter is None:
        raise ValueError(
            f"Unknown video detector '{detector_id}'. Expected one of {sorted(_ADAPTERS)}."
        )

    evidence = response.get("evidence") or {}
    flags = list(evidence.get("flags") or [])
    adapted = adapter(response, flags)
    job_id = response.get("job_id") or "unknown"

    return ForensicClaim(
        claim_id=f"clm-{detector_id}-{job_id}",
        job_id=job_id,
        detector_id=detector_id,
        model_version=response.get("model_version") or "unknown",
        domain=DOMAIN_BY_DETECTOR[detector_id],
        polarity=adapted.polarity,
        confidence=round(adapted.p_synthetic, 4),
        raw_score=response.get("raw_score"),
        claim=adapted.claim,
        flags=flags,
        observational_metrics=adapted.metrics,
        attenuation_factors=adapted.attenuation,
        operating_conditions=conditions,
        coverage_gap=adapted.coverage_gap,
        evidence_hash=_evidence_hash(response),
    )


def wrap_video_detector_outputs(
    responses: Dict[str, Optional[Dict[str, Any]]],
    conditions: Optional[OperatingConditions] = None,
) -> List[ForensicClaim]:
    """Wraps whatever the orchestrator collected, e.g.
    {"video-classifier": {...}, "rppg": {...}, "syncnet": None}.

    A detector that returned nothing (None / missing) is skipped — no claim is
    invented for it. Unknown detector ids raise ValueError.
    """
    unknown = set(responses) - set(_ADAPTERS)
    if unknown:
        raise ValueError(f"Unknown video detector(s): {sorted(unknown)}")

    return [
        wrap_detector_response(det_id, responses[det_id], conditions)
        for det_id in VIDEO_DETECTOR_ORDER
        if responses.get(det_id) is not None
    ]
