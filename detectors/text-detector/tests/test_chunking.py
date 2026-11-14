"""Unit tests for token windowing, weighted logit aggregation, OOM backoff, and length gating."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pytest
import torch

from chunking import (
    aggregate_chunk_predictions,
    apply_length_gating,
    score_long_text,
    sigmoid,
    split_token_ids_into_chunks,
)
from desklib_runner import DesklibRunner, _extract_logits


def test_split_token_ids_respects_overlap_and_max_chunk_striding():
    short_chunks, total = split_token_ids_into_chunks(list(range(200)), chunk_tokens=510, overlap=64)
    assert total == 1
    assert len(short_chunks) == 1
    assert short_chunks[0].token_count == 200

    # 1200 tokens with window=510, overlap=64 => starts at 0, 446, 892
    chunks, total_med = split_token_ids_into_chunks(list(range(1200)), chunk_tokens=510, overlap=64, max_chunks=32)
    assert total_med == 3
    assert [(c.start_token, c.end_token) for c in chunks] == [(0, 510), (446, 956), (892, 1200)]

    # Very long document exceeding max_chunks striding preserves start and end
    huge_chunks, total_huge = split_token_ids_into_chunks(
        list(range(30_000)), chunk_tokens=510, overlap=64, max_chunks=8
    )
    assert total_huge > 8
    assert len(huge_chunks) == 8
    assert huge_chunks[0].index == 0
    assert huge_chunks[-1].index == total_huge - 1


def test_weighted_logit_aggregation_and_disagreement_detection():
    # Consistent high-AI chunks -> no disagreement
    agg = aggregate_chunk_predictions([2.0, 2.5], [510, 100], total_tokens=546, sampled_from_chunks=2)
    expected_logit = (2.0 * 510 + 2.5 * 100) / 610
    assert agg.mean_logit == pytest.approx(expected_logit, abs=1e-5)
    assert agg.raw_probability == pytest.approx(sigmoid(expected_logit), abs=1e-5)
    assert agg.disagreement is False

    # Conflicting chunks straddling 0.5 boundary -> disagreement=True
    mixed = aggregate_chunk_predictions([2.2, -2.0], [500, 500], total_tokens=936, sampled_from_chunks=2)
    assert mixed.chunk_spread > 0.75
    assert mixed.disagreement is True


def test_score_long_text_does_not_truncate():
    class WordTokenizer:
        def __call__(self, text: str, **kwargs) -> Dict[str, List[int]]:
            return {"input_ids": list(range(len(text.split())))}

    text = " ".join(f"w{i}" for i in range(1100))
    seen_chunks = []

    def fake_predict(chunks):
        seen_chunks.extend(chunks)
        return [1.8 for _ in chunks]

    res = score_long_text(
        text, WordTokenizer(), fake_predict, chunk_tokens=510, overlap=64, max_chunks=32
    )
    assert res.total_tokens == 1100
    assert res.chunk_count == 3
    assert len(seen_chunks) == 3


def test_length_gating_not_applicable_marginal_attenuation_and_full():
    too_short = apply_length_gating(0.95, word_count=39, min_words=40, reliable_words=150)
    assert too_short.status == "not_applicable"
    assert too_short.confidence == 0.5
    assert too_short.attenuated is True

    # At word_count=75 out of 150 (alpha=0.5): 0.5 + (0.90 - 0.5) * 0.5 = 0.70
    marginal = apply_length_gating(0.90, word_count=75, min_words=40, reliable_words=150)
    assert marginal.status == "ok"
    assert marginal.attenuated is True
    assert marginal.attenuation_factor == pytest.approx(0.5)
    assert marginal.confidence == pytest.approx(0.70)

    # Human score moves from 0.10 halfway toward 0.50 -> 0.30
    marginal_human = apply_length_gating(0.10, word_count=75, min_words=40, reliable_words=150)
    assert marginal_human.confidence == pytest.approx(0.30)

    full = apply_length_gating(0.9123, word_count=150, min_words=40, reliable_words=150)
    assert full.status == "ok"
    assert full.attenuated is False
    assert full.confidence == pytest.approx(0.9123)


def test_desklib_runner_cuda_oom_backoff_and_logit_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    runner = DesklibRunner(model_dir=tmp_path, batch_size=4)
    runner.device = torch.device("cuda")

    class FakeTokenizer:
        cls_token_id = 101
        sep_token_id = 102
        pad_token_id = 0

    attempts = []

    class OOMOnLargeBatchModel:
        def __call__(self, input_ids, attention_mask):
            attempts.append(int(input_ids.shape[0]))
            if input_ids.shape[0] > 2:
                raise RuntimeError("CUDA out of memory")
            return torch.full((input_ids.shape[0], 1), 1.25)

    runner.tokenizer = FakeTokenizer()
    runner.model = OOMOnLargeBatchModel()

    # Keep tensor creation on CPU so this CUDA-OOM backoff test also passes in CPU-only CI
    monkeypatch.setattr(
        runner,
        "_build_batch_tensors",
        lambda batch: (
            torch.ones((len(batch), 4), dtype=torch.long),
            torch.ones((len(batch), 4), dtype=torch.long),
        ),
    )
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)

    chunks = [(10, 11, 12), (20, 21), (30, 31, 32, 33), (40, 41)]
    logits = runner.predict_chunk_logits(chunks)

    assert attempts[0] == 4
    assert attempts[1:] == [2, 2]
    assert logits == pytest.approx([1.25, 1.25, 1.25, 1.25])

    assert _extract_logits({"logits": torch.tensor([[0.5]])}).tolist() == pytest.approx([0.5])
    assert _extract_logits((torch.tensor([[0.7]]),)).tolist() == pytest.approx([0.7])


def test_desklib_runner_build_batch_tensors_and_score_text(tmp_path: Path):
    runner = DesklibRunner(model_dir=tmp_path, batch_size=2)
    runner.device = torch.device("cpu")

    class FakeTokenizer:
        cls_token_id = 101
        sep_token_id = 102
        pad_token_id = 0

        def __call__(self, text: str, **kwargs):
            return {"input_ids": list(range(10, 10 + len(text.split())))}

    seen_masks = []

    class RecordingModel:
        def __call__(self, input_ids, attention_mask):
            seen_masks.append(attention_mask.tolist())
            return torch.full((input_ids.shape[0], 1), 1.4)

    runner.tokenizer = FakeTokenizer()
    runner.model = RecordingModel()

    ids, mask = runner._build_batch_tensors([(5, 6), (7, 8, 9, 10)])
    # Longest sequence is 1 CLS + 4 tokens + 1 SEP = 6; shorter gets 2 pad zeros
    assert ids.tolist() == [[101, 5, 6, 102, 0, 0], [101, 7, 8, 9, 10, 102]]
    assert mask.tolist() == [[1, 1, 1, 1, 0, 0], [1, 1, 1, 1, 1, 1]]

    long_doc = " ".join(f"tok{i}" for i in range(600))
    res = runner.score_text(long_doc, chunk_tokens=510, overlap=64)
    assert res.chunk_count == 2
    assert res.total_tokens == 600
    assert res.raw_probability == pytest.approx(sigmoid(1.4), abs=1e-4)

