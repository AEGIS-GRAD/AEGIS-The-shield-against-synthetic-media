from pydantic import BaseModel, Field
from typing import Optional, List
from typing import Optional, List, Any, Dict



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
    planner_mode: Optional[str] = "rule_based"
    plan: Optional[dict] = None
    fallback: Optional[bool] = False
    fallback_reason: Optional[str] = None

    # ── NEW: Judge-Agent fields ──────────────────────────────────────────────
    judge_verdict: Optional[str] = None            # JudgeVerdictClass string value
    judge_score: Optional[float] = None            # calibrated score from CourtAdmissibleVerdict
    judge_mode: Optional[str] = None               # "expert_deterministic_judge" | "llm_agentic_judge"
    siem_alert_tier: Optional[str] = None          # "P1_CRITICAL" | "P2_ELEVATED" | "P4_INFORMATIONAL"
    debate_transcript: Optional[List[Dict[str, Any]]] = None  # list of DebateRound.model_dump()
    forensic_justification: Optional[str] = None
    debate_transcript_hash: Optional[str] = None
    guards_applied: Optional[List[str]] = None
    cross_examination_findings: Optional[List[Dict[str, Any]]] = None
    adjudication_latency_ms: Optional[float] = None