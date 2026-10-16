"""
AEGIS Debate & Arbitration Protocol — Pydantic v2 Data Models.
Defines strict schemas for Forensic Claims, Disagreement Analysis, and Court-Admissible Verdicts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class EvidenceDomain(str, Enum):
    SPATIAL_PIXEL = "spatial_pixel"
    PHYSIOLOGICAL_BVP = "physiological_bvp"
    AUDIOVISUAL_SYNC = "audiovisual_sync"
    AUDIO_ACOUSTIC = "audio_acoustic"
    METADATA_INTEGRITY = "metadata_integrity"


class ClaimPolarity(str, Enum):
    AUTHENTIC = "AUTHENTIC"
    SYNTHETIC = "SYNTHETIC"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SpatialMetrics(BaseModel):
    sampled_frames: int = 10
    max_frame_anomaly: Optional[float] = None
    frame_variance: Optional[float] = None
    suspicious_frame_ratio: Optional[float] = None


class PhysiologicalMetrics(BaseModel):
    estimated_bpm: Optional[float] = None
    spectral_purity: Optional[float] = None
    skin_ratio: Optional[float] = None
    snr_db: Optional[float] = None


class AudioVisualMetrics(BaseModel):
    optimal_offset_frames: Optional[int] = None
    offset_ms: Optional[float] = None
    min_distance: Optional[float] = None
    sync_confidence: Optional[float] = None


class ObservationalMetrics(BaseModel):
    spatial: Optional[SpatialMetrics] = None
    physiological: Optional[PhysiologicalMetrics] = None
    audiovisual: Optional[AudioVisualMetrics] = None


class AttenuationFactors(BaseModel):
    luminance_factor: float = Field(default=1.0, ge=0.0, le=1.0)
    duration_factor: float = Field(default=1.0, ge=0.0, le=1.0)
    occlusion_factor: float = Field(default=1.0, ge=0.0, le=1.0)
    compression_factor: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def composite_attenuation(self) -> float:
        """Computes minimum bounding attenuation multiplier."""
        return min(
            self.luminance_factor,
            self.duration_factor,
            self.occlusion_factor,
            self.compression_factor,
        )


class OperatingConditions(BaseModel):
    duration_seconds: Optional[float] = None
    mean_luminance: Optional[float] = None
    face_detected: bool = True
    audio_present: bool = True


class ForensicClaim(BaseModel):
    claim_id: Optional[str] = None
    job_id: str
    detector_id: str
    model_version: str
    domain: EvidenceDomain
    polarity: ClaimPolarity
    confidence: float = Field(..., ge=0.0, le=1.0)
    raw_score: Optional[float] = None
    claim: str
    flags: List[str] = Field(default_factory=list)
    observational_metrics: Optional[ObservationalMetrics] = None
    attenuation_factors: AttenuationFactors = Field(default_factory=AttenuationFactors)
    operating_conditions: Optional[OperatingConditions] = None
    coverage_gap: bool = False
    evidence_hash: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def effective_confidence(self) -> float:
        """Returns confidence calibrated by environmental attenuation factors."""
        if self.polarity in (ClaimPolarity.NOT_APPLICABLE, ClaimPolarity.INCONCLUSIVE):
            return 0.5
        # Scale divergence from neutral 0.5 by composite attenuation
        deviation = self.confidence - 0.5
        attenuated_deviation = deviation * self.attenuation_factors.composite_attenuation
        return round(0.5 + attenuated_deviation, 4)


class DisagreementType(str, Enum):
    CONSENSUS = "CONSENSUS"
    POLARITY_INVERSION = "POLARITY_INVERSION"
    CONFIDENCE_SPREAD = "CONFIDENCE_SPREAD"
    HEURISTIC_COLLISION = "HEURISTIC_COLLISION"
    COVERAGE_GAP_ONLY = "COVERAGE_GAP_ONLY"


class DisagreementAnalysis(BaseModel):
    requires_arbitration: bool
    primary_disagreement_type: DisagreementType
    confidence_spread: float
    max_confidence: float
    min_confidence: float
    conflicting_detectors: List[str] = Field(default_factory=list)
    coverage_gaps: List[str] = Field(default_factory=list)
    conflict_summary: str


class JudgeVerdictClass(str, Enum):
    AUTHENTIC = "AUTHENTIC"
    SYNTHETIC = "SYNTHETIC"
    INTEGRITY_UNKNOWN = "INTEGRITY_UNKNOWN"


class ClaimAdjudication(BaseModel):
    detector_id: str
    original_polarity: ClaimPolarity
    original_confidence: float
    accepted_confidence: float
    weight_assigned: float
    discount_reason: Optional[str] = None
    findings_retained: List[str] = Field(default_factory=list)


class CourtAdmissibleVerdict(BaseModel):
    verdict_id: str
    job_id: str
    final_verdict: JudgeVerdictClass
    calibrated_score: float = Field(..., ge=0.0, le=1.0)
    confidence_interval: List[float] = Field(default_factory=lambda: [0.0, 1.0])
    arbitration_mode: str  # "consensus_fast_path" | "expert_deterministic_judge" | "llm_agentic_judge"
    adjudications: List[ClaimAdjudication] = Field(default_factory=list)
    forensic_justification: str
    coverage_warnings: List[str] = Field(default_factory=list)
    siem_alert_tier: str  # "P1_CRITICAL" | "P2_ELEVATED" | "P4_INFORMATIONAL"
    evidence_manifest_hash: str  # SHA-256 digest of all considered inputs & claims
    signed_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CrossExaminationFinding(BaseModel):
    detector_id: str
    check_category: str  # "operating_constraint" | "known_failure_mode" | "borderline_dropped" | "coverage_gap"
    severity: str  # "HIGH" | "MEDIUM" | "LOW" | "INFO"
    finding: str
    rule_reference: Optional[str] = None
    source: str  # "capability_manifest" | "limitations_doc" | "operating_conditions" | "guardrail"


class DebateRound(BaseModel):
    round_number: int
    round_name: str
    summary: str
    details: Dict[str, Any] = Field(default_factory=dict)


class JudgeReport(BaseModel):
    job_id: str
    verdict: CourtAdmissibleVerdict
    judge_mode: str  # "expert_deterministic_judge" | "llm_agentic_judge"
    rounds: List[DebateRound] = Field(default_factory=list)
    cross_examination_findings: List[CrossExaminationFinding] = Field(default_factory=list)
    guards_applied: List[str] = Field(default_factory=list)
    llm_model: Optional[str] = None
    llm_fallback_used: bool = False
    llm_fallback_reason: Optional[str] = None
    prompt_version: Optional[str] = None
    debate_transcript_hash: str
    adjudication_latency_ms: float
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
