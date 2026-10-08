"""
planner.py — LLM-driven planning integration with rule-based fallback (Task 1)
=============================================================================
Integrates the LLM-driven planner into the live AEGIS orchestrator pipeline,
switchable between rule-based and LLM-driven planning modes via configuration.

Modes:
- "llm" (default): Generates structured planning decisions using capability
  manifests, deterministic eligibility filtering, live telemetry grounding,
  and LLM inference. In case of LLM error, timeout, or schema invalidity,
  gracefully falls back to Month 1's rule-based baseline.
- "rule_based" / "rule": Runs the Month 1 deterministic rule-based baseline
  orchestrator (retained as control condition for RQ1 evaluations).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from models import InputMetadata
from rules import decide_detectors_to_call
from manifest_loader import load_all_manifests, ManifestError
from eligibility import filter_detectors, apply_telemetry_constraints
from prompt_builder import build_planning_prompt, PROMPT_VERSION
from telemetry_client import get_telemetry_snapshot, DetectorTelemetry

logger = logging.getLogger("aegis.orchestrator.planner")

# ---------------------------------------------------------------------------
# Configuration & Feature Flag
# ---------------------------------------------------------------------------
DEFAULT_PLANNER_MODE = os.environ.get("PLANNER_MODE", os.environ.get("AEGIS_PLANNER_MODE", "llm")).strip().lower()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_URL = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
PLANNER_MODELS = [
    os.environ.get("AEGIS_PLANNER_MODEL", "nvidia/nemotron-3.5-lightning:free"),
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "inclusionai/ling-3.0-flash-fin:free",
]
PLANNER_TIMEOUT_S = float(os.environ.get("AEGIS_PLANNER_TIMEOUT_S", "10.0"))
DEFAULT_COMPUTE_BUDGET_S = float(os.environ.get("AEGIS_DEFAULT_BUDGET_S", "15.0"))

REQUIRED_PLAN_KEYS: Set[str] = {
    "plan_version",
    "stages",
    "skipped",
    "coverage_warnings",
    "estimated_latency_s",
    "rationale",
}


@dataclass
class PlanningResult:
    detectors_to_call: List[str]
    plan: Optional[Dict[str, Any]] = None
    planner_mode: str = "llm"
    fallback: bool = False
    fallback_reason: Optional[str] = None
    model_used: Optional[str] = None
    planning_latency_s: float = 0.0
    eligible_detectors: List[str] = field(default_factory=list)
    excluded_detectors: List[Dict[str, Any]] = field(default_factory=list)


def resolve_planner_mode(mode_override: Optional[str] = None) -> str:
    """
    Resolves the effective planner mode ("llm" or "rule_based").
    Supports "llm", "rule", "rule_based", "baseline", "rules".
    """
    mode = (mode_override or os.environ.get("PLANNER_MODE", os.environ.get("AEGIS_PLANNER_MODE", DEFAULT_PLANNER_MODE))).strip().lower()
    if mode in ("rule", "rule_based", "rules", "baseline"):
        return "rule_based"
    return "llm"


def get_configured_planner_mode() -> str:
    """Returns the globally configured planner mode."""
    return resolve_planner_mode()


# ---------------------------------------------------------------------------
# LLM Calling & Plan Validation
# ---------------------------------------------------------------------------

def _simulate_reference_plan(
    eligible: List[dict],
    excluded: List[dict],
    telemetry: Optional[Dict[str, Any]] = None,
    budget_s: float = 15.0,
) -> Dict[str, Any]:
    """
    Deterministic reference planning engine for mock / offline environments.
    Adheres strictly to the prompt schema and selection guidance.
    """
    eligible_names = [m["detector_name"] for m in eligible]
    skipped: List[Dict[str, str]] = []
    coverage_warnings: List[str] = []
    run_detectors: List[str] = []

    # Check for degraded detectors in telemetry
    total_latency = 0.0
    for m in eligible:
        name = m["detector_name"]
        tel = telemetry.get(name) if telemetry else None
        status = getattr(tel, "status", None) if tel else None
        p95 = getattr(tel, "p95_latency_ms", None) if tel else None
        latency_s = (p95 / 1000.0) if p95 else 5.0

        if status == "degraded" and (total_latency + latency_s > budget_s):
            skipped.append({
                "detector_name": name,
                "reason": f"live telemetry indicates latency degradation ({latency_s:.1f}s p95); deprioritized to preserve budget"
            })
            coverage_warnings.append(f"{name} deprioritized due to real-time latency degradation.")
        elif total_latency + latency_s <= budget_s or not run_detectors:
            run_detectors.append(name)
            total_latency += latency_s
        else:
            skipped.append({
                "detector_name": name,
                "reason": f"skipped to remain within budget ceiling of {budget_s}s"
            })

    # Record excluded reasons in coverage warnings if no video or audio
    for exc in excluded:
        det = exc.get("detector_name")
        reason = exc.get("reason", "")
        if "audio" in reason.lower():
            coverage_warnings.append(f"No audio track present; {det} excluded.")

    return {
        "plan_version": "3",
        "stages": [{"stage": 1, "run": run_detectors, "mode": "parallel"}] if run_detectors else [],
        "skipped": skipped,
        "coverage_warnings": coverage_warnings,
        "estimated_latency_s": round(total_latency, 2),
        "rationale": f"Selected {run_detectors} from eligible set based on budget and system load.",
    }


def call_llm(
    prompt: str,
    mock: bool = False,
    mock_plan: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], str, float]:
    """
    Invokes the LLM via OpenRouter API. If mock is True, returns simulated plan.
    Returns (parsed_plan_dict_or_None, model_or_error_str, latency_seconds).
    """
    if mock:
        t0 = time.time()
        return mock_plan or {}, "deterministic-reference-planner (mock)", round(time.time() - t0, 3)

    api_key = os.environ.get("OPENROUTER_API_KEY", OPENROUTER_API_KEY)
    if not api_key:
        # Check if offline mock mode is explicitly requested
        if os.environ.get("AEGIS_MOCK_LLM", "").lower() in ("1", "true", "yes"):
            t0 = time.time()
            return mock_plan or {}, "deterministic-reference-planner (mock-env)", round(time.time() - t0, 3)
        return None, "NO_API_KEY_SET", 0.0

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/AEGIS-GRAD/AEGIS-The-shield-against-synthetic-media",
        "X-Title": "AEGIS Orchestrator LLM Planner",
    }

    t0 = time.time()
    for model_name in PLANNER_MODELS:
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=PLANNER_TIMEOUT_S,
            )
            latency = time.time() - t0
            if resp.status_code != 200:
                logger.warning(f"OpenRouter model {model_name} returned HTTP {resp.status_code}")
                continue

            raw = resp.json()["choices"][0]["message"]["content"].strip()
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            parsed = json.loads(raw)
            return parsed, model_name, round(latency, 3)
        except Exception as exc:
            logger.warning(f"LLM request attempt failed for model {model_name}: {exc}")
            continue

    return None, "ALL_MODELS_FAILED", round(time.time() - t0, 3)


def validate_plan(plan: Optional[Dict[str, Any]], eligible_ids: Set[str], budget_s: float) -> List[str]:
    """
    Validates a generated plan against the plan schema, eligibility safety,
    and compute budget constraints. Returns a list of validation issues.
    """
    problems: List[str] = []
    if plan is None or not isinstance(plan, dict):
        return ["plan is None or not a dict"]

    missing_keys = REQUIRED_PLAN_KEYS - plan.keys()
    if missing_keys:
        problems.append(f"missing schema keys: {sorted(missing_keys)}")

    stages = plan.get("stages")
    if not isinstance(stages, list):
        problems.append("stages must be a list")
    else:
        used_ids: Set[str] = set()
        for idx, stage in enumerate(stages):
            if not isinstance(stage, dict):
                problems.append(f"stage #{idx} is not an object")
                continue
            run_list = stage.get("run")
            if not isinstance(run_list, list):
                problems.append(f"stage #{idx} 'run' field is not a list")
                continue
            for det in run_list:
                if not isinstance(det, str):
                    problems.append(f"stage #{idx} contains non-string detector identifier")
                else:
                    used_ids.add(det)

        invented_or_ineligible = used_ids - eligible_ids
        if invented_or_ineligible:
            problems.append(f"used ineligible or non-existent detector ids: {sorted(invented_or_ineligible)}")

    est = plan.get("estimated_latency_s")
    if est is not None and isinstance(est, (int, float)) and est > budget_s:
        problems.append(f"estimated_latency_s ({est}s) exceeds budget ceiling ({budget_s}s)")

    return problems


# ---------------------------------------------------------------------------
# Core Planning Pipeline
# ---------------------------------------------------------------------------

def plan_detectors(
    metadata: InputMetadata,
    mode: Optional[str] = None,
    risk_profile: str = "standard",
    budget_s: Optional[float] = None,
    mock_llm: bool = False,
) -> PlanningResult:
    """
    Executes the planning phase for an incoming media request.

    Depending on the resolved mode ("rule_based" or "llm"), this calls either
    the Month 1 rule-based baseline or the LLM-driven planner with automatic
    fallback to the baseline on error.
    """
    effective_mode = resolve_planner_mode(mode)
    compute_budget = budget_s if budget_s is not None else DEFAULT_COMPUTE_BUDGET_S

    # 1. Control Condition: Explicit Rule-Based Planning Mode
    if effective_mode == "rule_based":
        logger.info(f"Executing Rule-Based Baseline Orchestrator for {metadata.filename}")
        rule_detectors = decide_detectors_to_call(metadata)
        return PlanningResult(
            detectors_to_call=rule_detectors,
            plan=None,
            planner_mode="rule_based",
            fallback=False,
            fallback_reason=None,
            model_used=None,
            planning_latency_s=0.0,
            eligible_detectors=rule_detectors,
        )

    # 2. LLM-Driven Planning Mode
    logger.info(f"Executing LLM-Driven Planner for {metadata.filename} (budget={compute_budget}s, risk={risk_profile})")
    start_time = time.time()

    # Step A: Load manifests
    try:
        manifests = load_all_manifests()
    except Exception as exc:
        logger.error(f"Failed to load capability manifests: {exc}. Falling back to rule-based baseline.")
        rule_fallback = decide_detectors_to_call(metadata)
        return PlanningResult(
            detectors_to_call=rule_fallback,
            plan=None,
            planner_mode="llm",
            fallback=True,
            fallback_reason=f"Manifest load error: {exc}",
            planning_latency_s=round(time.time() - start_time, 3),
        )

    # Step B: Input summary & deterministic eligibility filtering
    input_summary: Dict[str, Any] = {
        "modality": metadata.modality,
        "has_audio": metadata.has_audio,
        "duration_seconds": metadata.duration_seconds,
    }
    if metadata.resolution:
        input_summary["resolution"] = metadata.resolution

    eligible, excluded = filter_detectors(manifests, input_summary)

    # Step C: Live telemetry grounding & down-detector constraints
    telemetry: Optional[Dict[str, DetectorTelemetry]] = None
    try:
        telemetry = get_telemetry_snapshot()
        eligible, excluded = apply_telemetry_constraints(eligible, excluded, telemetry)
    except Exception as tel_exc:
        logger.warning(f"Telemetry retrieval warning: {tel_exc}. Proceeding with static eligibility.")

    eligible_ids = {m["detector_name"] for m in eligible}
    eligible_names = sorted(eligible_ids)

    # Step D: Build prompt
    prompt = build_planning_prompt(
        eligible=eligible,
        excluded=excluded,
        input_summary=input_summary,
        risk_profile=risk_profile,
        budget_s=compute_budget,
        telemetry=telemetry,
    )

    # Step E: Call LLM
    reference_mock_plan = _simulate_reference_plan(eligible, excluded, telemetry, compute_budget)
    plan, model_or_err, llm_latency = call_llm(
        prompt=prompt,
        mock=mock_llm,
        mock_plan=reference_mock_plan,
    )

    # Step F: Validate plan & execute fallback if invalid or failed
    validation_problems = validate_plan(plan, eligible_ids, compute_budget) if plan else [f"LLM call failed: {model_or_err}"]

    if validation_problems:
        logger.warning(f"LLM plan invalid or failed ({validation_problems}). Falling back to rule-based baseline.")
        rule_fallback = decide_detectors_to_call(metadata)
        fallback_plan = {
            "plan_version": "fallback-rule-baseline",
            "stages": [{"stage": 1, "run": rule_fallback, "mode": "parallel"}],
            "skipped": excluded,
            "coverage_warnings": [f"Fallback triggered: {'; '.join(validation_problems)}"],
            "estimated_latency_s": None,
            "rationale": f"Automatic fallback to Month 1 rule-based baseline due to: {'; '.join(validation_problems)}",
        }
        return PlanningResult(
            detectors_to_call=rule_fallback,
            plan=fallback_plan,
            planner_mode="llm",
            fallback=True,
            fallback_reason="; ".join(validation_problems),
            model_used=model_or_err,
            planning_latency_s=round(time.time() - start_time, 3),
            eligible_detectors=eligible_names,
            excluded_detectors=excluded,
        )

    # Step G: Extract detectors scheduled to run in plan
    detectors_to_call: List[str] = []
    for stage in plan.get("stages", []):
        for det in stage.get("run", []):
            if det not in detectors_to_call and det in eligible_ids:
                detectors_to_call.append(det)

    total_latency = round(time.time() - start_time, 3)
    logger.info(f"LLM Planner successfully generated plan using {model_or_err}: {detectors_to_call} ({total_latency}s)")

    return PlanningResult(
        detectors_to_call=detectors_to_call,
        plan=plan,
        planner_mode="llm",
        fallback=False,
        fallback_reason=None,
        model_used=model_or_err,
        planning_latency_s=total_latency,
        eligible_detectors=eligible_names,
        excluded_detectors=excluded,
    )
