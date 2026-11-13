"""
Pydantic schemas for the Text Detector microservice.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class TextAnalysisRequest(BaseModel):
    text: str = Field(..., description="The input text to analyze for AI-generated artifacts")
    request_id: Optional[str] = Field(None, description="Optional tracking ID for tracing")
    include_stylometry: bool = Field(True, description="Whether to compute stylometry explainability features")

class StylometryMetrics(BaseModel):
    vocabulary_diversity: Dict[str, Any]
    ngram_repetition: Dict[str, Any]
    sentence_variation: Dict[str, Any]
    synthetic_indication_score: float
    stylometry_verdict: str
    summary: str

class TextAnalysisResponse(BaseModel):
    detector: str = "desklib_ai_text_detector"
    model_version: str = "v1.01"
    request_id: Optional[str] = None
    ai_score: float = Field(..., description="Probability of text being AI-generated (0.0 to 1.0)")
    human_score: float = Field(..., description="Probability of text being Human-written (0.0 to 1.0)")
    prediction: str = Field(..., description="'synthetic' or 'authentic'")
    confidence: float = Field(..., description="Confidence score")
    stylometry: Optional[StylometryMetrics] = None
    execution_time_ms: float = Field(..., description="Inference latency in milliseconds")


class DetectRequest(BaseModel):
    job_id: str
    modality: str
    payload: str


class DetectEvidence(BaseModel):
    claim: str
    flags: List[str] = Field(default_factory=list)


class DetectResponse(BaseModel):
    status: str = "ok"
    job_id: str
    confidence: float
    raw_score: float
    latency_ms: int
    model_version: str = "desklib-deberta-v1.01"
    evidence: DetectEvidence
    ram_usage_mb: Optional[float] = None
    vram_usage_mb: Optional[float] = None
