"""Opt-in small-model Binoculars zero-shot text detector signal (for 8 GB+ GPUs)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("detector_text.binoculars_small")


@dataclass(frozen=True)
class BinocularsMetrics:
    """Zero-shot observer/performer cross-perplexity divergence metrics."""

    enabled: bool
    available: bool
    performer_id: str
    observer_id: str
    threshold: float
    score: Optional[float] = None
    ai_likelihood: Optional[float] = None
    verdict: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "performer_id": self.performer_id,
            "observer_id": self.observer_id,
            "threshold": self.threshold,
            "score": self.score,
            "ai_likelihood": self.ai_likelihood,
            "verdict": self.verdict,
        }


def compute_binoculars_score_from_logits(
    observer_logits: Any,
    performer_logits: Any,
    input_ids: Any,
    attention_mask: Any,
    pad_token_id: Optional[int] = None,
) -> float:
    """
    Compute Hans et al. (2024) Binoculars ratio: PPL(observer) / X-PPL(observer || performer).

    Lower ratios occur when generated tokens already align tightly with an aligned
    observer's next-token distribution (typical of synthetic LLM outputs).
    """
    import torch
    import torch.nn.functional as F

    shift_obs = observer_logits[:, :-1, :].float().contiguous()
    shift_perf = performer_logits[:, :-1, :].float().contiguous()
    shift_labels = input_ids[:, 1:].contiguous()
    shift_mask = attention_mask[:, 1:].float().contiguous()
    if pad_token_id is not None:
        shift_mask = shift_mask * (shift_labels != pad_token_id).float()

    denom = shift_mask.sum().clamp(min=1.0)

    # Next-token log-likelihood under the observer model
    obs_log_probs = F.log_softmax(shift_obs, dim=-1)
    token_nll = -obs_log_probs.gather(dim=-1, index=shift_labels.unsqueeze(-1)).squeeze(-1)
    ppl = ((token_nll * shift_mask).sum() / denom).item()

    # Token-wise cross-entropy H(p_performer || p_observer) across next-token vocabulary
    perf_probs = F.softmax(shift_perf, dim=-1)
    xppl_per_token = -(perf_probs * obs_log_probs).sum(dim=-1)
    xppl = ((xppl_per_token * shift_mask).sum() / denom).clamp_min(1e-6).item()

    return float(ppl / xppl)


def binoculars_score_to_ai_likelihood(score: float, threshold: float = 0.90) -> float:
    """Map Binoculars ratio cleanly around calibrated threshold into [0, 1] AI score."""
    import math

    # Lower score => higher AI likelihood; slope 10 yields smooth transition across +-0.2
    margin = (threshold - score) * 10.0
    return round(1.0 / (1.0 + math.exp(-max(min(margin, 20.0), -20.0))), 6)


class BinocularsSmallScorer:
    """Lazy-loading paired small causal LMs for optional zero-shot corroboration."""

    def __init__(
        self,
        performer_id: str = "Qwen/Qwen2.5-0.5B",
        observer_id: str = "Qwen/Qwen2.5-0.5B-Instruct",
        threshold: float = 0.90,
        use_fp16: bool = True,
    ) -> None:
        self.performer_id = performer_id
        self.observer_id = observer_id
        self.threshold = threshold
        self.use_fp16 = use_fp16
        self.performer: Any = None
        self.observer: Any = None
        self.tokenizer: Any = None
        self.device: str = "cpu"

    def is_loaded(self) -> bool:
        return (
            self.performer is not None
            and self.observer is not None
            and self.tokenizer is not None
        )

    def load(self, device: Optional[str] = None) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        resolved_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        dtype = (
            torch.float16 if (resolved_device.startswith("cuda") and self.use_fp16) else torch.float32
        )
        logger.info(
            "Loading Binoculars-small pair (%s / %s) on %s (%s)",
            self.performer_id,
            self.observer_id,
            resolved_device,
            dtype,
        )
        self.tokenizer = AutoTokenizer.from_pretrained(self.observer_id)
        if self.tokenizer.pad_token is None and self.tokenizer.eos_token is not None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        self.performer = AutoModelForCausalLM.from_pretrained(
            self.performer_id, torch_dtype=dtype
        ).to(resolved_device)
        self.observer = AutoModelForCausalLM.from_pretrained(
            self.observer_id, torch_dtype=dtype
        ).to(resolved_device)
        self.performer.eval()
        self.observer.eval()
        self.device = resolved_device

    def score(self, text: str, max_length: int = 512) -> BinocularsMetrics:
        import torch

        if not self.is_loaded():
            self.load()

        encoded = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=max_length,
        )
        if encoded["input_ids"].shape[1] < 4:
            return BinocularsMetrics(
                enabled=True,
                available=False,
                performer_id=self.performer_id,
                observer_id=self.observer_id,
                threshold=self.threshold,
                error="too_few_tokens",
            )

        encoded = {k: v.to(self.device) for k, v in encoded.items()}
        with torch.inference_mode():
            obs_out = self.observer(**encoded)
            perf_out = self.performer(**encoded)

        ratio = compute_binoculars_score_from_logits(
            observer_logits=obs_out.logits,
            performer_logits=perf_out.logits,
            input_ids=encoded["input_ids"],
            attention_mask=encoded["attention_mask"],
            pad_token_id=self.tokenizer.pad_token_id,
        )
        ai_prob = binoculars_score_to_ai_likelihood(ratio, threshold=self.threshold)
        verdict = "synthetic" if ratio < self.threshold else "human"
        return BinocularsMetrics(
            enabled=True,
            available=True,
            performer_id=self.performer_id,
            observer_id=self.observer_id,
            threshold=self.threshold,
            score=round(ratio, 4),
            ai_likelihood=ai_prob,
            verdict=verdict,
        )

