"""
AEGIS Debate & Arbitration Package.
Multi-agent arbitration, disagreement analysis, and court-admissible forensic reporting.
"""

from debate.arbitrator import JudgeArbitrator
from debate.claim_wrapper import (
    wrap_detector_response,
    wrap_video_detector_outputs,
)
from debate.disagreement import evaluate_disagreement, is_coverage_gap
from debate.judge_agent import JudgeAgent
from debate.judge_prompt import JUDGE_PROMPT_VERSION, build_judge_prompt
from debate.schemas import (
    AudioVisualMetrics,
    ClaimAdjudication,
    ClaimPolarity,
    CourtAdmissibleVerdict,
    CrossExaminationFinding,
    DebateRound,
    DisagreementAnalysis,
    DisagreementType,
    EvidenceDomain,
    ForensicClaim,
    JudgeReport,
    JudgeVerdictClass,
    OperatingConditions,
    PhysiologicalMetrics,
    SpatialMetrics,
)

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
    "CrossExaminationFinding",
    "DebateRound",
    "JudgeReport",
    "evaluate_disagreement",
    "is_coverage_gap",
    "JudgeArbitrator",
    "JudgeAgent",
    "wrap_detector_response",
    "wrap_video_detector_outputs",
    "build_judge_prompt",
    "JUDGE_PROMPT_VERSION",
]
