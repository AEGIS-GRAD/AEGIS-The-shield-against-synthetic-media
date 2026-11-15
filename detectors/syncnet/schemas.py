"""
Pydantic schemas for SyncNet microservice API contracts.
Strictly conforms to shared/json-api-contracts-schema/ schemas.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, field_validator


class DetectorRequest(BaseModel):
    job_id: str = Field(
        ...,
        description="Unique UUID for tracing the request across the debate loop."
    )
    modality: Literal["audio", "video", "image", "text"] = Field(
        ...,
        description="The modality of the media."
    )
    payload: str = Field(
        ...,
        min_length=1,
        description="The Base64 encoded string of the media file, OR an absolute internal file path."
    )

    @field_validator("modality")
    @classmethod
    def validate_modality(cls, v: str) -> str:
        if v != "video":
            raise ValueError(f"SyncNet detector only processes 'video' modality, got: {v}")
        return v


class DubbingMetadata(BaseModel):
    """
    Dubbing-awareness step results written into the SyncNet Evidence.
    The downstream judge and arbitrator can read these fields to understand
    whether SyncNet's confidence was adjusted due to suspected dubbing.
    """
    is_dubbed: bool = Field(
        ...,
        description="Whether the content is likely dubbed (audio in different language).",
    )
    dubbing_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in the is_dubbed conclusion.",
    )
    language_mismatch_prob: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Estimated probability that audio and visual lip movements are in different languages.",
    )
    discount_factor: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Multiplier applied to SyncNet raw confidence. "
            "1.0 = no adjustment; <1.0 = confidence reduced due to dubbing."
        ),
    )
    raw_syncnet_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="SyncNet confidence BEFORE the dubbing discount was applied.",
    )
    backend_used: str = Field(
        default="heuristic",
        description="Dubbing-awareness backend: 'heuristic' | 'manifest_lookup'.",
    )
    extra: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extra metadata (dub_language, source, etc.).",
    )


class Evidence(BaseModel):
    claim: str = Field(
        ...,
        description="A human-readable claim regarding audio-visual synchronization."
    )
    flags: Optional[List[str]] = Field(
        default=None,
        description="Specific heuristic flags triggered (e.g. ['sync_offset_detected', 'not_applicable'])."
    )
    dubbing_metadata: Optional[DubbingMetadata] = Field(
        default=None,
        description=(
            "Dubbing-awareness assessment. "
            "If is_dubbed is True, the confidence was down-weighted by discount_factor. "
            "Downstream judge/arbitrator should weight the SyncNet claim accordingly."
        ),
    )


class DetectorResponse(BaseModel):
    job_id: str = Field(
        ...,
        description="The exact UUID provided in the Request."
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalized confidence score. 0.0 = Authentic, 1.0 = Synthetic/Deepfake."
    )
    raw_score: float = Field(
        ...,
        description="Unnormalized logit or raw score from the PyTorch model."
    )
    latency_ms: int = Field(
        ...,
        ge=0,
        description="Exact time in milliseconds the inference took."
    )
    ram_usage_mb: Optional[float] = Field(
        default=None,
        description="Peak system RAM consumed in Megabytes."
    )
    vram_usage_mb: Optional[float] = Field(
        default=None,
        description="Peak GPU VRAM consumed in Megabytes."
    )
    model_version: str = Field(
        default="syncnet-v1.3",
        description="The version of the detector."
    )
    evidence: Evidence = Field(
        ...,
        description="Contextual reasoning for the Debate Agent."
    )


class HealthResponse(BaseModel):
    status: str = Field(default="healthy")
    service: str = Field(default="syncnet")
    model_loaded: bool = Field(...)
    model_version: str = Field(default="syncnet-v1.3")
    device: str = Field(...)
