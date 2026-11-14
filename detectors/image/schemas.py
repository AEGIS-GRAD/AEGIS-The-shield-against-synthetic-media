"""
Pydantic v2 schemas for image detector microservice.
Strictly conforms to shared/json-api-contracts-schema/SCHEMA.md
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator


class DetectorRequest(BaseModel):
    job_id: str = Field(..., description="Unique UUID for tracing request across debate loop.")
    modality: Literal["audio", "video", "image", "text"] = Field(
        ..., description="The modality of the media."
    )
    payload: str = Field(
        ...,
        min_length=1,
        description="Base64-encoded image bytes OR an absolute internal file path."
    )

    @field_validator("modality")
    @classmethod
    def validate_modality(cls, v: str) -> str:
        if v != "image":
            raise ValueError(f"Image detector only processes 'image' modality, got: {v}")
        return v


class Evidence(BaseModel):
    claim: str = Field(..., description="Human-readable verdict on image authenticity.")
    flags: Optional[List[str]] = Field(
        default=None,
        description="Heuristic flags (e.g. ['frequency_anomaly', 'exif_missing'])."
    )


class DetectorResponse(BaseModel):
    job_id: str = Field(..., description="Echo of the request UUID.")
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Normalized confidence score: 0.0 = Authentic, 1.0 = Synthetic/Deepfake."
    )
    raw_score: float = Field(..., description="Pre-sigmoid logit from the model.")
    latency_ms: int = Field(..., ge=0, description="Inference time in milliseconds.")
    ram_usage_mb: Optional[float] = Field(default=None)
    vram_usage_mb: Optional[float] = Field(default=None)
    model_version: str = Field(default="commfor-model-384-fp16")
    evidence: Evidence = Field(..., description="Contextual reasoning for Debate Agent.")


class HealthResponse(BaseModel):
    status: str = Field(default="healthy")
    model_loaded: bool = Field(...)
    model_version: str = Field(default="commfor-model-384-fp16")
    device: str = Field(...)