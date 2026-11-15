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
from debate.prompt_security import (
    MAX_FORENSIC_CLAIM_LEN,
    MAX_RAW_DETECTOR_CLAIM_LEN,
    sanitize_claim_text,
    sanitize_flags,
    sanitize_untrusted_text,
)
from debate.schemas import (
    AttenuationFactors,
    AudioMetrics,
    AudioVisualMetrics,
    ClaimPolarity,
    EvidenceDomain,
    ForensicClaim,
    ImageForensicMetrics,
    ObservationalMetrics,
    OperatingConditions,
    PhysiologicalMetrics,
    SpatialMetrics,
    TextForensicMetrics,
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
    "aasist": EvidenceDomain.AUDIO_ACOUSTIC,
    "detector_image": EvidenceDomain.IMAGE_FORENSIC,
    "image-mirror": EvidenceDomain.IMAGE_FORENSIC,
    "image-frequency": EvidenceDomain.IMAGE_FORENSIC,
    "image-exif": EvidenceDomain.METADATA_INTEGRITY,
    "detector_text": EvidenceDomain.TEXT_FORENSIC,
    "text-desklib": EvidenceDomain.TEXT_FORENSIC,
    "text-stylometry": EvidenceDomain.TEXT_FORENSIC,
    "text-perplexity": EvidenceDomain.TEXT_FORENSIC,
}

# Order used by wrap_video_detector_outputs (matches the arbitrator's precedence rules).
VIDEO_DETECTOR_ORDER = ("video-classifier", "rppg", "syncnet", "aasist")
DETECTOR_ORDER = VIDEO_DETECTOR_ORDER + ("detector_image", "detector_text")


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
    raw_detector_claim = (r.get("evidence") or {}).get("claim", "")
    detector_claim = sanitize_claim_text(
        raw_detector_claim, max_len=MAX_RAW_DETECTOR_CLAIM_LEN, source="rppg_claim"
    ).sanitized
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
    raw_bpm = r.get("estimated_bpm")
    estimated_bpm_val = float(raw_bpm) if raw_bpm is not None else None
    bpm = estimated_bpm_val if (estimated_bpm_val is not None and estimated_bpm_val > 0) else None

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
                physiological=PhysiologicalMetrics(estimated_bpm=estimated_bpm_val, spectral_purity=round(1.0 - p, 4))
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
            physiological=PhysiologicalMetrics(estimated_bpm=estimated_bpm_val, spectral_purity=round(quality, 4))
        ),
        attenuation=attenuation,
    )


