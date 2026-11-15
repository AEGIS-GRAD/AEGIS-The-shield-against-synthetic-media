"""
Pydantic schemas for AASIST microservice API contracts.
Strictly conforms to shared/json-api-contracts-schema/ schemas.
"""

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
        if v not in ("audio", "video"):
            raise ValueError(f"AASIST detector processes 'audio' and 'video' modalities, got: {v}")
        return v


class VADMetadata(BaseModel):
    """
    Voice-Activity Detection pre-filter results.
    Written into the Evidence object so the debate Judge and Arbitrator can
    see and reason about the VAD decision.
    """
    speech_activity: str = Field(
        ...,
        description="VAD classification: 'speech' | 'non_speech' | 'uncertain'."
    )
    speech_ratio: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction [0, 1] of analysis windows classified as containing speech.",
    )
    vad_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in the VAD classification.",
    )
    backend_used: str = Field(
        default="heuristic",
        description="VAD backend: 'silero' | 'heuristic'.",
    )
    speech_threshold: float = Field(
        default=0.35,
        description="Speech-fraction threshold applied during VAD.",
    )


class Evidence(BaseModel):
    claim: str = Field(
        ...,
        description="A human-readable claim regarding audio authenticity."
    )
    flags: Optional[List[str]] = Field(
        default=None,
        description="Specific heuristic flags triggered (e.g. ['voice_cloning_detected', 'high_spoof_confidence'])."
    )
    vad_metadata: Optional[VADMetadata] = Field(
        default=None,
        description=(
            "Voice-activity detection pre-filter result. "
            "If speech_activity == 'non_speech', the AASIST verdict is not_applicable. "
            "Downstream judge/arbitrator MUST treat the claim as a coverage gap."
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
        default="aasist-v1.0",
        description="The version of the detector."
    )
    evidence: Evidence = Field(
        ...,
        description="Contextual reasoning for the Debate Agent."
    )


class HealthResponse(BaseModel):
    status: str = Field(default="healthy")
    model_loaded: bool = Field(...)
    model_version: str = Field(default="aasist-v1.0")
    device: str = Field(...)
