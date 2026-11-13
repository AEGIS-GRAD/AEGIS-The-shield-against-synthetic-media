"""Token chunking, weighted logit aggregation, and minimum-length confidence gating."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class TextChunk:
    """Single tokenized window inside DeBERTa's 512-token limit."""

    index: int
    token_ids: Tuple[int, ...]
    start_token: int
    end_token: int

    @property
    def token_count(self) -> int:
        return len(self.token_ids)


@dataclass(frozen=True)
class ChunkAggregationResult:
    """Aggregated classifier output across one or more token windows."""

    raw_probability: float
    mean_logit: float
    chunk_scores: Tuple[float, ...]
    chunk_token_counts: Tuple[int, ...]
    total_tokens: int
    chunk_count: int
    sampled_from_chunks: int
    chunk_spread: float
    disagreement: bool


@dataclass(frozen=True)
class LengthGatingResult:
    """Minimum-length gating and marginal-length confidence attenuation decision."""

    status: str  # "ok" | "not_applicable"
    confidence: float
    raw_probability: float
    attenuation_factor: float
    attenuated: bool


def sigmoid(x: float) -> float:
    """Numerically stable logistic sigmoid."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def logit(prob: float, eps: float = 1e-6) -> float:
    """Numerically clamped log-odds."""
    p = min(max(prob, eps), 1.0 - eps)
    return math.log(p / (1.0 - p))


def split_token_ids_into_chunks(
    token_ids: Sequence[int],
    chunk_tokens: int = 510,
    overlap: int = 64,
    max_chunks: int = 32,
) -> Tuple[List[TextChunk], int]:
    """
    Slice token IDs (excluding special CLS/SEP tokens) into overlapping windows.

    Returns (selected_chunks, total_chunks_before_cap). If the full sequence produces
    more than `max_chunks` windows, evenly strided windows are chosen so beginning,
    middle, and ending passages all remain represented.
    """
    if chunk_tokens <= 0:
        raise ValueError("chunk_tokens must be positive")
    if overlap < 0 or overlap >= chunk_tokens:
        raise ValueError("overlap must satisfy 0 <= overlap < chunk_tokens")
    if max_chunks <= 0:
        raise ValueError("max_chunks must be positive")

    n_tokens = len(token_ids)
    if n_tokens == 0:
        return [], 0

    if n_tokens <= chunk_tokens:
        return [TextChunk(index=0, token_ids=tuple(token_ids), start_token=0, end_token=n_tokens)], 1

    step = chunk_tokens - overlap
    all_chunks: List[TextChunk] = []
    start = 0
    idx = 0
    while start < n_tokens:
        end = min(start + chunk_tokens, n_tokens)
        all_chunks.append(
            TextChunk(
                index=idx,
                token_ids=tuple(token_ids[start:end]),
                start_token=start,
                end_token=end,
            )
        )
        if end >= n_tokens:
            break
        start += step
        idx += 1

    total_windows = len(all_chunks)
    if total_windows <= max_chunks:
        return all_chunks, total_windows

    # Deterministic evenly-spaced striding including first and last windows
    if max_chunks == 1:
        return [all_chunks[0]], total_windows

    indices = sorted(
        {
            round(i * (total_windows - 1) / (max_chunks - 1))
            for i in range(max_chunks)
        }
    )
    sampled = [all_chunks[i] for i in indices]
    return sampled, total_windows


def aggregate_chunk_predictions(
    chunk_logits: Sequence[float],
    chunk_token_counts: Sequence[int],
    total_tokens: int,
    sampled_from_chunks: int,
    spread_threshold: float = 0.35,
) -> ChunkAggregationResult:
    """Compute token-weighted mean logit and chunk-level spread/disagreement diagnostics."""
    if not chunk_logits or len(chunk_logits) != len(chunk_token_counts):
        raise ValueError("chunk_logits and chunk_token_counts must be non-empty and equal length")

    weights = [max(1, int(c)) for c in chunk_token_counts]
    total_weight = sum(weights)
    mean_logit = sum(l * w for l, w in zip(chunk_logits, weights)) / total_weight
    raw_prob = sigmoid(mean_logit)
    scores = tuple(round(sigmoid(float(l)), 6) for l in chunk_logits)
    spread = round(max(scores) - min(scores), 6) if len(scores) > 1 else 0.0

    # Mixed document disagreement: meaningful spread AND chunks straddle the 0.5 boundary
    has_ai_chunk = any(s >= 0.55 for s in scores)
    has_human_chunk = any(s <= 0.45 for s in scores)
    disagreement = len(scores) > 1 and spread >= spread_threshold and has_ai_chunk and has_human_chunk

    return ChunkAggregationResult(
        raw_probability=round(raw_prob, 6),
        mean_logit=round(mean_logit, 6),
        chunk_scores=scores,
        chunk_token_counts=tuple(int(c) for c in chunk_token_counts),
        total_tokens=total_tokens,
        chunk_count=len(chunk_logits),
        sampled_from_chunks=sampled_from_chunks,
        chunk_spread=spread,
        disagreement=disagreement,
    )


def score_long_text(
    text: str,
    tokenizer: Any,
    predict_logits_fn: Callable[[List[Tuple[int, ...]]], List[float]],
    chunk_tokens: int = 510,
    overlap: int = 64,
    max_chunks: int = 32,
    spread_threshold: float = 0.35,
) -> ChunkAggregationResult:
    """Tokenize once without truncation, chunk into overlapping windows, and aggregate logits."""
    encoded = tokenizer(
        text,
        add_special_tokens=False,
        truncation=False,
        return_attention_mask=False,
    )
    token_ids: List[int] = list(encoded["input_ids"])
    chunks, total_windows = split_token_ids_into_chunks(
        token_ids,
        chunk_tokens=chunk_tokens,
        overlap=overlap,
        max_chunks=max_chunks,
    )
    if not chunks:
        return ChunkAggregationResult(
            raw_probability=0.5,
            mean_logit=0.0,
            chunk_scores=(),
            chunk_token_counts=(),
            total_tokens=0,
            chunk_count=0,
            sampled_from_chunks=0,
            chunk_spread=0.0,
            disagreement=False,
        )

    logits = predict_logits_fn([c.token_ids for c in chunks])
    counts = [c.token_count for c in chunks]
    return aggregate_chunk_predictions(
        chunk_logits=logits,
        chunk_token_counts=counts,
        total_tokens=len(token_ids),
        sampled_from_chunks=total_windows,
        spread_threshold=spread_threshold,
    )


def apply_length_gating(
    raw_probability: float,
    word_count: int,
    min_words: int = 40,
    reliable_words: int = 150,
) -> LengthGatingResult:
    """
    Gate sub-minimum inputs to `not_applicable` and attenuate marginal lengths toward 0.5.

    In AEGIS, `0.0 = Authentic` and `1.0 = Synthetic`. Pulling toward `0.5` represents
    lowered diagnostic certainty without fabricating a false human or AI verdict.
    """
    if word_count < min_words:
        return LengthGatingResult(
            status="not_applicable",
            confidence=0.5,
            raw_probability=round(raw_probability, 6),
            attenuation_factor=0.0,
            attenuated=True,
        )

    if word_count < reliable_words and reliable_words > min_words:
        alpha = max(0.0, min(1.0, float(word_count) / float(reliable_words)))
        calibrated = 0.5 + (raw_probability - 0.5) * alpha
        return LengthGatingResult(
            status="ok",
            confidence=round(min(max(calibrated, 0.0), 1.0), 6),
            raw_probability=round(raw_probability, 6),
            attenuation_factor=round(alpha, 4),
            attenuated=True,
        )

    return LengthGatingResult(
        status="ok",
        confidence=round(min(max(raw_probability, 0.0), 1.0), 6),
        raw_probability=round(raw_probability, 6),
        attenuation_factor=1.0,
        attenuated=False,
    )