# ── SyncNet ──────────────────────────────────────────────────────────────────
def _adapt_syncnet(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    raw_detector_claim = (r.get("evidence") or {}).get("claim", "")
    detector_claim = sanitize_claim_text(
        raw_detector_claim, max_len=MAX_RAW_DETECTOR_CLAIM_LEN, source="syncnet_claim"
    ).sanitized

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


# ── AASIST ───────────────────────────────────────────────────────────────────
def _adapt_aasist(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    raw_detector_claim = (r.get("evidence") or {}).get("claim", "")
    detector_claim = sanitize_claim_text(
        raw_detector_claim, max_len=MAX_RAW_DETECTOR_CLAIM_LEN, source="aasist_claim"
    ).sanitized

    # Check for coverage gaps: silent video, non-speech, or not_applicable flag
    if (
        NOT_APPLICABLE_FLAG in flags
        or "silent_video" in flags
        or "insufficient_signal" in flags
        or "no_speech" in flags
    ):
        return _Adapted(
            p_synthetic=0.5,
            polarity=ClaimPolarity.NOT_APPLICABLE,
            claim=detector_claim or "Acoustic spoofing analysis was not applicable to this input.",
            coverage_gap=True,
        )

    p = _clamp01(r["confidence"])  # P(synthetic)
    polarity = _polarity_from_p(p)
    pct = f"{p:.0%}"

    spectral_anomaly = (
        "graph_spectral_anomaly" in flags
        or "voice_cloning_suspected" in flags
        or "high_spoof_confidence" in flags
    )

    if polarity == ClaimPolarity.SYNTHETIC:
        claim = (
            f"Acoustic spectral-temporal analysis found {_strength(p)} evidence of synthetic voice / audio cloning "
            f"(estimated {pct} probability of synthetic content)."
        )
        if "voice_cloning_suspected" in flags or "high_spoof_confidence" in flags:
            claim += " Graph spectral attention irregularities indicate cloned or synthesized speech."
    elif polarity == ClaimPolarity.AUTHENTIC:
        claim = (
            f"Acoustic analysis found spectral patterns consistent with authentic human vocal tract dynamics "
            f"(estimated {pct} probability of synthetic content)."
        )
    else:
        claim = (
            f"Acoustic analysis was borderline ({pct} probability of synthetic content): "
            "spectral features neither confirm nor rule out voice cloning."
        )

    return _Adapted(
        p_synthetic=p,
        polarity=polarity,
        claim=claim,
        metrics=ObservationalMetrics(
            audio=AudioMetrics(
                spoof_score=p,
                spectral_anomaly_detected=spectral_anomaly,
                speech_detected=True,
            )
        ),
    )


# ── detector_image ───────────────────────────────────────────────────────────
def _adapt_detector_image(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    """
    Adapts the MIRROR / CommFor image-detector response into a ForensicClaim.
    Domain: SPATIAL_PIXEL — spatial neural representations, FFT grid, and EXIF checks.
    """
    raw_detector_claim = (r.get("evidence") or {}).get("claim", "")
    detector_claim = sanitize_claim_text(
        raw_detector_claim, max_len=MAX_RAW_DETECTOR_CLAIM_LEN, source="image_claim"
    ).sanitized

    if NOT_APPLICABLE_FLAG in flags or r.get("status") == "not_applicable":
        return _Adapted(
            p_synthetic=0.5,
            polarity=ClaimPolarity.NOT_APPLICABLE,
            claim=detector_claim or "Image analysis was not applicable to this input.",
            coverage_gap=True,
        )

    p = _clamp01(r["confidence"])  # P(synthetic) as declared by the detector
    polarity = _polarity_from_p(p)
    pct = f"{p:.0%}"

    has_freq = "frequency_anomaly" in flags
    has_exif = "exif_missing" in flags

    if has_freq and has_exif:
        evidence_summary = "frequency-domain grid artifacts present, no camera metadata"
    elif has_freq and not has_exif:
        evidence_summary = "frequency-domain grid artifacts present, camera metadata intact"
    elif has_exif and not has_freq:
        evidence_summary = "no camera metadata, no high-frequency grid anomalies"
    else:
        evidence_summary = "clean frequency spectrum and intact camera metadata"

    if polarity == ClaimPolarity.SYNTHETIC:
        claim = (
            f"Image analysis found {_strength(p)} evidence of synthetic generation "
            f"({evidence_summary}; estimated {pct} probability of synthetic content)."
        )
    elif polarity == ClaimPolarity.AUTHENTIC:
        claim = (
            f"Image analysis found no significant manipulation artifacts "
            f"({evidence_summary}; estimated {pct} probability of synthetic content)."
        )
    else:
        claim = (
            f"Image analysis was borderline ({pct} probability of synthetic content): "
            f"{evidence_summary}."
        )

    return _Adapted(
        p_synthetic=p,
        polarity=polarity,
        claim=claim,
        metrics=ObservationalMetrics(
            spatial=SpatialMetrics(
                sampled_frames=1,
                suspicious_frame_ratio=round(p, 4),
            ),
            image=ImageForensicMetrics(
                frequency_anomaly_detected=has_freq,
                exif_metadata_present=not has_exif,
                model_score=r.get("raw_score"),
            ),
        ),
    )


def _adapt_image_mirror(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    p = _clamp01(r["confidence"])
    polarity = _polarity_from_p(p)
    pct = f"{p:.0%}"
    if polarity == ClaimPolarity.SYNTHETIC:
        claim = f"MIRROR visual backbone detected {_strength(p)} deepfake artifacts ({pct} synthetic probability)."
    elif polarity == ClaimPolarity.AUTHENTIC:
        claim = f"MIRROR visual backbone confirmed authentic natural image structure ({pct} synthetic probability)."
    else:
        claim = f"MIRROR visual backbone was borderline ({pct} synthetic probability)."
    return _Adapted(p_synthetic=p, polarity=polarity, claim=claim)


def _adapt_image_frequency(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    p = _clamp01(r.get("confidence", 0.85 if "frequency_anomaly" in flags else 0.15))
    polarity = _polarity_from_p(p)
    if "frequency_anomaly" in flags or polarity == ClaimPolarity.SYNTHETIC:
        claim = "frequency-domain grid artifacts present from upsampling convolutions or diffusion latent decoding."
    else:
        claim = "clean frequency spectrum with natural power-law decay."
    return _Adapted(
        p_synthetic=p,
        polarity=polarity,
        claim=claim,
        metrics=ObservationalMetrics(
            image=ImageForensicMetrics(frequency_anomaly_detected="frequency_anomaly" in flags)
        ),
    )


def _adapt_image_exif(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    exif_missing = "exif_missing" in flags or r.get("exif_missing", False)
    p = 0.55 if exif_missing else 0.10
    polarity = ClaimPolarity.INCONCLUSIVE if exif_missing else ClaimPolarity.AUTHENTIC
    claim = "no camera metadata found in image container." if exif_missing else "valid camera hardware EXIF metadata verified."
    return _Adapted(
        p_synthetic=p,
        polarity=polarity,
        claim=claim,
        metrics=ObservationalMetrics(
            image=ImageForensicMetrics(exif_metadata_present=not exif_missing)
        ),
    )


# ── detector_text ─────────────────────────────────────────────────────────────
def _adapt_detector_text(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    """
    Adapts the Desklib multi-signal text-detector response into a ForensicClaim.
    Domain: METADATA_INTEGRITY — transformer sequence score, perplexity/burstiness,
    stylometry, minimum-length gating, and opt-in Binoculars corroboration.
    """
    raw_detector_claim = (r.get("evidence") or {}).get("claim", "")
    detector_claim = sanitize_claim_text(
        raw_detector_claim, max_len=MAX_RAW_DETECTOR_CLAIM_LEN, source="text_claim"
    ).sanitized

    if (
        NOT_APPLICABLE_FLAG in flags
        or "text_too_short" in flags
        or r.get("status") == "not_applicable"
    ):
        return _Adapted(
            p_synthetic=0.5,
            polarity=ClaimPolarity.NOT_APPLICABLE,
            claim=detector_claim or "Text analysis was not applicable (insufficient word count).",
            coverage_gap=True,
        )

    p = _clamp01(r["confidence"])  # P(synthetic)
    polarity = _polarity_from_p(p)
    pct = f"{p:.0%}"

    has_low_perp = "uniform_low_perplexity" in flags or "low_perplexity" in flags or (r.get("perplexity_variance") is not None and r.get("perplexity_variance") < 0.25)
    has_low_var = "low_sentence_length_variation" in flags or "low_burstiness" in flags or (r.get("sentence_length_cov") is not None and r.get("sentence_length_cov") < 0.35)
    has_stylo = "stylometry_synthetic" in flags
    has_vocab = "low_vocabulary_diversity" in flags
    has_ngram = "high_ngram_repetition" in flags

    if has_low_perp and has_low_var:
        stylometric_summary = "uniformly low perplexity, low sentence-length variation"
    elif has_stylo or has_vocab:
        stylometric_summary = "low vocabulary diversity and repetitive stylometric pacing"
    elif has_ngram:
        stylometric_summary = "high n-gram repetition across discourse segments"
    else:
        stylometric_summary = "natural syntactic burstiness and lexical diversity"

    if polarity == ClaimPolarity.SYNTHETIC:
        claim = (
            f"Text analysis found {_strength(p)} evidence of AI authorship "
            f"({stylometric_summary}; estimated {pct} probability of synthetic content)."
        )
    elif polarity == ClaimPolarity.AUTHENTIC:
        claim = (
            f"Text analysis found patterns consistent with human authorship "
            f"({stylometric_summary}; estimated {pct} probability of synthetic content)."
        )
    else:
        claim = (
            f"Text analysis was borderline ({pct} probability of synthetic content): "
            f"{stylometric_summary}."
        )

    return _Adapted(
        p_synthetic=p,
        polarity=polarity,
        claim=claim,
        metrics=ObservationalMetrics(
            text=TextForensicMetrics(
                perplexity_score=r.get("perplexity_score"),
                perplexity_variance=r.get("perplexity_variance"),
                type_token_ratio=r.get("type_token_ratio"),
                sentence_length_cov=r.get("sentence_length_cov"),
                ngram_repetition_rate=r.get("ngram_repetition_rate"),
            )
        ),
    )


def _adapt_text_desklib(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    p = _clamp01(r["confidence"])
    polarity = _polarity_from_p(p)
    pct = f"{p:.0%}"
    if polarity == ClaimPolarity.SYNTHETIC:
        claim = f"Fine-tuned Desklib DeBERTa model detected {_strength(p)} markers of LLM generation ({pct} synthetic probability)."
    elif polarity == ClaimPolarity.AUTHENTIC:
        claim = f"Fine-tuned Desklib DeBERTa model verified human authorship semantics ({pct} synthetic probability)."
    else:
        claim = f"Fine-tuned Desklib DeBERTa classification was borderline ({pct} synthetic probability)."
    return _Adapted(p_synthetic=p, polarity=polarity, claim=claim)


def _adapt_text_stylometry(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    p = _clamp01(r.get("confidence", 0.75 if "stylometry_synthetic" in flags else 0.20))
    polarity = _polarity_from_p(p)
    if "stylometry_synthetic" in flags or polarity == ClaimPolarity.SYNTHETIC:
        claim = "low vocabulary diversity and low sentence-length variation characteristic of LLM output."
    else:
        claim = "natural lexical variety and human-like sentence length variance."
    return _Adapted(
        p_synthetic=p,
        polarity=polarity,
        claim=claim,
        metrics=ObservationalMetrics(
            text=TextForensicMetrics(
                type_token_ratio=r.get("type_token_ratio"),
                sentence_length_cov=r.get("sentence_length_cov"),
            )
        ),
    )


def _adapt_text_perplexity(r: Dict[str, Any], flags: List[str]) -> _Adapted:
    p = _clamp01(r.get("confidence", 0.85 if "uniform_low_perplexity" in flags else 0.20))
    polarity = _polarity_from_p(p)
    if "uniform_low_perplexity" in flags or polarity == ClaimPolarity.SYNTHETIC:
        claim = "uniformly low perplexity across all sampled sentence windows."
    else:
        claim = "high perplexity variance with natural burstiness."
    return _Adapted(
        p_synthetic=p,
        polarity=polarity,
        claim=claim,
        metrics=ObservationalMetrics(
            text=TextForensicMetrics(
                perplexity_score=r.get("perplexity_score"),
                perplexity_variance=r.get("perplexity_variance"),
            )
        ),
    )


_ADAPTERS: Dict[str, Callable[[Dict[str, Any], List[str]], _Adapted]] = {
    "video-classifier": _adapt_video_classifier,
    "rppg": _adapt_rppg,
    "syncnet": _adapt_syncnet,
    "aasist": _adapt_aasist,
    "detector_image": _adapt_detector_image,
    "image-mirror": _adapt_image_mirror,
    "image-frequency": _adapt_image_frequency,
    "image-exif": _adapt_image_exif,
    "detector_text": _adapt_detector_text,
    "text-desklib": _adapt_text_desklib,
    "text-stylometry": _adapt_text_stylometry,
    "text-perplexity": _adapt_text_perplexity,
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
            f"Unknown detector '{detector_id}'. Expected one of {sorted(_ADAPTERS)}."
        )

    evidence = response.get("evidence") or {}
    raw_flags = list(evidence.get("flags") or response.get("flags") or [])
    flags, _ = sanitize_flags(raw_flags)
    adapted = adapter(response, flags)
    safe_claim = sanitize_claim_text(
        adapted.claim, max_len=MAX_FORENSIC_CLAIM_LEN, source=f"wrapped_claim:{detector_id}"
    ).sanitized
    raw_job = response.get("job_id") or "unknown"
    safe_job = sanitize_untrusted_text(str(raw_job), max_len=64, strict_chars=True, source="job_id").sanitized or "unknown"
    raw_ver = response.get("model_version") or "unknown"
    safe_ver = sanitize_untrusted_text(str(raw_ver), max_len=64, strict_chars=True, source="model_version").sanitized or "unknown"

    return ForensicClaim(
        claim_id=f"clm-{detector_id}-{safe_job}",
        job_id=safe_job,
        detector_id=detector_id,
        model_version=safe_ver,
        domain=DOMAIN_BY_DETECTOR[detector_id],
        polarity=adapted.polarity,
        confidence=round(adapted.p_synthetic, 4),
        raw_score=response.get("raw_score"),
        claim=safe_claim,
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
        raise ValueError(f"Unknown detector(s): {sorted(unknown)}")

    return [
        wrap_detector_response(det_id, responses[det_id], conditions)
        for det_id in DETECTOR_ORDER
        if responses.get(det_id) is not None
    ]
