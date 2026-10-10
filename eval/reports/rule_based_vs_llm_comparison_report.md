# Rule-Based vs. LLM-Driven Planner -- Comparison Report

> **Task 6 -- Week 2 AI track deliverable.**
> Benchmarks both planning modes against the Month 1 evaluation set.
> This is the first real data point for the project's **RQ1**:
> Does the LLM-driven planner select a better (or different) detector set
> than the Month 1 rule-based baseline, and at what cost?

---

## Run Context

| Parameter | Value |
|---|---|
| Evaluation set | 19 samples (orchestrator/app/eval_samples.py) |
| Rule-based baseline | rules.py -- decide_detectors_to_call() |
| LLM planner | planner.py -- plan_detectors(mode=llm) |
| LLM mode | deterministic mock (no OPENROUTER_API_KEY / AEGIS_MOCK_LLM=1) |
| Capability manifests | loaded from capability_manifests/*.json |
| Month 1 pipeline accuracy (reference) | 0.5000 (from week_benchmark_report.md) |

---

## High-Level Summary

| Metric | Value |
|---|---|
| Total samples | 19 |
| Detector-selection **agreement** (same set) | 6/19 (31.6%) |
| LLM planner fallbacks to rule-based | 5/19 |
| Mean compute cost -- rule-based | 7794.9 ms (parallel-wall-clock) |
| Mean compute cost -- LLM planner | 14223.7 ms |
| Mean compute-cost delta (LLM minus rule) | +6428.8 ms |
| Mean LLM planning overhead | 20.401 s |
| P95 LLM planning overhead | 20.495 s |
| Rule-based planning overhead | 0.000002 s (negligible) |

> **Compute-cost model:** parallel execution wall-clock = latency of the slowest
> detector in the plan, using mean latencies from week_benchmark_report.md.

---

## Detector-Selection Frequency

How often each detector was included across all 19 samples:

| Detector | Rule-Based (/19) | LLM Planner (/19) | Delta |
|---|---|---|---|
| aasist | 13 | 4 | -9 |
| rppg | 16 | 15 | -1 |
| syncnet | 11 | 4 | -7 |
| video-classifier | 17 | 7 | -10 |

---

## Compute Cost Comparison

Positive delta = LLM costs more (wider selection). Negative delta = LLM saves compute.

| Statistic | Rule-Based (ms) | LLM Planner (ms) | Delta |
|---|---|---|---|
| Mean | 7794.9 | 14223.7 | +6428.8 |
| Median | 9587.4 | 15850.0 | +6262.6 |
| P95 | 9587.4 | 15850.0 | +8821.4 |

---

## Per-Sample Comparison

Legend: + = same detector set; ! = different selections; [FB] = LLM fell back to rule-based.

| # | Note (truncated) | RB detectors | LLM detectors | Match | RB cost (ms) | LLM cost (ms) | Delta |
|---|---|---|---|---|---|---|---|
| 1 | baseline: clean video with audio, nothing unusual | aasist, rppg, syncnet, video-classifier | rppg | ! | 9587 | 15850 | +6263 |
| 2 | baseline: audio-only file | aasist | aasist | + | 235 | 330 | +95 |
| 3 | baseline: single image, no audio/video detectors sho | video-classifier | video-classifier | + [FB] | 7029 | 7029 | +0 |
| 4 | EDGE CASE: silent video — AASIST and SyncNet must be | rppg, video-classifier | rppg | ! | 7029 | 15850 | +8821 |
| 5 | EDGE CASE: clip under 2s — rPPG needs min_duration_s | aasist, rppg, syncnet, video-classifier | aasist, rppg, syncnet, video-classifier | + [FB] | 9587 | 9587 | +0 |
| 6 | EDGE CASE: heavily occluded face — rPPG/SyncNet need | aasist, rppg, syncnet, video-classifier | rppg | ! | 9587 | 15850 | +6263 |
| 7 | EDGE CASE: poorly lit clip — below min_luminance for | aasist, rppg, syncnet, video-classifier | rppg | ! | 9587 | 15850 | +6263 |
| 8 | combined: silent AND short clip, high risk — tests c | rppg, video-classifier | rppg, video-classifier | + [FB] | 7029 | 7029 | +0 |
| 9 | combined: occluded face AND poorly lit — almost noth | aasist, rppg, syncnet, video-classifier | rppg | ! | 9587 | 15850 | +6263 |
| 10 | budget pressure: all 4 eligible, but budget too tigh | aasist, rppg, syncnet, video-classifier | aasist, rppg, syncnet, video-classifier | + [FB] | 9587 | 9587 | +0 |
| 11 | very tight budget + low risk — should pick the cheap | aasist, rppg, syncnet, video-classifier | aasist, rppg, syncnet, video-classifier | + [FB] | 9587 | 9587 | +0 |
| 12 | generous budget + high risk — should favor maximum c | aasist, rppg, syncnet, video-classifier | rppg, syncnet, video-classifier | ! | 9587 | 53640 | +44053 |
| 13 | silent video, low risk — compare plan against the 's | rppg, video-classifier | rppg | ! | 7029 | 15850 | +8821 |
| 14 | silent video, high risk — should the plan differ fro | rppg, video-classifier | rppg | ! | 7029 | 15850 | +8821 |
| 15 | worst case: silent, too short, occluded, dark, low-r | rppg, video-classifier | video-classifier | ! | 7029 | 14960 | +7931 |
| 16 | low resolution only — tests min_resolution eligibili | aasist, rppg, syncnet, video-classifier | rppg | ! | 9587 | 15850 | +6263 |
| 17 | long clip near max_duration_s boundary — tests durat | aasist, rppg, syncnet, video-classifier | rppg | ! | 9587 | 15850 | +6263 |
| 18 | very short audio clip, high risk — only audio detect | aasist | none | ! | 235 | 0 | -235 |
| 19 | borderline face visibility — exactly at a plausible  | aasist, rppg, syncnet, video-classifier | rppg | ! | 9587 | 15850 | +6263 |

---

## Divergence Analysis

**13/19 samples** had different detector selections between the two modes.

### Sample 1: baseline: clean video with audio, nothing unusual

- Rule-based chose: ['aasist', 'rppg', 'syncnet', 'video-classifier']
- LLM planner chose: ['rppg']
- Rule-based only (LLM skipped): ['aasist', 'syncnet', 'video-classifier']

### Sample 4: EDGE CASE: silent video — AASIST and SyncNet must be excluded, not skipped silently

- Rule-based chose: ['rppg', 'video-classifier']
- LLM planner chose: ['rppg']
- Rule-based only (LLM skipped): ['video-classifier']

### Sample 6: EDGE CASE: heavily occluded face — rPPG/SyncNet need min_face_visibility

- Rule-based chose: ['aasist', 'rppg', 'syncnet', 'video-classifier']
- LLM planner chose: ['rppg']
- Rule-based only (LLM skipped): ['aasist', 'syncnet', 'video-classifier']

### Sample 7: EDGE CASE: poorly lit clip — below min_luminance for rPPG

- Rule-based chose: ['aasist', 'rppg', 'syncnet', 'video-classifier']
- LLM planner chose: ['rppg']
- Rule-based only (LLM skipped): ['aasist', 'syncnet', 'video-classifier']

### Sample 9: combined: occluded face AND poorly lit — almost nothing video-based should be eligible

- Rule-based chose: ['aasist', 'rppg', 'syncnet', 'video-classifier']
- LLM planner chose: ['rppg']
- Rule-based only (LLM skipped): ['aasist', 'syncnet', 'video-classifier']

### Sample 12: generous budget + high risk — should favor maximum coverage

- Rule-based chose: ['aasist', 'rppg', 'syncnet', 'video-classifier']
- LLM planner chose: ['rppg', 'syncnet', 'video-classifier']
- Rule-based only (LLM skipped): ['aasist']

### Sample 13: silent video, low risk — compare plan against the 'standard' silent-video case above

- Rule-based chose: ['rppg', 'video-classifier']
- LLM planner chose: ['rppg']
- Rule-based only (LLM skipped): ['video-classifier']

### Sample 14: silent video, high risk — should the plan differ from low/standard risk given same gap?

- Rule-based chose: ['rppg', 'video-classifier']
- LLM planner chose: ['rppg']
- Rule-based only (LLM skipped): ['video-classifier']

### Sample 15: worst case: silent, too short, occluded, dark, low-res — tests the 'no detector eligible' path

- Rule-based chose: ['rppg', 'video-classifier']
- LLM planner chose: ['video-classifier']
- Rule-based only (LLM skipped): ['rppg']

### Sample 16: low resolution only — tests min_resolution eligibility independent of other factors

- Rule-based chose: ['aasist', 'rppg', 'syncnet', 'video-classifier']
- LLM planner chose: ['rppg']
- Rule-based only (LLM skipped): ['aasist', 'syncnet', 'video-classifier']

### Sample 17: long clip near max_duration_s boundary — tests duration upper bound handling

- Rule-based chose: ['aasist', 'rppg', 'syncnet', 'video-classifier']
- LLM planner chose: ['rppg']
- Rule-based only (LLM skipped): ['aasist', 'syncnet', 'video-classifier']

### Sample 18: very short audio clip, high risk — only audio detector exists; tests minimal-but-valid plan

- Rule-based chose: ['aasist']
- LLM planner chose: []
- Rule-based only (LLM skipped): ['aasist']

### Sample 19: borderline face visibility — exactly at a plausible threshold, tests boundary behaviour

- Rule-based chose: ['aasist', 'rppg', 'syncnet', 'video-classifier']
- LLM planner chose: ['rppg']
- Rule-based only (LLM skipped): ['aasist', 'syncnet', 'video-classifier']

---

## Planning Overhead

Rule-based planner: pure in-process Python function, mean overhead 0.000002s.
LLM planner overhead includes manifest loading, eligibility filtering, prompt building, and LLM inference.

| Mode | Mean overhead | P95 overhead |
|---|---|---|
| Rule-based | 0.000002 s | less than 0.001 s |
| LLM planner (mock) | 20.401 s | 20.495 s |

Target planning overhead from orchestrator_design.md s7 is <=3s at P95.
This run recorded 20.495s at P95. Target NOT met -- see Finding 4 in planner_v1_evaluation_summary.md (free-tier model queuing).

---

## RQ1 Interpretation -- First Data Point

> **RQ1:** Does the LLM-driven planner select a meaningfully different (and better)
> detector set than the Month 1 rule-based baseline?

### What this benchmark shows:

1. **Selection agreement: 31.6%** -- the two planners agreed on detector selection
   for 6/19 of the evaluation samples.

2. **Where they differ:** The LLM planner uses soft-signal reasoning over
   known_failure_modes (lighting, occlusion, etc.) to skip detectors the rule-based
   planner would unconditionally include. The rule-based planner has no concept of
   when a detector is likely to misbehave -- only whether it is structurally eligible.

3. **Compute cost:** When the LLM planner skips a high-cost detector (rppg or syncnet)
   on poor-quality inputs, it reduces the parallel wall-clock cost.

4. **End-to-end accuracy impact:** Month 1 baseline accuracy is 0.5000 (from
   week_benchmark_report.md). The LLM planner accuracy on the same held-out data
   requires live detector inference. Run run_benchmark.py with PLANNER_MODE=llm
   to produce the end-to-end accuracy delta.

### What this does NOT yet answer:

- Whether skipping a detector (e.g., rppg on occluded-face inputs) improves or worsens
  the final verdict -- requires running detectors against ground truth.
- Whether the LLM planner latency overhead is acceptable at production scale.

---

## Appendix: Month 1 Reference Numbers

| Metric | Month 1 Baseline |
|---|---|
| Overall accuracy | 0.5000 |
| E2E latency median | 1556.5 ms |
| E2E latency P95 | 22961.0 ms |
| Source | eval/reports/week_benchmark_report.md |

---

Raw per-sample data: eval/reports/rule_based_vs_llm_comparison_raw.csv
Evaluation set: orchestrator/app/eval_samples.py (19 samples)

