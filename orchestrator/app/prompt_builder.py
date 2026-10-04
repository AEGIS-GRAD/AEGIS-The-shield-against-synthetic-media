"""
Planning prompt builder — v3 (Grounding in Live Inference Telemetry)
=====================================================================
Integrates real-time Prometheus telemetry (latency, RAM, degradation ratio)
directly into the LLM planner's prompt context.

Key capabilities:
1. Live Telemetry Grounding: When live Prometheus telemetry is available, the
   prompt displays current p95/avg latency and flags "degraded" or "down" services.
2. Graceful Fallback: If Prometheus telemetry is offline or pending, the prompt
   automatically falls back to manifest values or Month 1 benchmark numbers with
   explicit source labelling.
3. Budget-Aware Reasoning: Guides the LLM to deprioritize, stage, or drop
   degraded detectors when system load threatens the latency budget.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

PROMPT_VERSION = "planner-v3.0"

# Fallback latency figures from eval/reports/week_benchmark_report.md
# (Month 1, 120-sample full-pipeline run), used only when live telemetry
# or manifest performance fields are pending.
BASELINE_LATENCY_MS = {
    "video-classifier": {"avg": 7028.6, "p95": 14961.0},
    "rppg": {"avg": 6607.7, "p95": 15850.0},
    "aasist": {"avg": 234.8, "p95": 334.0},
    "syncnet": {"avg": 9587.4, "p95": 22834.0},
}


def _latency_for(manifest: dict, telemetry: Optional[dict] = None) -> tuple[float, float, str]:
    """Resolves latency for a detector, prioritizing live telemetry -> manifest -> baseline."""
    name = manifest["detector_name"]

    # 1. Prioritize live Prometheus telemetry
    if telemetry and name in telemetry:
        tel = telemetry[name]
        source = getattr(tel, "source", None) or (tel.get("source") if isinstance(tel, dict) else None)
        status = getattr(tel, "status", None) or (tel.get("status") if isinstance(tel, dict) else None)
        p95 = getattr(tel, "p95_latency_ms", None) or (tel.get("p95_latency_ms") if isinstance(tel, dict) else None)
        avg = getattr(tel, "avg_latency_ms", None) or (tel.get("avg_latency_ms") if isinstance(tel, dict) else None)
        ratio = getattr(tel, "degradation_ratio", None) or (tel.get("degradation_ratio") if isinstance(tel, dict) else None)

        if source == "live_prometheus" and p95 is not None and avg is not None:
            if status == "degraded" and ratio:
                source_label = f"live Prometheus [DEGRADED: {ratio:.1f}x slower]"
            else:
                source_label = f"live Prometheus [{status or 'healthy'}]"
            return avg, p95, source_label

    # 2. Check manifest performance field
    perf = manifest.get("performance", {})
    if perf.get("avg_latency_ms") is not None and perf.get("p95_latency_ms") is not None:
        return perf["avg_latency_ms"], perf["p95_latency_ms"], "manifest"

    # 3. Fallback to Month 1 benchmark baseline
    if name in BASELINE_LATENCY_MS:
        b = BASELINE_LATENCY_MS[name]
        return b["avg"], b["p95"], "Month 1 benchmark fallback (live telemetry pending)"

    return None, None, "unknown"


def _format_failure_modes(manifest: dict) -> str:
    modes = manifest.get("known_failure_modes", [])
    if not modes:
        return "none documented"
    return "; ".join(f"{m['condition']} → {m['effect']}" for m in modes)


def _format_eligible_table(eligible: list[dict], telemetry: Optional[dict] = None) -> str:
    rows = []
    for m in eligible:
        avg_ms, p95_ms, source = _latency_for(m, telemetry)
        latency_str = (
            f"~{avg_ms/1000:.1f}s avg, {p95_ms/1000:.1f}s p95 (source: {source})"
            if avg_ms is not None
            else "unknown"
        )

        rows.append(
            f"- detector_name: {m['detector_name']}\n"
            f"  description: {m.get('description', '')}\n"
            f"  latency: {latency_str}\n"
            f"  known_failure_modes: {_format_failure_modes(m)}\n"
            f"  reliability_notes: {m.get('reliability_notes', '')}"
        )
    return "\n".join(rows) if rows else "(none eligible)"


def _format_excluded_table(excluded: list[dict]) -> str:
    if not excluded:
        return "(none excluded — all registered detectors are eligible for this input)"
    return "\n".join(f"- detector_name: {e['detector_name']}, reason: {e['reason']}" for e in excluded)


def _format_telemetry_section(telemetry: Optional[dict]) -> str:
    if not telemetry:
        return "(no live Prometheus telemetry available — relying on baseline performance benchmarks)"

    lines = []
    for name, tel in telemetry.items():
        status = getattr(tel, "status", None) or (tel.get("status") if isinstance(tel, dict) else "unknown")
        p95 = getattr(tel, "p95_latency_ms", None) or (tel.get("p95_latency_ms") if isinstance(tel, dict) else None)
        avg = getattr(tel, "avg_latency_ms", None) or (tel.get("avg_latency_ms") if isinstance(tel, dict) else None)
        source = getattr(tel, "source", None) or (tel.get("source") if isinstance(tel, dict) else "unknown")
        ratio = getattr(tel, "degradation_ratio", None) or (tel.get("degradation_ratio") if isinstance(tel, dict) else None)
        ram = getattr(tel, "ram_usage_mb", None) or (tel.get("ram_usage_mb") if isinstance(tel, dict) else None)
        calls = getattr(tel, "calls_count", 0) or (tel.get("calls_count", 0) if isinstance(tel, dict) else 0)

        p95_str = f"{p95/1000:.2f}s" if p95 else "unknown"
        avg_str = f"{avg/1000:.2f}s" if avg else "unknown"
        ram_str = f"{ram:.1f} MB" if ram else "unknown"
        ratio_str = f"{ratio:.2f}x" if ratio else "1.00x"

        lines.append(
            f"- detector: {name}\n"
            f"  status: {status.upper()} (degradation_ratio: {ratio_str})\n"
            f"  measured_latency: p95={p95_str}, avg={avg_str} (source: {source})\n"
            f"  system_load: RAM={ram_str}, calls_in_window={calls}"
        )
    return "\n".join(lines)


def build_planning_prompt(
    eligible: list[dict],
    excluded: list[dict],
    input_summary: dict,
    risk_profile: str,
    budget_s: float,
    telemetry: Optional[dict] = None,
) -> str:
    prompt = f"""# 1. ROLE AND OBJECTIVE
