"""AEGIS Adversarial Robustness v2: Adaptive Black-Box, Agentic Text, Hard-Negatives & Re-Test."""

from eval.adaptive_robustness.detectors import (
    AdaptiveTarget,
    HTTPDetectorTarget,
    HardenedTextDefense,
    HardenedVisionDefense,
    LocalImageFrameTarget,
    LocalTextForensicTarget,
    LocalVideoEfficientNetTarget,
    TargetScore,
)
from eval.adaptive_robustness.blackbox_evasion import (
    EvasionCurveRow,
    VisionEvasionTrace,
    run_adaptive_transform_attack,
    run_square_attack,
    summarize_vision_curves,
)
from eval.adaptive_robustness.agentic_text_paraphraser import (
    AdaptiveHeuristicParaphraser,
    OpenRouterParaphraser,
    TextEvasionTrace,
    TextTurnRecord,
    run_agentic_text_evasion,
    summarize_text_curves,
)
from eval.adaptive_robustness.hard_negatives import export_hard_negatives

__all__ = [
    "AdaptiveHeuristicParaphraser",
    "AdaptiveTarget",
    "EvasionCurveRow",
    "HTTPDetectorTarget",
    "HardenedTextDefense",
    "HardenedVisionDefense",
    "LocalImageFrameTarget",
    "LocalTextForensicTarget",
    "LocalVideoEfficientNetTarget",
    "OpenRouterParaphraser",
    "TargetScore",
    "TextEvasionTrace",
    "TextTurnRecord",
    "VisionEvasionTrace",
    "export_hard_negatives",
    "run_adaptive_transform_attack",
    "run_agentic_text_evasion",
    "run_square_attack",
    "summarize_text_curves",
    "summarize_vision_curves",
]
