"""Shared pytest fixtures for deterministic, fast detector_text test suites."""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

DETECTOR_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = DETECTOR_DIR.parents[1]
if str(DETECTOR_DIR) not in sys.path:
    sys.path.insert(0, str(DETECTOR_DIR))

from binoculars_small import BinocularsMetrics  # noqa: E402
from chunking import ChunkAggregationResult  # noqa: E402
from config import TextDetectorConfig  # noqa: E402
from perplexity import PerplexityMetrics  # noqa: E402


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def make_words(n: int, seed_phrase: str = "forensic verification latency budget pipeline") -> str:
    words = seed_phrase.split()
    out: List[str] = []
    for i in range(n):
        token = words[i % len(words)]
        if i > 0 and i % 15 == 0:
            out.append(f"{token}.")
        else:
            out.append(token)
    if out and not out[-1].endswith("."):
        out[-1] = out[-1] + "."
    return " ".join(out)


class StubDesklibRunner:
    """Deterministic test double avoiding multi-GB transformer downloads in unit tests."""

    def __init__(
        self,
        prob: float = 0.88,
        chunk_scores: Optional[Tuple[float, ...]] = None,
        total_tokens: int = 240,
        sampled_from: Optional[int] = None,
    ) -> None:
        self.prob = prob
        self.chunk_scores = chunk_scores or (prob,)
        self.total_tokens = total_tokens
        self.sampled_from = sampled_from
        self.device = "cpu"
        self.loaded = True
        self.calls: List[str] = []

    def is_loaded(self) -> bool:
        return self.loaded

    def load(self, device: Optional[str] = None) -> None:
        self.loaded = True

    def score_text(
        self,
        text: str,
        chunk_tokens: int = 510,
        overlap: int = 64,
        max_chunks: int = 32,
        spread_threshold: float = 0.35,
    ) -> ChunkAggregationResult:
        self.calls.append(text)
        scores = self.chunk_scores
        spread = round(max(scores) - min(scores), 6) if len(scores) > 1 else 0.0
        disagree = (
            len(scores) > 1
            and spread >= spread_threshold
            and any(s >= 0.55 for s in scores)
            and any(s <= 0.45 for s in scores)
        )
        return ChunkAggregationResult(
            raw_probability=self.prob,
            mean_logit=1.5 if self.prob >= 0.5 else -1.5,
            chunk_scores=scores,
            chunk_token_counts=tuple(120 for _ in scores),
            total_tokens=self.total_tokens,
            chunk_count=len(scores),
            sampled_from_chunks=self.sampled_from or len(scores),
            chunk_spread=spread,
            disagreement=disagree,
        )


class StubPerplexityScorer:
    """Deterministic GPT-2 perplexity test double."""

    def __init__(
        self,
        mean_ppl: float = 22.0,
        cov: float = 0.24,
        available: bool = True,
        raises: Optional[Exception] = None,
    ) -> None:
        self.mean_ppl = mean_ppl
        self.cov = cov
        self.available = available
        self.raises = raises
        self.loaded = True

    def is_loaded(self) -> bool:
        return self.loaded

    def load(self, device: Optional[str] = None) -> None:
        self.loaded = True

    def score(self, text: str) -> PerplexityMetrics:
        if self.raises is not None:
            raise self.raises
        return PerplexityMetrics(
            enabled=True,
            available=self.available,
            model_id="gpt2-stub",
            mean_perplexity=self.mean_ppl,
            median_perplexity=self.mean_ppl * 0.95,
            std_perplexity=round(self.mean_ppl * self.cov, 3),
            sentence_burstiness_cov=self.cov,
            scored_sentence_count=6,
        )


class StubBinocularsScorer:
    """Deterministic small-model Binoculars test double."""

    def __init__(self, ratio: float = 0.72, threshold: float = 0.90) -> None:
        self.ratio = ratio
        self.threshold = threshold
        self.loaded = True

    def is_loaded(self) -> bool:
        return self.loaded

    def load(self, device: Optional[str] = None) -> None:
        self.loaded = True

    def score(self, text: str) -> BinocularsMetrics:
        verdict = "synthetic" if self.ratio < self.threshold else "human"
        return BinocularsMetrics(
            enabled=True,
            available=True,
            performer_id="Qwen/Qwen2.5-0.5B",
            observer_id="Qwen/Qwen2.5-0.5B-Instruct",
            threshold=self.threshold,
            score=self.ratio,
            ai_likelihood=0.86 if verdict == "synthetic" else 0.14,
            verdict=verdict,
        )


@pytest.fixture
def shared_dir(tmp_path: Path) -> Path:
    root = tmp_path / "shared_volume"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def test_config(shared_dir: Path, tmp_path: Path) -> TextDetectorConfig:
    return TextDetectorConfig(
        preload_models=False,
        shared_volume_root=shared_dir,
        calibration_path=tmp_path / "no_cal.json",
        internal_api_key="",
        mesh_strict=False,
    )

