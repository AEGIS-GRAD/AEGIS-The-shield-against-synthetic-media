"""
benchmark_planner_vs_baseline.py  ---  Task 6
==============================================
Benchmarks the LLM-driven planner against the Month 1 rule-based baseline
on the same 19-sample evaluation set (orchestrator/app/eval_samples.py).

For every sample, both planning modes are run:
  1. rule_based  -- deterministic Month 1 orchestrator (rules.py)
  2. llm         -- LLM-driven planner (planner.py); uses mock mode when
                   OPENROUTER_API_KEY is absent.

Per sample the script records:
  - detector-selection choices for each mode
  - estimated compute cost
  - agreement/disagreement between modes
  - planning overhead latency

Output:
  eval/reports/rule_based_vs_llm_comparison_report.md
  eval/reports/rule_based_vs_llm_comparison_raw.csv

Usage:
    python eval/scripts/benchmark_planner_vs_baseline.py
    OPENROUTER_API_KEY=sk-... python eval/scripts/benchmark_planner_vs_baseline.py
    AEGIS_MOCK_LLM=1 python eval/scripts/benchmark_planner_vs_baseline.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parent.parent.parent
_ORCHESTRATOR_APP = _REPO_ROOT / "orchestrator" / "app"
_EVAL_REPORTS = _REPO_ROOT / "eval" / "reports"

if str(_ORCHESTRATOR_APP) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR_APP))

from models import InputMetadata
from rules import decide_detectors_to_call
from planner import plan_detectors
from eval_samples import SAMPLES
from eligibility import filter_detectors
from manifest_loader import load_all_manifests

REPORT_PATH = _EVAL_REPORTS / "rule_based_vs_llm_comparison_report.md"
RAW_CSV_PATH = _EVAL_REPORTS / "rule_based_vs_llm_comparison_raw.csv"

MONTH1_ACCURACY = 0.5000
MONTH1_E2E_LATENCY_MEDIAN_MS = 1556.5
MONTH1_E2E_LATENCY_P95_MS = 22961.0

DETECTOR_LATENCY_MS: Dict[str, float] = {
    "video-classifier": 7028.6,
    "rppg": 6607.7,
    "aasist": 234.8,
    "syncnet": 9587.4,
}


def _compute_cost_ms(detectors: List[str]) -> float:
    if not detectors:
        return 0.0
    costs = [DETECTOR_LATENCY_MS.get(d, 5000.0) for d in detectors]
    return max(costs)


def _input_summary_to_metadata(input_summary: Dict[str, Any], idx: int) -> InputMetadata:
    return InputMetadata(
        filename=f"eval_sample_{idx:02d}",
        modality=input_summary.get("modality", "video"),
        has_audio=bool(input_summary.get("has_audio", False)),
        duration_seconds=float(input_summary.get("duration_seconds", 10.0)),
        resolution=input_summary.get("resolution"),
    )


def _detectors_match(a: List[str], b: List[str]) -> bool:
    return sorted(a) == sorted(b)


def run_rule_based(metadata: InputMetadata) -> Tuple[List[str], float]:
    t0 = time.perf_counter()
    detectors = decide_detectors_to_call(metadata)
    latency = time.perf_counter() - t0
    return detectors, round(latency, 6)


def run_llm_planner(
    metadata: InputMetadata,
    risk_profile: str,
    budget_s: float,
    mock_llm: bool,
) -> Tuple[List[str], Optional[float], bool, Optional[str], float, Optional[Dict[str, Any]]]:
    result = plan_detectors(
        metadata=metadata,
        mode="llm",
        risk_profile=risk_profile,
        budget_s=budget_s,
        mock_llm=mock_llm,
    )
    estimated_cost_s: Optional[float] = None
    if result.plan:
        estimated_cost_s = result.plan.get("estimated_latency_s")
    return (
        result.detectors_to_call,
        estimated_cost_s,
        result.fallback,
        result.fallback_reason,
        result.planning_latency_s,
        result.plan,
    )


def run_benchmark(mock_llm: bool = False) -> List[Dict[str, Any]]:
    try:
        manifests = load_all_manifests()
        print(f"[INFO] Loaded {len(manifests)} capability manifests.")
    except Exception as exc:
        print(f"[WARN] Could not load manifests: {exc}.")
        manifests = []

    rows: List[Dict[str, Any]] = []
    total = len(SAMPLES)

    print(f"\n{'='*70}")
    print(f"  Task 6 -- Benchmark: LLM Planner vs. Rule-Based Baseline")
    print(f"  Samples: {total}  |  Mock LLM: {mock_llm}")
    print(f"{'='*70}\n")

    for idx, (input_summary, risk_profile, budget_s, note) in enumerate(SAMPLES, start=1):
        metadata = _input_summary_to_metadata(input_summary, idx)

        rb_detectors, rb_latency_s = run_rule_based(metadata)

        eligible_ids: List[str] = []
        if manifests:
            eligible, excluded = filter_detectors(manifests, input_summary)
            eligible_ids = sorted(m["detector_name"] for m in eligible)

        llm_t0 = time.perf_counter()
        try:
            (
                llm_detectors,
                llm_estimated_cost_s,
                llm_fallback,
                llm_fallback_reason,
                llm_planning_latency_s,
                llm_plan,
            ) = run_llm_planner(metadata, risk_profile, budget_s, mock_llm)
        except Exception as exc:
            llm_detectors = rb_detectors[:]
            llm_estimated_cost_s = None
            llm_fallback = True
            llm_fallback_reason = f"Exception: {exc}"
            llm_planning_latency_s = round(time.perf_counter() - llm_t0, 3)
            llm_plan = None

        rb_compute_cost_ms = _compute_cost_ms(rb_detectors)
        llm_compute_cost_ms = (
            (llm_estimated_cost_s * 1000.0) if llm_estimated_cost_s is not None
            else _compute_cost_ms(llm_detectors)
        )

        selection_match = _detectors_match(rb_detectors, llm_detectors)
        rb_adds = sorted(set(rb_detectors) - set(llm_detectors))
        llm_adds = sorted(set(llm_detectors) - set(rb_detectors))
        cost_delta_ms = llm_compute_cost_ms - rb_compute_cost_ms

        match_icon = "+" if selection_match else "!"
        fb_flag = " [FB]" if llm_fallback else ""
        print(
            f"  [{idx:2}/{total}] {match_icon}{fb_flag} | "
            f"RB={rb_detectors} | LLM={llm_detectors} | "
            f"dCost={cost_delta_ms:+.0f}ms | lat={llm_planning_latency_s:.3f}s | {note[:45]}"
        )

        rows.append({
            "sample_idx": idx,
            "note": note,
            "modality": input_summary.get("modality", ""),
            "has_audio": input_summary.get("has_audio", False),
            "duration_s": input_summary.get("duration_seconds", ""),
            "risk_profile": risk_profile,
            "budget_s": budget_s,
            "eligible_ids": json.dumps(eligible_ids),
            "rb_detectors": json.dumps(sorted(rb_detectors)),
            "rb_compute_cost_ms": round(rb_compute_cost_ms, 1),
            "rb_planning_latency_s": round(rb_latency_s, 6),
            "llm_detectors": json.dumps(sorted(llm_detectors)),
            "llm_estimated_cost_ms": round(llm_compute_cost_ms, 1),
            "llm_planning_latency_s": round(llm_planning_latency_s, 3),
            "llm_fallback": llm_fallback,
            "llm_fallback_reason": llm_fallback_reason or "",
            "selection_match": selection_match,
            "rb_only_detectors": json.dumps(rb_adds),
            "llm_only_detectors": json.dumps(llm_adds),
            "compute_cost_delta_ms": round(cost_delta_ms, 1),
        })

    return rows


def write_csv(rows: List[Dict[str, Any]]) -> None:
    _EVAL_REPORTS.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with open(RAW_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n[OK] Raw CSV written to {RAW_CSV_PATH}")


def write_report(rows: List[Dict[str, Any]], mock_llm: bool) -> None:
    _EVAL_REPORTS.mkdir(parents=True, exist_ok=True)

    total = len(rows)
    matches = sum(1 for r in rows if r["selection_match"])
    fallbacks = sum(1 for r in rows if r["llm_fallback"])
    match_rate = matches / total if total else 0.0

    rb_costs = [r["rb_compute_cost_ms"] for r in rows]
    llm_costs = [r["llm_estimated_cost_ms"] for r in rows]
    cost_deltas = [r["compute_cost_delta_ms"] for r in rows]

    def _mean(vals):
        return sum(vals) / len(vals) if vals else 0.0

    rb_mean_cost = _mean(rb_costs)
    llm_mean_cost = _mean(llm_costs)
    mean_delta = _mean(cost_deltas)

    rb_det_freq: Dict[str, int] = {}
    llm_det_freq: Dict[str, int] = {}
    for r in rows:
        for d in json.loads(r["rb_detectors"]):
            rb_det_freq[d] = rb_det_freq.get(d, 0) + 1
        for d in json.loads(r["llm_detectors"]):
            llm_det_freq[d] = llm_det_freq.get(d, 0) + 1

    all_detectors = sorted(set(list(rb_det_freq) + list(llm_det_freq)))

    llm_plan_lats = [r["llm_planning_latency_s"] for r in rows]
    rb_plan_lats = [r["rb_planning_latency_s"] for r in rows]
    import statistics as _stats

    llm_lat_mean = round(_stats.mean(llm_plan_lats), 3) if llm_plan_lats else 0
    rb_lat_mean = round(_stats.mean(rb_plan_lats), 6) if rb_plan_lats else 0
    llm_lat_p95 = round(sorted(llm_plan_lats)[max(0, int(len(llm_plan_lats) * 0.95) - 1)], 3)

    llm_mode_note = (
        "deterministic mock (no OPENROUTER_API_KEY / AEGIS_MOCK_LLM=1)"
        if mock_llm
        else "live LLM via OpenRouter"
    )

    lines: List[str] = []
    lines += [
        "# Rule-Based vs. LLM-Driven Planner -- Comparison Report",
        "",
        "> **Task 6 -- Week 2 AI track deliverable.**",
        "> Benchmarks both planning modes against the Month 1 evaluation set.",
        "> This is the first real data point for the project's **RQ1**:",
        "> Does the LLM-driven planner select a better (or different) detector set",
        "> than the Month 1 rule-based baseline, and at what cost?",
        "",
        "---",
        "",
        "## Run Context",
        "",
        "| Parameter | Value |",
        "|---|---|",
        "| Evaluation set | 19 samples (orchestrator/app/eval_samples.py) |",
        "| Rule-based baseline | rules.py -- decide_detectors_to_call() |",
        "| LLM planner | planner.py -- plan_detectors(mode=llm) |",
        f"| LLM mode | {llm_mode_note} |",
        "| Capability manifests | loaded from capability_manifests/*.json |",
        f"| Month 1 pipeline accuracy (reference) | {MONTH1_ACCURACY:.4f} (from week_benchmark_report.md) |",
        "",
        "---",
        "",
        "## High-Level Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total samples | {total} |",
        f"| Detector-selection **agreement** (same set) | {matches}/{total} ({match_rate:.1%}) |",
        f"| LLM planner fallbacks to rule-based | {fallbacks}/{total} |",
        f"| Mean compute cost -- rule-based | {rb_mean_cost:.1f} ms (parallel-wall-clock) |",
        f"| Mean compute cost -- LLM planner | {llm_mean_cost:.1f} ms |",
        f"| Mean compute-cost delta (LLM minus rule) | {mean_delta:+.1f} ms |",
        f"| Mean LLM planning overhead | {llm_lat_mean:.3f} s |",
        f"| P95 LLM planning overhead | {llm_lat_p95:.3f} s |",
        f"| Rule-based planning overhead | {rb_lat_mean:.6f} s (negligible) |",
        "",
        "> **Compute-cost model:** parallel execution wall-clock = latency of the slowest",
        "> detector in the plan, using mean latencies from week_benchmark_report.md.",
        "",
        "---",
        "",
        "## Detector-Selection Frequency",
        "",
        f"How often each detector was included across all {total} samples:",
        "",
        f"| Detector | Rule-Based (/{total}) | LLM Planner (/{total}) | Delta |",
        "|---|---|---|---|",
    ]
    for det in all_detectors:
        rb_n = rb_det_freq.get(det, 0)
        llm_n = llm_det_freq.get(det, 0)
        delta = llm_n - rb_n
        delta_str = f"{delta:+d}" if delta != 0 else "0"
        lines.append(f"| {det} | {rb_n} | {llm_n} | {delta_str} |")

    rb_sorted = sorted(rb_costs)
    llm_sorted = sorted(llm_costs)
    p95_idx = max(0, int(total * 0.95) - 1)

    lines += [
        "",
        "---",
        "",
        "## Compute Cost Comparison",
        "",
        "Positive delta = LLM costs more (wider selection). Negative delta = LLM saves compute.",
        "",
        "| Statistic | Rule-Based (ms) | LLM Planner (ms) | Delta |",
        "|---|---|---|---|",
        f"| Mean | {_mean(rb_costs):.1f} | {_mean(llm_costs):.1f} | {_mean(cost_deltas):+.1f} |",
        f"| Median | {_stats.median(rb_sorted):.1f} | {_stats.median(llm_sorted):.1f} | {_stats.median(sorted(cost_deltas)):+.1f} |",
        f"| P95 | {rb_sorted[p95_idx]:.1f} | {llm_sorted[p95_idx]:.1f} | {sorted(cost_deltas)[p95_idx]:+.1f} |",
        "",
        "---",
        "",
        "## Per-Sample Comparison",
        "",
        "Legend: + = same detector set; ! = different selections; [FB] = LLM fell back to rule-based.",
        "",
        "| # | Note (truncated) | RB detectors | LLM detectors | Match | RB cost (ms) | LLM cost (ms) | Delta |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        match_sym = "+" if r["selection_match"] else "!"
        fb_flag = " [FB]" if r["llm_fallback"] else ""
        rb_det_str = ", ".join(json.loads(r["rb_detectors"])) or "none"
        llm_det_str = ", ".join(json.loads(r["llm_detectors"])) or "none"
        note_trunc = r["note"][:52]
        lines.append(
            f"| {r['sample_idx']} | {note_trunc} | {rb_det_str} | {llm_det_str} "
            f"| {match_sym}{fb_flag} | {r['rb_compute_cost_ms']:.0f} | {r['llm_estimated_cost_ms']:.0f} "
            f"| {r['compute_cost_delta_ms']:+.0f} |"
        )

    divergent = [r for r in rows if not r["selection_match"]]
    lines += [
        "",
        "---",
        "",
        "## Divergence Analysis",
        "",
        f"**{len(divergent)}/{total} samples** had different detector selections between the two modes.",
        "",
    ]
    if not divergent:
        lines.append("No divergence -- both modes agreed on every sample in this evaluation set.")
    else:
        for r in divergent:
            rb_only = json.loads(r["rb_only_detectors"])
            llm_only = json.loads(r["llm_only_detectors"])
            lines += [
                f"### Sample {r['sample_idx']}: {r['note']}",
                "",
                f"- Rule-based chose: {sorted(json.loads(r['rb_detectors']))}",
                f"- LLM planner chose: {sorted(json.loads(r['llm_detectors']))}",
            ]
            if rb_only:
                lines.append(f"- Rule-based only (LLM skipped): {rb_only}")
            if llm_only:
                lines.append(f"- LLM added (not in rule-based): {llm_only}")
            if r["llm_fallback"]:
                lines.append(f"- WARNING: LLM fallback triggered: {r['llm_fallback_reason'][:100]}")
            lines.append("")

    p95_note = "Target met." if llm_lat_p95 <= 3.0 else (
        "Target NOT met -- see Finding 4 in planner_v1_evaluation_summary.md (free-tier model queuing)."
    )
    lines += [
        "---",
        "",
        "## Planning Overhead",
        "",
        f"Rule-based planner: pure in-process Python function, mean overhead {rb_lat_mean:.6f}s.",
        "LLM planner overhead includes manifest loading, eligibility filtering, prompt building, and LLM inference.",
        "",
        "| Mode | Mean overhead | P95 overhead |",
        "|---|---|---|",
        f"| Rule-based | {rb_lat_mean:.6f} s | less than 0.001 s |",
        f"| LLM planner ({'mock' if mock_llm else 'live'}) | {llm_lat_mean:.3f} s | {llm_lat_p95:.3f} s |",
        "",
        f"Target planning overhead from orchestrator_design.md s7 is <=3s at P95.",
        f"This run recorded {llm_lat_p95:.3f}s at P95. {p95_note}",
        "",
        "---",
        "",
        "## RQ1 Interpretation -- First Data Point",
        "",
        "> **RQ1:** Does the LLM-driven planner select a meaningfully different (and better)",
        "> detector set than the Month 1 rule-based baseline?",
        "",
        "### What this benchmark shows:",
        "",
        f"1. **Selection agreement: {match_rate:.1%}** -- the two planners agreed on detector selection",
        f"   for {matches}/{total} of the evaluation samples.",
        "",
        "2. **Where they differ:** The LLM planner uses soft-signal reasoning over",
        "   known_failure_modes (lighting, occlusion, etc.) to skip detectors the rule-based",
        "   planner would unconditionally include. The rule-based planner has no concept of",
        "   when a detector is likely to misbehave -- only whether it is structurally eligible.",
        "",
        "3. **Compute cost:** When the LLM planner skips a high-cost detector (rppg or syncnet)",
        "   on poor-quality inputs, it reduces the parallel wall-clock cost.",
        "",
        "4. **End-to-end accuracy impact:** Month 1 baseline accuracy is 0.5000 (from",
        "   week_benchmark_report.md). The LLM planner accuracy on the same held-out data",
        "   requires live detector inference. Run run_benchmark.py with PLANNER_MODE=llm",
        "   to produce the end-to-end accuracy delta.",
        "",
        "### What this does NOT yet answer:",
        "",
        "- Whether skipping a detector (e.g., rppg on occluded-face inputs) improves or worsens",
        "  the final verdict -- requires running detectors against ground truth.",
        "- Whether the LLM planner latency overhead is acceptable at production scale.",
        "",
        "---",
        "",
        "## Appendix: Month 1 Reference Numbers",
        "",
        "| Metric | Month 1 Baseline |",
        "|---|---|",
        f"| Overall accuracy | {MONTH1_ACCURACY:.4f} |",
        f"| E2E latency median | {MONTH1_E2E_LATENCY_MEDIAN_MS:.1f} ms |",
        f"| E2E latency P95 | {MONTH1_E2E_LATENCY_P95_MS:.1f} ms |",
        "| Source | eval/reports/week_benchmark_report.md |",
        "",
        "---",
        "",
        "Raw per-sample data: eval/reports/rule_based_vs_llm_comparison_raw.csv",
        "Evaluation set: orchestrator/app/eval_samples.py (19 samples)",
        "",
    ]

    report_text = "\n".join(lines) + "\n"
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"[OK] Comparison report written to {REPORT_PATH}")


def main() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    mock_env = os.environ.get("AEGIS_MOCK_LLM", "").lower() in ("1", "true", "yes")
    mock_llm = mock_env or not api_key

    if mock_llm and not mock_env:
        print("[INFO] No OPENROUTER_API_KEY found -- running LLM planner in deterministic mock mode.")
        os.environ["AEGIS_MOCK_LLM"] = "1"

    rows = run_benchmark(mock_llm=mock_llm)
    write_csv(rows)
    write_report(rows, mock_llm=mock_llm)

    total = len(rows)
    matches = sum(1 for r in rows if r["selection_match"])
    fallbacks = sum(1 for r in rows if r["llm_fallback"])
    print(f"\n{'='*70}")
    print(f"  BENCHMARK COMPLETE  (Task 6)")
    print(f"  Samples: {total}   Selection agreement: {matches}/{total}   Fallbacks: {fallbacks}")
    print(f"  Report:  {REPORT_PATH}")
    print(f"  Raw CSV: {RAW_CSV_PATH}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
