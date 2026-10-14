"""
AEGIS Debate & Arbitration Package.
Multi-agent arbitration, disagreement analysis, and court-admissible forensic reporting.
"""

from debate.schemas import (
    EvidenceDomain,
    ClaimPolarity,
    ForensicClaim,
    DisagreementType,
    DisagreementAnalysis,
    JudgeVerdictClass,
    CourtAdmissibleVerdict,
    ClaimAdjudication,
    OperatingConditions,
    SpatialMetrics,
    PhysiologicalMetrics,
    AudioVisualMetrics,
)
from debate.disagreement import evaluate_disagreement, is_coverage_gap
from debate.arbitrator import JudgeArbitrator

__all__ = [
    "EvidenceDomain",
    "ClaimPolarity",
    "ForensicClaim",
    "DisagreementType",
    "DisagreementAnalysis",
    "JudgeVerdictClass",
    "CourtAdmissibleVerdict",
    "ClaimAdjudication",
    "OperatingConditions",
    "SpatialMetrics",
    "PhysiologicalMetrics",
    "AudioVisualMetrics",
    "evaluate_disagreement",
    "is_coverage_gap",
    "JudgeArbitrator",
]
