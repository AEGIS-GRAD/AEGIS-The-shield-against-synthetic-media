"""Unit tests for sentence perplexity, burstiness CoV, CUDA OOM CPU fallback, and Binoculars math."""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
import torch

from binoculars_small import (
    BinocularsSmallScorer,
    binoculars_score_to_ai_likelihood,
    compute_binoculars_score_from_logits,
)
from perplexity import PerplexityScorer, split_sentences_for_perplexity


def test_split_sentences_merges_tiny_fragments_and_caps_count():
    text = "Dr. A. This is a normal first sentence with several words. Wait? Yes this second sentence is long enough too."
    sents = split_sentences_for_perplexity(text, max_sentences=64)
    assert len(sents) >= 2
    assert all(len(s.split()) >= 4 for s in sents)

    many = " ".join(f"This sample sentence number {i} contains enough words." for i in range(100))
    capped = split_sentences_for_perplexity(many, max_sentences=12)
    assert len(capped) == 12


def test_perplexity_scorer_exact_nll_and_burstiness_with_fake_causal_lm():
    class TinyTokenizer:
        bos_token_id = 0
        eos_token_id = 0
        pad_token_id = 0

        def __call__(self, sent, return_tensors="pt", truncation=True, max_length=512):
            toks = list(range(1, min(len(sent.split()), max_length) + 1))
            return {"input_ids": torch.tensor([toks], dtype=torch.long)}

    class KnownLossCausalLM:
        def __init__(self, losses_per_call):
            self.losses = list(losses_per_call)
            self.idx = 0

        def __call__(self, input_ids, labels=None):
            loss_val = self.losses[self.idx % len(self.losses)]
            self.idx += 1
            return SimpleNamespace(loss=torch.tensor(loss_val))

    scorer = PerplexityScorer(use_fp16=False, max_sentences=10)
    scorer.tokenizer = TinyTokenizer()
    scorer.device = "cpu"
    # Two sentences: exp(2.0) and exp(3.0)
    l1, l2 = 2.0, 3.0
    scorer.model = KnownLossCausalLM([l1, l2])

    text = "First sufficiently long sentence here. Second sufficiently long sentence follows here."
    metrics = scorer.score(text)
    assert metrics.available is True
    assert metrics.scored_sentence_count == 2
    p1, p2 = math.exp(l1), math.exp(l2)
    expected_mean = (p1 + p2) / 2.0
    expected_std = math.sqrt(((p1 - expected_mean) ** 2 + (p2 - expected_mean) ** 2) / 2.0)
    assert metrics.mean_perplexity == pytest.approx(expected_mean, abs=0.05)
    assert metrics.sentence_burstiness_cov == pytest.approx(expected_std / expected_mean, abs=0.005)


def test_perplexity_cuda_oom_falls_back_cleanly_to_cpu():
    class TinyTokenizer:
        bos_token_id = 0
        eos_token_id = 0

        def __call__(self, sent, **kwargs):
            return {"input_ids": torch.tensor([[1, 2, 3, 4, 5]], dtype=torch.long)}

    class MoveableModel:
        def __init__(self):
            self.on_device = "cuda"

        def float(self):
            return self

        def to(self, dev):
            self.on_device = dev
            return self

        def __call__(self, input_ids, labels=None):
            if self.on_device == "cuda":
                raise RuntimeError("CUDA out of memory")
            return SimpleNamespace(loss=torch.tensor(1.5))

    scorer = PerplexityScorer()
    scorer.tokenizer = TinyTokenizer()
    scorer.device = "cuda"
    scorer.model = MoveableModel()

    # Fake tensor.to('cuda') on CPU-only test hosts by returning CPU tensor cleanly
    orig_tensor_to = torch.Tensor.to
    orig_empty = torch.cuda.empty_cache
    torch.cuda.empty_cache = lambda: None
    torch.Tensor.to = lambda self, dev, *a, **kw: self if str(dev).startswith("cuda") else orig_tensor_to(self, dev, *a, **kw)
    try:
        res = scorer.score("Sentence one with at least five tokens here.")
    finally:
        torch.Tensor.to = orig_tensor_to
        torch.cuda.empty_cache = orig_empty

    assert res.available is True
    assert scorer.device == "cpu"
    assert res.mean_perplexity == pytest.approx(math.exp(1.5), abs=0.05)


def test_binoculars_cross_perplexity_ratio_and_likelihood():
    vocab = 8
    input_ids = torch.tensor([[1, 2, 3, 4]], dtype=torch.long)
    mask = torch.ones_like(input_ids)

    # Identical uniform distributions yield NLL == H(p) == log(vocab) => ratio 1.0
    uniform = torch.zeros((1, 4, vocab))
    ratio_uniform = compute_binoculars_score_from_logits(uniform, uniform, input_ids, mask)
    assert ratio_uniform == pytest.approx(1.0, abs=1e-4)

    # Peaked aligned distributions yield NLL < H(p) and divergent performer lowers ratio further
    peaked = torch.zeros((1, 4, vocab))
    peaked[0, :-1, input_ids[0, 1:]] = 4.0
    ratio_same = compute_binoculars_score_from_logits(peaked, peaked, input_ids, mask)
    assert 0.5 < ratio_same < 1.0

    perf_shifted = torch.full((1, 4, vocab), -2.0)
    perf_shifted[0, :, 7] = 5.0
    ratio_diff = compute_binoculars_score_from_logits(peaked, perf_shifted, input_ids, mask)
    assert ratio_diff < ratio_same

    assert binoculars_score_to_ai_likelihood(0.70, 0.90) > 0.5
    assert binoculars_score_to_ai_likelihood(1.10, 0.90) < 0.5


def test_binoculars_small_scorer_short_and_normal_paths():
    vocab = 8

    class FakeTok:
        pad_token_id = 0

        def __call__(self, text, return_tensors="pt", truncation=True, max_length=512):
            toks = [((i % (vocab - 1)) + 1) for i in range(len(text.split()))]
            ids = torch.tensor([toks], dtype=torch.long)
            return {"input_ids": ids, "attention_mask": torch.ones_like(ids)}

    class FakeCausal:
        def __init__(self, scale: float) -> None:
            self.scale = scale

        def __call__(self, **enc):
            seq_len = enc["input_ids"].shape[1]
            logits = torch.full((1, seq_len, vocab), -1.0)
            logits[:, :, 2] = self.scale
            return SimpleNamespace(logits=logits)

    scorer = BinocularsSmallScorer(threshold=0.90)
    scorer.tokenizer = FakeTok()
    scorer.observer = FakeCausal(3.0)
    scorer.performer = FakeCausal(1.0)
    scorer.device = "cpu"

    too_short = scorer.score("two words")
    assert too_short.available is False
    assert too_short.error == "too_few_tokens"

    scored = scorer.score("enough words to score clean binoculars ratio accurately here")
    assert scored.available is True
    assert scored.score is not None
    assert scored.verdict in {"synthetic", "human"}
    assert scored.to_dict()["enabled"] is True