You are the planning component of a deepfake verification system (AEGIS).
Your job is to choose which detectors to run on a given input, and in what
stages, so the system gets the most reliable verdict possible within the
given compute budget.

# 2. HARD RULES
- You may ONLY choose detector_name values from the "ELIGIBLE DETECTORS" list below.
- NEVER invent a detector_name that is not listed.
- NEVER select a detector listed under "EXCLUDED DETECTORS".
- Your plan's estimated_latency_s MUST NOT exceed the compute_budget_s given below.
- Budget calculations MUST use the live latency figures specified in the
  telemetry table below whenever a detector is marked DEGRADED.
- Each eligible detector's "known_failure_modes" and "reliability_notes" are
  real documented weaknesses, not boilerplate — weigh them when the input
  summary suggests a failure condition applies.
- If no detector is eligible or fits the budget, return an empty "stages" list
  and explain why in "rationale" — do not force an infeasible selection.
- Output key names must match the schema EXACTLY, character-for-character.

# 3. INPUT SUMMARY
{json.dumps(input_summary, indent=2)}

# 4. REQUEST CONSTRAINTS
- risk_profile: {risk_profile}   (low = cost-sensitive, standard = balanced, high = missing a fake is costly — favor coverage)
- compute_budget_s: {budget_s}   (hard ceiling on total estimated latency for this run)

# 5. LIVE SYSTEM TELEMETRY (Prometheus Real-Time Load)
{_format_telemetry_section(telemetry)}

# 6. ELIGIBLE DETECTORS
{_format_eligible_table(eligible, telemetry)}

# 7. EXCLUDED DETECTORS
{_format_excluded_table(excluded)}

# 8. SELECTION GUIDANCE
- High risk_profile favors broader coverage over minimizing cost, but still
  must respect compute_budget_s.
- Telemetry & Load Adaptation: When a detector shows status "DEGRADED", its
  actual latency is elevated due to inference load. If including a degraded
  detector would breach compute_budget_s, drop it or defer it to a conditional
  second stage, and explicitly log this in "coverage_warnings" and "rationale".
- Tight budgets favor staging: run the fastest detector(s) first; only
  escalate to slower detectors in a later stage if the budget allows.
- If the input summary matches a detector's known_failure_modes, treat that
  detector as low-value evidence — either skip it and say why, or note the
  caveat in coverage_warnings.

