"""Forensic evidence synthesis mapping multi-signal outputs into readable claims and flags."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from binoculars_small import BinocularsMetrics
from chunking import ChunkAggregationResult, LengthGatingResult
from config import SignalThresholds
from ingest import IngestedText
from perplexity import PerplexityMetrics


@dataclass(frozen=True)
class ForensicEvidence:
    """Contract-conformant `evidence` object plus diagnostic flag list."""

    claim: str
    flags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"claim": self.claim, "flags": self.flags}


def _dedupe_flags(flags: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for flag in flags:
        clean = flag.strip().lower()[:64]
        if clean and clean not in seen:
            seen.add(clean)
            ordered.append(clean)
    return ordered


def build_not_applicable_evidence(ingested: IngestedText, min_words: int) -> ForensicEvidence:
    """Produce explicit insufficient-length explanation when text cannot be reliably scored."""
    flags = ["text_too_short", "insufficient_signal"]
    if ingested.stripped_control_chars >= 3:
        flags.append("adversarial_unicode_stripped")
    claim = (
        f"Text too short for reliable synthetic text attribution ({ingested.word_count} words; "
        f"minimum {min_words} words required)."
    )
    return ForensicEvidence(claim=claim[:512], flags=_dedupe_flags(flags))


def build_forensic_evidence(
    ingested: IngestedText,
    chunk_result: ChunkAggregationResult,
    gating: LengthGatingResult,
    perplexity: PerplexityMetrics,
    stylometry: Dict[str, Any],
    thresholds: SignalThresholds,
    binoculars: Optional[BinocularsMetrics] = None,
) -> ForensicEvidence:
    """Synthesize Desklib, chunking, perplexity, burstiness, stylometry, and gating signals."""
    flags: List[str] = []
    clauses: List[str] = []
    conf = gating.confidence

    # 1. Core classifier stance
    if conf >= 0.70:
        flags.append("high_ai_probability")
        clauses.append(f"Desklib classifier indicates likely AI-generated text (score {conf:.2f}).")
    elif conf >= 0.55:
        flags.append("moderate_ai_probability")
        clauses.append(f"Desklib classifier leans toward AI-generated text (score {conf:.2f}).")
    elif conf <= 0.30:
        flags.append("likely_human_authored")
        clauses.append(f"Desklib classifier indicates likely human-authored text (score {conf:.2f}).")
    else:
        flags.append("uncertain_authorship_band")
        clauses.append(f"Desklib classifier falls in an uncertain band (score {conf:.2f}).")

    # 2. Perplexity + sentence burstiness prose
    if perplexity.available and perplexity.mean_perplexity is not None:
        ppl = perplexity.mean_perplexity
        cov = perplexity.sentence_burstiness_cov
        low_ppl = ppl <= thresholds.low_perplexity_threshold
        high_ppl = ppl >= thresholds.high_perplexity_threshold
        low_burst = cov is not None and cov <= thresholds.low_burstiness_cov_threshold

        if low_ppl and low_burst:
            flags.extend(["low_perplexity", "low_burstiness"])
            clauses.append(
                f"Uniformly low perplexity across sentences (mean PPL {ppl:.1f}, CoV {cov:.2f})."
            )
        else:
            if low_ppl:
                flags.append("low_perplexity")
                clauses.append(f"Low language-model perplexity (mean PPL {ppl:.1f}).")
            elif high_ppl:
                flags.append("high_perplexity")
                clauses.append(
                    f"Elevated perplexity consistent with unconstrained phrasing (mean PPL {ppl:.1f})."
                )
            if low_burst and cov is not None:
                flags.append("low_burstiness")
                clauses.append(f"Low sentence-length/predictability burstiness (CoV {cov:.2f}).")
            elif cov is not None and cov >= 0.65:
                flags.append("natural_burstiness")
                clauses.append(f"Natural sentence-to-sentence burstiness (CoV {cov:.2f}).")

    # 3. Long-text chunking + disagreement checks
    if chunk_result.sampled_from_chunks > chunk_result.chunk_count:
        flags.append("long_text_sampled")
    if chunk_result.disagreement:
        flags.append("chunk_disagreement")
        clauses.append(
            f"Mixed authorship signals across {chunk_result.chunk_count} text chunks "
            f"(score spread {chunk_result.chunk_spread:.2f})."
        )

    # 4. Short-text marginal attenuation & Unicode sanitation
    if gating.attenuated and gating.status == "ok":
        flags.append("short_text_attenuated")
        clauses.append(
            f"Marginal text length ({ingested.word_count} words); confidence attenuated toward 0.50."
        )
    if ingested.stripped_control_chars >= 3:
        flags.append("adversarial_unicode_stripped")
        clauses.append(
            f"Sanitized {ingested.stripped_control_chars} invisible/bidi control characters."
        )

    # 5. Stylometry explainability signals (cross-check with neural classifier)
    ngram = stylometry.get("ngram_repetition", {})
    if ngram.get("3gram_repetition_rate", 0.0) >= 0.12 or ngram.get("4gram_repetition_rate", 0.0) >= 0.08:
        flags.append("high_ngram_repetition")
        clauses.append("Elevated 3-gram/4-gram phrase repetition.")
    vocab = stylometry.get("vocabulary_diversity", {})
    if ingested.word_count >= 80 and vocab.get("root_ttr", 99.0) <= 5.0:
        flags.append("low_vocabulary_diversity")
    sent_var = stylometry.get("sentence_variation", {})
    if sent_var.get("sentence_count", 0) >= 3 and sent_var.get("sentence_length_cov", 1.0) <= 0.25:
        flags.append("uniform_sentence_structure")

    style_verdict = stylometry.get("stylometry_verdict")
    if (conf >= 0.65 and style_verdict == "human") or (conf <= 0.35 and style_verdict == "synthetic"):
        flags.append("stylometry_classifier_divergence")

    # 6. Optional Binoculars small-model cross-check
    if binoculars is not None and binoculars.enabled and binoculars.available:
        flags.append("binoculars_small_enabled")
        if binoculars.verdict == "synthetic" and conf >= 0.55:
            flags.append("binoculars_corroborated")
            clauses.append(f"Binoculars-small ratio {binoculars.score:.2f} corroborates synthetic output.")
        elif binoculars.verdict == "human" and conf <= 0.45:
            flags.append("binoculars_corroborated")
        elif binoculars.verdict is not None:
            flags.append("binoculars_divergence")

    claim = " ".join(clauses)
    if len(claim) > 512:
        claim = claim[:509].rstrip() + "..."

    return ForensicEvidence(claim=claim, flags=_dedupe_flags(flags))

