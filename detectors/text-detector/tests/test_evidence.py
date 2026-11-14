"""Unit tests for forensic evidence synthesis, flags, and character budget bounds."""
from __future__ import annotations

from binoculars_small import BinocularsMetrics
from chunking import ChunkAggregationResult, LengthGatingResult
from config import SignalThresholds
from evidence import build_forensic_evidence, build_not_applicable_evidence
from ingest import IngestedText
from perplexity import PerplexityMetrics


def _sample_ingested(words: int = 200, stripped: int = 0) -> IngestedText:
    return IngestedText(
        text="Sentence. " * 20,
        source_kind="base64",
        char_count=words * 6,
        word_count=words,
        line_count=4,
        paragraph_count=2,
        stripped_control_chars=stripped,
    )


def _sample_stylometry(
    rep3: float = 0.02, cov: float = 0.5, root_ttr: float = 7.5, verdict: str = "uncertain"
) -> dict:
    return {
        "vocabulary_diversity": {"ttr": 0.65, "root_ttr": root_ttr},
        "ngram_repetition": {"3gram_repetition_rate": rep3, "4gram_repetition_rate": 0.0},
        "sentence_variation": {"sentence_count": 6, "sentence_length_cov": cov},
        "stylometry_verdict": verdict,
    }


def test_evidence_low_perplexity_and_low_burstiness_claim_and_flags():
    ev = build_forensic_evidence(
        ingested=_sample_ingested(200, stripped=4),
        chunk_result=ChunkAggregationResult(
            raw_probability=0.92,
            mean_logit=2.4,
            chunk_scores=(0.94, 0.40),
            chunk_token_counts=(400, 400),
            total_tokens=750,
            chunk_count=2,
            sampled_from_chunks=3,
            chunk_spread=0.54,
            disagreement=True,
        ),
        gating=LengthGatingResult("ok", confidence=0.92, raw_probability=0.92, attenuation_factor=1.0, attenuated=False),
        perplexity=PerplexityMetrics(
            enabled=True,
            available=True,
            model_id="gpt2",
            mean_perplexity=18.2,
            median_perplexity=17.5,
            std_perplexity=3.1,
            sentence_burstiness_cov=0.17,
            scored_sentence_count=8,
        ),
        stylometry=_sample_stylometry(rep3=0.18, cov=0.20, root_ttr=4.2, verdict="human"),
        thresholds=SignalThresholds(),
        binoculars=BinocularsMetrics(
            enabled=True,
            available=True,
            performer_id="p",
            observer_id="o",
            threshold=0.90,
            score=0.71,
            ai_likelihood=0.87,
            verdict="synthetic",
        ),
    )

    assert "uniformly low perplexity across sentences" in ev.claim.lower()
    assert len(ev.claim) <= 512
    assert len(ev.flags) == len(set(ev.flags))
    for expected in (
        "high_ai_probability",
        "low_perplexity",
        "low_burstiness",
        "long_text_sampled",
        "chunk_disagreement",
        "adversarial_unicode_stripped",
        "high_ngram_repetition",
        "low_vocabulary_diversity",
        "uniform_sentence_structure",
        "stylometry_classifier_divergence",
        "binoculars_small_enabled",
        "binoculars_corroborated",
    ):
        assert expected in ev.flags


def test_evidence_human_high_perplexity_and_binoculars_divergence():
    ev = build_forensic_evidence(
        ingested=_sample_ingested(180),
        chunk_result=ChunkAggregationResult(
            raw_probability=0.12,
            mean_logit=-2.0,
            chunk_scores=(0.12,),
            chunk_token_counts=(220,),
            total_tokens=220,
            chunk_count=1,
            sampled_from_chunks=1,
            chunk_spread=0.0,
            disagreement=False,
        ),
        gating=LengthGatingResult("ok", confidence=0.12, raw_probability=0.12, attenuation_factor=1.0, attenuated=False),
        perplexity=PerplexityMetrics(
            enabled=True,
            available=True,
            model_id="gpt2",
            mean_perplexity=210.4,
            median_perplexity=190.0,
            std_perplexity=160.0,
            sentence_burstiness_cov=0.76,
            scored_sentence_count=7,
        ),
        stylometry=_sample_stylometry(verdict="synthetic"),
        thresholds=SignalThresholds(),
        binoculars=BinocularsMetrics(
            enabled=True,
            available=True,
            performer_id="p",
            observer_id="o",
            threshold=0.90,
            score=0.75,
            ai_likelihood=0.81,
            verdict="synthetic",
        ),
    )
    assert "likely_human_authored" in ev.flags
    assert "high_perplexity" in ev.flags
    assert "natural_burstiness" in ev.flags
    assert "stylometry_classifier_divergence" in ev.flags
    assert "binoculars_divergence" in ev.flags
    assert len(ev.claim) <= 512


def test_not_applicable_evidence_has_explicit_short_flags():
    ev = build_not_applicable_evidence(_sample_ingested(words=14, stripped=3), min_words=40)
    assert "text_too_short" in ev.flags
    assert "insufficient_signal" in ev.flags
    assert "adversarial_unicode_stripped" in ev.flags
    assert "14 words" in ev.claim
