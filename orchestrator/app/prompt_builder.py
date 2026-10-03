"""
Planning prompt builder — v2 (matches real manifest schema)
==============================================================
Revised after reading the real capability_manifests/*.json files.

Key change from v1: since latency numbers in the manifests are currently
null ("measured_on": "PENDING"), this falls back to the real Month 1
full-pipeline benchmark numbers (eval/reports/week_benchmark_report.md) so
the budget constraint still has real data to work with instead of nothing.
Once detector owners fill in `performance` in their manifest, this fallback
stops being used automatically (manifest values take priority).
"""

import json

PROMPT_VERSION = "planner-v2.0"

# Fallback latency figures from eval/reports/week_benchmark_report.md
# (Month 1, 120-sample full-pipeline run), used only when a manifest's own
# `performance` fields are still null/pending.
BASELINE_LATENCY_MS = {
    "video-classifier": {"avg": 7028.6, "p95": 14961.0},
    "rppg": {"avg": 6607.7, "p95": 15850.0},
    "aasist": {"avg": 234.8, "p95": 334.0},
    "syncnet": {"avg": 9587.4, "p95": 22834.0},
}


def _latency_for(manifest: dict) -> tuple[float, float, str]:
    perf = manifest.get("performance", {})
    name = manifest["detector_name"]
    if perf.get("avg_latency_ms") is not None and perf.get("p95_latency_ms") is not None:
        return perf["avg_latency_ms"], perf["p95_latency_ms"], "manifest"
    if name in BASELINE_LATENCY_MS:
        b = BASELINE_LATENCY_MS[name]
        return b["avg"], b["p95"], "Month 1 benchmark fallback (manifest pending)"
    return None, None, "unknown"


def _format_failure_modes(manifest: dict) -> str:
    modes = manifest.get("known_failure_modes", [])
    if not modes:
        return "none documented"
    return "; ".join(f"{m['condition']} → {m['effect']}" for m in modes)


def _format_eligible_table(eligible: list[dict]) -> str:
    rows = []
    for m in eligible:
        avg_ms, p95_ms, source = _latency_for(m)
        latency_str = f"~{avg_ms/1000:.1f}s avg, {p95_ms/1000:.1f}s p95 (source: {source})" if avg_ms else "unknown"
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


def build_planning_prompt(
    eligible: list[dict],
    excluded: list[dict],
    input_summary: dict,
    risk_profile: str,
    budget_s: float,
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
- Your plan's estimated_latency_s MUST NOT exceed the budget given below.
- Each eligible detector's "known_failure_modes" and "reliability_notes" are
  real documented weaknesses, not boilerplate — weigh them when the input
  summary suggests a failure condition applies (e.g. low light, short clip,
  occluded face), even though no hard numeric threshold excluded it.
- If no detector is eligible, return an empty "stages" list and explain why
  in "rationale" — do not force a selection.
- Output key names must match the schema EXACTLY, character-for-character (e.g. "estimated_latency_s", never a variation).  

# 3. INPUT SUMMARY
{json.dumps(input_summary, indent=2)}

# 4. REQUEST CONSTRAINTS
- risk_profile: {risk_profile}   (low = cost-sensitive, standard = balanced, high = missing a fake is costly — favor coverage)
- compute_budget_s: {budget_s}   (hard ceiling on total estimated latency for this run)

# 5. ELIGIBLE DETECTORS
{_format_eligible_table(eligible)}

# 6. EXCLUDED DETECTORS
{_format_excluded_table(excluded)}

# 7. SELECTION GUIDANCE
- High risk_profile favors broader coverage over minimizing cost, but still
  must respect compute_budget_s.
- Tight budgets favor staging: run the cheapest detector(s) first; only
  escalate to slower detectors in a later stage if the budget allows.
- If the input summary (e.g. low face_visibility, low luminance, very short
  duration) matches a detector's known_failure_modes, treat that detector as
  low-value evidence even if it is technically eligible — either skip it and
  say why, or include it but note the caveat in coverage_warnings.
- If an excluded detector would have provided evidence this input type
  really needs (e.g. no audio-based detector was eligible for a video),
  say so explicitly in "coverage_warnings".

# 8. OUTPUT SCHEMA
Respond with JSON ONLY. No markdown fences, no commentary outside the JSON.
{{
  "plan_version": "2",
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

# 9. FEW-SHOT EXAMPLES

Example A — video with audio, standard risk, generous budget, good conditions:
Input: {{"modality": "video", "has_audio": true, "duration_seconds": 10, "face_visibility": 0.9, "luminance": 0.5}}
Constraints: risk_profile=standard, compute_budget_s=20
Output:
{{"plan_version": "2", "stages": [{{"stage": 1, "run": ["video-classifier", "aasist"], "mode": "parallel"}}, {{"stage": 2, "run": ["rppg", "syncnet"], "mode": "parallel", "condition": "stage 1 inconclusive"}}], "skipped": [], "coverage_warnings": [], "estimated_latency_s": 18.5, "rationale": "Conditions are good for all four detectors; run the fast ones first and escalate within budget."}}

Example B — audio-only file:
Input: {{"modality": "audio", "has_audio": true, "duration_seconds": 4.5}}
Constraints: risk_profile=standard, compute_budget_s=10
Output:
{{"plan_version": "2", "stages": [{{"stage": 1, "run": ["aasist"], "mode": "parallel"}}], "skipped": [], "coverage_warnings": ["No video-based evidence available — input has no visual track."], "estimated_latency_s": 0.3, "rationale": "Only aasist is eligible for an audio-only input."}}

Example C — silent video, high risk, tight budget:
Input: {{"modality": "video", "has_audio": false, "duration_seconds": 6, "face_visibility": 0.85, "luminance": 0.4}}
Constraints: risk_profile=high, compute_budget_s=6
Output:
{{"plan_version": "2", "stages": [{{"stage": 1, "run": ["video-classifier"], "mode": "parallel"}}], "skipped": [{{"detector_name": "rppg", "reason": "eligible but would exceed the tight 6s budget alongside video-classifier"}}], "coverage_warnings": ["No audio-based evidence available — input has no audio track.", "rppg skipped due to budget, reducing coverage despite high risk profile."], "estimated_latency_s": 5.1, "rationale": "High risk normally favors more coverage, but the 6s budget only fits the cheapest eligible detector."}}

Example D — low light, face partially visible — technically eligible but known weak conditions for rppg:
Input: {{"modality": "video", "has_audio": true, "duration_seconds": 10, "face_visibility": 0.3, "luminance": 0.08}}
Constraints: risk_profile=standard, compute_budget_s=20
Output:
{{"plan_version": "2", "stages": [{{"stage": 1, "run": ["video-classifier", "aasist"], "mode": "parallel"}}], "skipped": [{{"detector_name": "rppg", "reason": "input is low-light with a partially occluded face — rppg's known_failure_modes document this as producing a confident-but-wrong result, not just reduced accuracy"}}], "coverage_warnings": ["rppg excluded despite being technically eligible, because this input matches its documented failure condition for misleading (not just noisy) results."], "estimated_latency_s": 7.3, "rationale": "rppg is eligible by duration/modality, but its own documented failure mode for this exact condition (low light + occlusion) is a confident wrong answer, which is worse than no answer — safer to skip it here."}}

Now produce the plan for the INPUT SUMMARY and CONSTRAINTS given above. JSON only.
"""
    return prompt
