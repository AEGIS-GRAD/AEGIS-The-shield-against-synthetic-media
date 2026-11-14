"""GPT-2 perplexity and sentence-level burstiness extractor for explainable text forensics."""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("detector_text.perplexity")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class PerplexityMetrics:
    """Sentence- and document-level language model predictability metrics."""

    enabled: bool
    available: bool
    model_id: str
    mean_perplexity: Optional[float] = None
    median_perplexity: Optional[float] = None
    std_perplexity: Optional[float] = None
    sentence_burstiness_cov: Optional[float] = None
    scored_sentence_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "model_id": self.model_id,
            "mean_perplexity": self.mean_perplexity,
            "median_perplexity": self.median_perplexity,
            "std_perplexity": self.std_perplexity,
            "sentence_burstiness_cov": self.sentence_burstiness_cov,
            "scored_sentence_count": self.scored_sentence_count,
        }


def split_sentences_for_perplexity(text: str, max_sentences: int = 64) -> List[str]:
    """Split text into scorable sentences, merging tiny fragments so NLL stays meaningful."""
    raw_parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p and p.strip()]
    merged: List[str] = []
    buffer = ""
    for part in raw_parts:
        candidate = f"{buffer} {part}".strip() if buffer else part
        if len(candidate.split()) < 4:
            buffer = candidate
            continue
        merged.append(candidate)
        buffer = ""
        if len(merged) >= max_sentences:
            break

    if buffer:
        if merged:
            merged[-1] = f"{merged[-1]} {buffer}".strip()
        elif len(buffer.split()) >= 2:
            merged.append(buffer)

    return merged[:max_sentences]


class PerplexityScorer:
    """Lazy-loading fp16/CPU GPT-2 scorer for perplexity and burstiness signals."""

    def __init__(
        self,
        model_dir: Path | str | None = None,
        model_id: str = "gpt2",
        use_fp16: bool = True,
        max_sentences: int = 64,
    ) -> None:
        self.model_dir = Path(model_dir) if model_dir else None
        self.model_id = model_id
        self.use_fp16 = use_fp16
        self.max_sentences = max_sentences
        self.model: Any = None
        self.tokenizer: Any = None
        self.device: str = "cpu"

    def is_loaded(self) -> bool:
        return self.model is not None and self.tokenizer is not None

    def load(self, device: Optional[str] = None) -> None:
        """Load local cached GPT-2 checkpoint first, falling back to Hub ID if permitted."""
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        resolved_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        source = (
            str(self.model_dir)
            if self.model_dir is not None and self.model_dir.exists() and any(self.model_dir.iterdir())
            else self.model_id
        )
        dtype = torch.float16 if (resolved_device.startswith("cuda") and self.use_fp16) else torch.float32

        logger.info("Loading perplexity model '%s' on %s (%s)", source, resolved_device, dtype)
        self.tokenizer = AutoTokenizer.from_pretrained(source)
        if self.tokenizer.pad_token is None and self.tokenizer.eos_token is not None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(source, torch_dtype=dtype).to(
            resolved_device
        )
        self.model.eval()
        self.device = resolved_device

    def _compute_sentence_perplexities(self, sentences: List[str]) -> Tuple[List[float], List[int]]:
        """Score token-weighted NLL per sentence; falls back to CPU if CUDA runs OOM."""
        import torch

        def _run_on_device() -> Tuple[List[float], List[int]]:
            ppls: List[float] = []
            tok_counts: List[int] = []
            bos_id = self.tokenizer.bos_token_id or self.tokenizer.eos_token_id
            with torch.inference_mode():
                for sent in sentences:
                    encoded = self.tokenizer(
                        sent,
                        return_tensors="pt",
                        truncation=True,
                        max_length=512,
                    )
                    input_ids = encoded["input_ids"]
                    if input_ids.shape[1] < 2 and bos_id is not None:
                        bos = torch.tensor([[bos_id]], dtype=input_ids.dtype)
                        input_ids = torch.cat([bos, input_ids], dim=1)
                    if input_ids.shape[1] < 2:
                        continue
                    input_ids = input_ids.to(self.device)
                    outputs = self.model(input_ids=input_ids, labels=input_ids)
                    nll = float(outputs.loss.detach().cpu().item())
                    # Guard numerical overflow on degenerate strings
                    ppls.append(math.exp(min(nll, 20.0)))
                    tok_counts.append(int(input_ids.shape[1]))
            return ppls, tok_counts

        try:
            return _run_on_device()
        except RuntimeError as exc:
            if "out of memory" in str(exc).lower() and str(self.device).startswith("cuda"):
                logger.warning("CUDA OOM in GPT-2 perplexity scorer; moving GPT-2 to CPU")
                torch.cuda.empty_cache()
                self.model = self.model.float().to("cpu")
                self.device = "cpu"
                return _run_on_device()
            raise

    def score(self, text: str) -> PerplexityMetrics:
        """Compute mean/median perplexity and sentence burstiness (CoV of per-sentence PPL)."""
        if not text.strip():
            return PerplexityMetrics(
                enabled=True,
                available=False,
                model_id=self.model_id,
                error="empty_text",
            )
        if not self.is_loaded():
            self.load()

        sentences = split_sentences_for_perplexity(text, max_sentences=self.max_sentences)
        if not sentences:
            sentences = [text[:2000]]

        ppls, _ = self._compute_sentence_perplexities(sentences)
        if not ppls:
            return PerplexityMetrics(
                enabled=True,
                available=False,
                model_id=self.model_id,
                error="no_scorable_sentences",
            )

        sorted_ppls = sorted(ppls)
        n = len(ppls)
        mean_ppl = sum(ppls) / n
        mid = n // 2
        median_ppl = (
            sorted_ppls[mid] if n % 2 == 1 else 0.5 * (sorted_ppls[mid - 1] + sorted_ppls[mid])
        )
        if n >= 2 and mean_ppl > 0:
            variance = sum((p - mean_ppl) ** 2 for p in ppls) / n
            std_ppl = math.sqrt(variance)
            cov = std_ppl / mean_ppl
        else:
            std_ppl = None
            cov = None

        return PerplexityMetrics(
            enabled=True,
            available=True,
            model_id=self.model_id,
            mean_perplexity=round(mean_ppl, 3),
            median_perplexity=round(median_ppl, 3),
            std_perplexity=round(std_ppl, 3) if std_ppl is not None else None,
            sentence_burstiness_cov=round(cov, 4) if cov is not None else None,
            scored_sentence_count=n,
        )

