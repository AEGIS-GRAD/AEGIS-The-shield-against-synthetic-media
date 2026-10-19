"""
judge_bridge.py — Adapter between orchestrator DetectorResult and the debate JudgeAgent.
========================================================================================
Translates the orchestrator's flat List[DetectorResult] into the raw_responses dict
expected by debate.JudgeAgent.judge_file(), then returns a JudgeReport.
This is the ONLY file in orchestrator/ that imports from the debate package.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from models import DetectorResult, InputMetadata

# ---------------------------------------------------------------------------
# Ensure debate package is importable.
# Docker: PYTHONPATH=/app/app:/repo, debate mounted at /repo/debate — no sys.path needed.
# Local dev: __file__ is .../orchestrator/app/judge_bridge.py → parent×3 = repo root.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# Also honour entries already on PYTHONPATH (set by Docker / CI environment)
for _p in os.environ.get("PYTHONPATH", "").split(os.pathsep):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)


from debate.judge_agent import JudgeAgent
from debate.schemas import JudgeReport, OperatingConditions

logger = logging.getLogger("aegis.orchestrator.judge_bridge")

# Module-level singleton — JudgeAgent is stateless after __init__ (manifests are cached).
# Mode is read from env var AEGIS_JUDGE_MODE (default: "deterministic").
_JUDGE_MODE = os.environ.get("AEGIS_JUDGE_MODE", "deterministic")
_judge: Optional[JudgeAgent] = None


def _get_judge() -> JudgeAgent:
    global _judge
    if _judge is None:
        _judge = JudgeAgent(mode=_JUDGE_MODE)
        logger.info(f"JudgeAgent singleton initialised (mode={_JUDGE_MODE})")
    return _judge


def build_raw_responses(results: List[DetectorResult]) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Converts List[DetectorResult] into the raw_responses dict that
    debate.claim_wrapper.wrap_video_detector_outputs() expects.

    The debate layer only has adapters for the three video-modal detectors.
    Audio-only detectors (e.g. 'aasist') are silently skipped here — they still
    appear in raw_results on the OrchestrationResponse but are not passed to the
    JudgeAgent which would raise ValueError for unknown detector IDs.
    """
    # Detectors the debate/claim_wrapper layer knows how to handle.
    # Any detector NOT in this set is excluded from the judge's input.
    DEBATE_KNOWN_DETECTORS = {"video-classifier", "rppg", "syncnet"}

    raw: Dict[str, Optional[Dict[str, Any]]] = {}
    for r in results:
        if r.detector not in DEBATE_KNOWN_DETECTORS:
            logger.debug(
                f"Detector '{r.detector}' has no debate adapter — excluded from JudgeAgent input "
                f"(still present in raw_results on the OrchestrationResponse)."
            )
            continue
        if r.status != "ok" or r.confidence is None:
            raw[r.detector] = None
            continue
        entry: Dict[str, Any] = {
            "job_id": r.job_id,
            "confidence": r.confidence,
            "raw_score": r.raw_score,
            "latency_ms": r.latency_ms,
            "model_version": r.model_version or "unknown-v0",
            "evidence": {
                "claim": r.evidence.claim if r.evidence else "",
                "flags": r.evidence.flags if r.evidence else [],
            },
        }
        # rPPG contract: claim_wrapper reads `score` (= P(synthetic)), NOT `confidence`
        # (which in real rPPG responses means signal quality, not fake-probability).
        # raw_score IS P(synthetic) in DetectorResult, so we expose it as `score` here
        # to satisfy the debate layer's expected schema and suppress the legacy-fallback warning.
        if r.detector == "rppg":

            entry["score"] = r.raw_score  # P(synthetic) — what claim_wrapper._adapt_rppg() reads
        raw[r.detector] = entry
    return raw


def build_operating_conditions(metadata: InputMetadata) -> OperatingConditions:
    """
    Derives OperatingConditions from InputMetadata for the JudgeAgent.
    """
    return OperatingConditions(
        duration_seconds=metadata.duration_seconds,
        audio_present=metadata.has_audio,
        # mean_luminance and face_detected are not available from metadata alone;
        # they can be enriched later by detector evidence flags.
        mean_luminance=None,
        face_detected=True,
    )


def run_judge(
    results: List[DetectorResult],
    metadata: InputMetadata,
    job_id: str,
) -> JudgeReport:
    """
    Main entry point called by main.py.
    Returns a full JudgeReport (3-round debate transcript + CourtAdmissibleVerdict).
    """
    judge = _get_judge()
    raw_responses = build_raw_responses(results)
    conditions = build_operating_conditions(metadata)

    logger.info(f"[{job_id}] Invoking JudgeAgent (mode={_JUDGE_MODE}) on {len(results)} detector results")
    report: JudgeReport = judge.judge_file(
        raw_responses=raw_responses,
        conditions=conditions,
        job_id=job_id,
    )
    logger.info(
        f"[{job_id}] JudgeAgent verdict: {report.verdict.final_verdict.value} "
        f"(score={report.verdict.calibrated_score:.4f}, "
        f"mode={report.verdict.arbitration_mode}, "
        f"latency={report.adjudication_latency_ms:.1f}ms)"
    )
    return report
