from pydantic import BaseModel, Field
from typing import Optional, List


class InputMetadata(BaseModel):
    filename: str
    modality: str  # "video" | "audio" | "image" | "text" | "unknown"
    has_audio: bool
    duration_seconds: float
    resolution: Optional[List[int]] = None  # [width, height] — List[int] serialises cleanly in JSON


class DetectorEvidence(BaseModel):
    claim: str
    flags: List[str] = []


class DetectorResult(BaseModel):
    detector: str
    status: str  # "ok" or "failed"

    job_id: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    raw_score: Optional[float] = None
    latency_ms: Optional[int] = None
    ram_usage_mb: Optional[float] = None
    vram_usage_mb: Optional[float] = None
    model_version: Optional[str] = None
    evidence: Optional[DetectorEvidence] = None
    error: Optional[str] = None


class OrchestrationResponse(BaseModel):
    input_file: str
    metadata: InputMetadata
    detectors_called: List[str]
    raw_results: List[DetectorResult]
    aggregated_score: Optional[float] = None
    aggregated_verdict: str