# 9. OUTPUT SCHEMA
Respond with JSON ONLY. No markdown fences, no commentary outside the JSON.
{{
  "plan_version": "3",
  "stages": [
    {{"stage": 1, "run": ["<detector_name>", "..."], "mode": "parallel"}}
  ],
  "skipped": [
    {{"detector_name": "<name>", "reason": "<why not used, if eligible but not chosen>"}}
  ],
  "coverage_warnings": ["<string>", "..."],
  "estimated_latency_s": <number>,
  "rationale": "<short explanation of the choice>"
}}

# 10. FEW-SHOT EXAMPLES

Example A — video with audio, standard risk, generous budget, good conditions:
Input: {{"modality": "video", "has_audio": true, "duration_seconds": 10, "face_visibility": 0.9, "luminance": 0.5}}
Constraints: risk_profile=standard, compute_budget_s=20
Output:
{{"plan_version": "3", "stages": [{{"stage": 1, "run": ["video-classifier", "aasist"], "mode": "parallel"}}, {{"stage": 2, "run": ["rppg", "syncnet"], "mode": "parallel", "condition": "stage 1 inconclusive"}}], "skipped": [], "coverage_warnings": [], "estimated_latency_s": 18.5, "rationale": "Conditions are good for all four detectors; run the fast ones first and escalate within budget."}}

Example B — audio-only file:
Input: {{"modality": "audio", "has_audio": true, "duration_seconds": 4.5}}
Constraints: risk_profile=standard, compute_budget_s=10
Output:
{{"plan_version": "3", "stages": [{{"stage": 1, "run": ["aasist"], "mode": "parallel"}}], "skipped": [], "coverage_warnings": ["No video-based evidence available — input has no visual track."], "estimated_latency_s": 0.3, "rationale": "Only aasist is eligible for an audio-only input."}}

Example C — silent video, high risk, tight budget:
Input: {{"modality": "video", "has_audio": false, "duration_seconds": 6, "face_visibility": 0.85, "luminance": 0.4}}
Constraints: risk_profile=high, compute_budget_s=6
Output:
{{"plan_version": "3", "stages": [{{"stage": 1, "run": ["video-classifier"], "mode": "parallel"}}], "skipped": [{{"detector_name": "rppg", "reason": "eligible but would exceed the tight 6s budget alongside video-classifier"}}], "coverage_warnings": ["No audio-based evidence available — input has no audio track.", "rppg skipped due to budget, reducing coverage despite high risk profile."], "estimated_latency_s": 5.1, "rationale": "High risk normally favors more coverage, but the 6s budget only fits the cheapest eligible detector."}}

Example D — low light, face partially visible — technically eligible but known weak conditions for rppg:
Input: {{"modality": "video", "has_audio": true, "duration_seconds": 10, "face_visibility": 0.3, "luminance": 0.08}}
Constraints: risk_profile=standard, compute_budget_s=20
Output:
{{"plan_version": "3", "stages": [{{"stage": 1, "run": ["video-classifier", "aasist"], "mode": "parallel"}}], "skipped": [{{"detector_name": "rppg", "reason": "input is low-light with a partially occluded face — rppg's known_failure_modes document this as producing a confident-but-wrong result"}}], "coverage_warnings": ["rppg excluded despite being technically eligible, because this input matches its documented failure condition."], "estimated_latency_s": 7.3, "rationale": "rppg is eligible by duration/modality, but its documented failure mode is a confident wrong answer — safer to skip it here."}}

Example E — LIVE TELEMETRY DEGRADATION (AASIST experiencing 8.2s latency spike vs 0.3s baseline):
Input: {{"modality": "video", "has_audio": true, "duration_seconds": 8, "face_visibility": 0.9, "luminance": 0.5}}
Telemetry: aasist status=DEGRADED, live_p95=8.2s (baseline: 0.33s, 24.5x degradation); video-classifier status=HEALTHY, live_p95=7.0s
Constraints: risk_profile=standard, compute_budget_s=10
Output:
{{"plan_version": "3", "stages": [{{"stage": 1, "run": ["video-classifier"], "mode": "parallel"}}], "skipped": [{{"detector_name": "aasist", "reason": "live telemetry indicates severe latency degradation (8.2s p95); running concurrently with video-classifier would exceed 10s budget"}}], "coverage_warnings": ["aasist deprioritized due to real-time latency spike (8.2s), sacrificing audio deepfake coverage to preserve system latency budget."], "estimated_latency_s": 7.0, "rationale": "Under a 10s budget, aasist's measured 8.2s latency spike makes concurrent execution with video-classifier (7.0s) budget-infeasible; prioritizing video-classifier."}}

Now produce the plan for the INPUT SUMMARY, REQUEST CONSTRAINTS, and LIVE TELEMETRY given above. JSON only.
"""
    return prompt
