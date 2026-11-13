"""Runtime configuration for the AEGIS text detector microservice."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_SERVICE_DIR = Path(__file__).resolve().parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw is not None and raw.strip() else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw is not None and raw.strip() else default


@dataclass(frozen=True)
class SignalThresholds:
    """Calibrated thresholds derived from human baseline percentiles."""

    low_perplexity_threshold: float = 35.0
    high_perplexity_threshold: float = 160.0
    low_burstiness_cov_threshold: float = 0.35
    binoculars_threshold: float = 0.90
    source: str = "defaults"


@dataclass(frozen=True)
class TextDetectorConfig:
    """Immutable configuration resolved from environment variables."""

    service_name: str = "detector_text"
    model_name: str = "desklib/ai-text-detector-v1.01"
    model_version: str = "desklib-v1.01-fp16"
    model_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("AEGIS_TEXT_MODEL_DIR", str(_SERVICE_DIR / "models" / "desklib-base"))
        )
    )
    lora_dir: str = field(default_factory=lambda: os.getenv("AEGIS_TEXT_LORA_DIR", "").strip())
    ppl_model_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("AEGIS_TEXT_PPL_MODEL_DIR", str(_SERVICE_DIR / "models" / "gpt2"))
        )
    )
    ppl_model_id: str = field(
        default_factory=lambda: os.getenv("AEGIS_TEXT_PPL_MODEL_ID", "gpt2")
    )
    calibration_path: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "AEGIS_TEXT_CALIBRATION_PATH",
                str(_SERVICE_DIR / "models" / "signal_calibration.json"),
            )
        )
    )

    enable_ppl: bool = field(default_factory=lambda: _env_bool("AEGIS_TEXT_ENABLE_PPL", True))
    enable_binoculars: bool = field(
        default_factory=lambda: _env_bool("AEGIS_TEXT_ENABLE_BINOCULARS", False)
    )
    binoculars_performer_id: str = field(
        default_factory=lambda: os.getenv("AEGIS_TEXT_BINOCULARS_PERFORMER", "Qwen/Qwen2.5-0.5B")
    )
    binoculars_observer_id: str = field(
        default_factory=lambda: os.getenv(
            "AEGIS_TEXT_BINOCULARS_OBSERVER", "Qwen/Qwen2.5-0.5B-Instruct"
        )
    )
    binoculars_threshold_override: Optional[float] = field(
        default_factory=lambda: (
            float(os.environ["AEGIS_TEXT_BINOCULARS_THRESHOLD"])
            if os.getenv("AEGIS_TEXT_BINOCULARS_THRESHOLD", "").strip()
            else None
        )
    )

    use_fp16: bool = field(default_factory=lambda: _env_bool("AEGIS_TEXT_FP16", True))
    preload_models: bool = field(default_factory=lambda: _env_bool("AEGIS_TEXT_PRELOAD", True))
    min_words: int = field(default_factory=lambda: _env_int("AEGIS_TEXT_MIN_WORDS", 40))
    reliable_words: int = field(default_factory=lambda: _env_int("AEGIS_TEXT_RELIABLE_WORDS", 150))
    chunk_tokens: int = field(default_factory=lambda: _env_int("AEGIS_TEXT_CHUNK_TOKENS", 510))
    chunk_overlap: int = field(default_factory=lambda: _env_int("AEGIS_TEXT_CHUNK_OVERLAP", 64))
    max_chunks: int = field(default_factory=lambda: _env_int("AEGIS_TEXT_MAX_CHUNKS", 32))
    chunk_batch_size: int = field(default_factory=lambda: _env_int("AEGIS_TEXT_BATCH_SIZE", 4))
    max_chars: int = field(default_factory=lambda: _env_int("AEGIS_TEXT_MAX_CHARS", 200_000))
    max_ppl_sentences: int = field(
        default_factory=lambda: _env_int("AEGIS_TEXT_MAX_PPL_SENTENCES", 64)
    )

    shared_volume_root: Path = field(
        default_factory=lambda: Path(os.getenv("AEGIS_SHARED_VOLUME", "/shared_volume"))
    )
    internal_api_key: str = field(default_factory=lambda: os.getenv("INTERNAL_API_KEY", "").strip())
    mesh_strict: bool = field(default_factory=lambda: _env_bool("AEGIS_MESH_STRICT", False))
    artificial_delay_ms: int = field(
        default_factory=lambda: _env_int("AEGIS_ARTIFICIAL_DELAY_MS", 0)
    )
    chunk_disagreement_spread: float = field(
        default_factory=lambda: _env_float("AEGIS_TEXT_CHUNK_SPREAD_THRESHOLD", 0.35)
    )

    @property
    def effective_model_version(self) -> str:
        """Report whether weights are as-is baseline or a fine-tuned LoRA checkpoint."""
        if self.lora_dir:
            return f"desklib-v1.01-lora-{Path(self.lora_dir).name}"
        return self.model_version if self.use_fp16 else "desklib-v1.01-fp32"


def load_signal_thresholds(config: TextDetectorConfig) -> SignalThresholds:
    """Load calibrated human-percentile thresholds if present, else fall back to defaults."""
    defaults = SignalThresholds()
    data: dict = {}
    if config.calibration_path.exists():
        try:
            data = json.loads(config.calibration_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}

    bino_thresh = (
        config.binoculars_threshold_override
        if config.binoculars_threshold_override is not None
        else float(data.get("binoculars_threshold", defaults.binoculars_threshold))
    )
    return SignalThresholds(
        low_perplexity_threshold=float(
            data.get("low_perplexity_threshold", defaults.low_perplexity_threshold)
        ),
        high_perplexity_threshold=float(
            data.get("high_perplexity_threshold", defaults.high_perplexity_threshold)
        ),
        low_burstiness_cov_threshold=float(
            data.get("low_burstiness_cov_threshold", defaults.low_burstiness_cov_threshold)
        ),
        binoculars_threshold=bino_thresh,
        source=str(config.calibration_path) if data else defaults.source,
    )

