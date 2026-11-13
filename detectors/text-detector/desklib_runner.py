"""Wrapper over DesklibAIDetectionModel adding fp16 CUDA support, LoRA adapters, and OOM-safe chunk batching."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import torch

from chunking import ChunkAggregationResult, score_long_text
from desklib_model import load_desklib

logger = logging.getLogger("detector_text.desklib_runner")


def _extract_logits(output: Any) -> torch.Tensor:
    """Normalize tensor/dict/ModelOutput return values into a 1D tensor of scalar logits."""
    if isinstance(output, dict):
        tensor = output["logits"]
    elif hasattr(output, "logits"):
        tensor = output.logits
    elif isinstance(output, (tuple, list)):
        tensor = output[0]
    else:
        tensor = output
    return tensor.reshape(-1)


class DesklibRunner:
    """Manages Desklib model lifecycle and dynamic-padded chunk inference."""

    def __init__(
        self,
        model_dir: Path,
        model_name: str = "desklib/ai-text-detector-v1.01",
        lora_dir: str = "",
        use_fp16: bool = True,
        batch_size: int = 4,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.model_name = model_name
        self.lora_dir = lora_dir.strip()
        self.use_fp16 = use_fp16
        self.batch_size = max(1, batch_size)
        self.model: Any = None
        self.tokenizer: Any = None
        self.device: torch.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def is_loaded(self) -> bool:
        return self.model is not None and self.tokenizer is not None

    def _resolve_model_source(self) -> str:
        if self.model_dir.exists() and (self.model_dir / "config.json").exists():
            return str(self.model_dir)
        return self.model_name

    def load(self, device: Optional[str] = None) -> None:
        """Load Desklib weights (fp16 on CUDA if configured) plus optional LoRA adapter."""
        target = torch.device(device) if device else self.device
        source = self._resolve_model_source()
        logger.info("Loading Desklib checkpoint from '%s' onto %s", source, target)

        model, tokenizer, resolved_dev = load_desklib(model_dir=source, device=target)
        if self.lora_dir:
            lora_path = Path(self.lora_dir)
            if not lora_path.exists():
                raise FileNotFoundError(f"AEGIS_TEXT_LORA_DIR does not exist: {lora_path}")
            from peft import PeftModel

            logger.info("Attaching PEFT LoRA adapter from '%s'", lora_path)
            model = PeftModel.from_pretrained(model, str(lora_path))
            model.to(resolved_dev)

        if resolved_dev.type == "cuda" and self.use_fp16:
            model = model.half()
        else:
            model = model.float()

        model.eval()
        self.model = model
        self.tokenizer = tokenizer
        self.device = resolved_dev

    def _special_token_ids(self) -> Tuple[Optional[int], Optional[int], int]:
        cls_id = getattr(self.tokenizer, "cls_token_id", None)
        if cls_id is None:
            cls_id = getattr(self.tokenizer, "bos_token_id", None)
        sep_id = getattr(self.tokenizer, "sep_token_id", None)
        if sep_id is None:
            sep_id = getattr(self.tokenizer, "eos_token_id", None)
        pad_id = getattr(self.tokenizer, "pad_token_id", None)
        return cls_id, sep_id, int(pad_id if pad_id is not None else 0)

    def _build_batch_tensors(self, batch_chunks: Sequence[Tuple[int, ...]]) -> Tuple[torch.Tensor, torch.Tensor]:
        cls_id, sep_id, pad_id = self._special_token_ids()
        wrapped: List[List[int]] = []
        for ids in batch_chunks:
            seq: List[int] = []
            if cls_id is not None:
                seq.append(int(cls_id))
            seq.extend(int(t) for t in ids)
            if sep_id is not None:
                seq.append(int(sep_id))
            wrapped.append(seq)

        max_len = max(len(seq) for seq in wrapped)
        padded_ids: List[List[int]] = []
        masks: List[List[int]] = []
        for seq in wrapped:
            pad_len = max_len - len(seq)
            padded_ids.append(seq + [pad_id] * pad_len)
            masks.append([1] * len(seq) + [0] * pad_len)

        input_tensor = torch.tensor(padded_ids, dtype=torch.long, device=self.device)
        mask_tensor = torch.tensor(masks, dtype=torch.long, device=self.device)
        return input_tensor, mask_tensor

    def predict_chunk_logits(self, chunks: List[Tuple[int, ...]]) -> List[float]:
        """Run dynamic-padded batched inference across token chunks with CUDA OOM backoff."""
        if not self.is_loaded():
            self.load()

        current_bs = self.batch_size
        idx = 0
        logits_out: List[float] = []

        while idx < len(chunks):
            batch = chunks[idx : idx + current_bs]
            try:
                input_ids, attention_mask = self._build_batch_tensors(batch)
                with torch.inference_mode():
                    raw = self.model(input_ids=input_ids, attention_mask=attention_mask)
                batch_logits = _extract_logits(raw).float().detach().cpu().tolist()
                logits_out.extend(float(v) for v in batch_logits)
                idx += len(batch)
            except RuntimeError as exc:
                if (
                    "out of memory" in str(exc).lower()
                    and self.device.type == "cuda"
                    and current_bs > 1
                ):
                    torch.cuda.empty_cache()
                    next_bs = max(1, current_bs // 2)
                    logger.warning(
                        "CUDA OOM at chunk batch_size=%d; backing off to batch_size=%d",
                        current_bs,
                        next_bs,
                    )
                    current_bs = next_bs
                    continue
                raise

        return logits_out

    def score_text(
        self,
        text: str,
        chunk_tokens: int = 510,
        overlap: int = 64,
        max_chunks: int = 32,
        spread_threshold: float = 0.35,
    ) -> ChunkAggregationResult:
        """Tokenize, chunk, infer in fp16 batches, and aggregate into a calibrated probability."""
        if not self.is_loaded():
            self.load()

        return score_long_text(
            text=text,
            tokenizer=self.tokenizer,
            predict_logits_fn=self.predict_chunk_logits,
            chunk_tokens=chunk_tokens,
            overlap=overlap,
            max_chunks=max_chunks,
            spread_threshold=spread_threshold,
        )

