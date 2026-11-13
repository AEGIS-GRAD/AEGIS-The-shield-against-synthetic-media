"""Pydantic schemas aligned with shared/json-api-contracts-schema/."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class DetectionRequest(BaseModel):
    """Canonical detector request conforming to detector_request.schema.json."""

    job_id: str = Field(..., min_length=1, description="Unique orchestrator job identifier.")
    modality: Literal["audio", "video", "image", "text"] = Field(
        ..., description="Media modality; only 'text' is processed by this detector."
    )
    payload: str = Field(
        ..., min_length=1, description="Base64-encoded UTF-8 text or path inside /shared_volume/."
    )


class LegacyTextRequest(BaseModel):
    """Deprecated raw-text payload kept solely for backwards-compatible `/analyze` callers."""

    text: str = Field(..., min_length=1)


class DetectionEvidence(BaseModel):
    """Structured claim and flag summary inside detector_response.schema.json."""

    claim: str = Field(..., min_length=1, max_length=512)
    flags: List[str] = Field(default_factory=list)


class DetectionResponse(BaseModel):
    """Canonical detector response conforming to detector_response.schema.json."""

    job_id: str
    status: Literal["ok", "not_applicable", "error"] = "ok"
    modality: Literal["text"] = "text"
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="0.0 = Authentic human, 1.0 = Synthetic LLM."
    )
    raw_score: float = Field(
        ..., description="Primary detector score prior to length-attenuation calibration."
    )
    latency_ms: int = Field(..., ge=0)
    ram_usage_mb: Optional[float] = Field(default=None, ge=0.0)
    vram_usage_mb: Optional[float] = Field(default=None, ge=0.0)
    model_version: str
    evidence: DetectionEvidence
    signals: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
