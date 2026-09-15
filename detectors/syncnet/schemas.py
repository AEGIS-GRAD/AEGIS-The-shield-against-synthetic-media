"""
Pydantic schemas for SyncNet microservice API contracts.
Strictly conforms to shared/json-api-contracts-schema/ schemas.
"""
from __future__ import annotations

from typing import List, Optional, Literal
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


class Evidence(BaseModel):
    claim: str = Field(
        ...,
        description="A human-readable claim regarding audio-visual synchronization."
    )
    flags: Optional[List[str]] = Field(
        default=None,
        description="Specific heuristic flags triggered (e.g. ['sync_offset_detected', 'not_applicable'])."
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
