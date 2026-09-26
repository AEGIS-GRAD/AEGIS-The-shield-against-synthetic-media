# AEGIS Week 1 Full-Pipeline Benchmark Report

> **This is the Month 1 baseline that Month 2's agentic orchestrator must be compared against.**

---

## Overview

| Parameter | Value |
|---|---|
| Total samples in manifest | 120 |
| Completed runs | 120 |
| Failed / skipped runs | 0 |
| Target (≥ 100 runs) | ✅ Met |

## Overall End-to-End Accuracy

| Metric | Value |
|---|---|
| Samples evaluated | 120 |
| Correct verdicts | 60 |
| **Overall accuracy** | **0.5000** |

## End-to-End Latency (per sample)

| Statistic | Latency (ms) |
|---|---|
| Mean | 5441.4 |
| Median | 1556.5 |
| P95 | 22961.0 |

## Per-Detector Contribution

Individual accuracy = fraction of samples *where that detector ran* where its own verdict matched `true_label`.
Pipeline agreement = fraction of those samples where the detector's verdict matched the final pipeline verdict.

| Detector | Times Called | Individual Accuracy | Pipeline Agreement | Mean Latency (ms) | Median Latency (ms) | P95 Latency (ms) |
|---|---|---|---|---|---|---|
| video-classifier | 60 | 0.4667 | 0.9000 | 7028.6 | 5142.5 | 14961.0 |
| rppg | 60 | 0.4667 | 0.1000 | 6607.7 | 4507.5 | 15850.0 |
| aasist | 120 | 0.5000 | 1.0000 | 234.8 | 212.0 | 334.0 |
| syncnet | 58 | 0.5172 | 1.0000 | 9587.4 | 6505.5 | 22834.0 |

---

## Notes

- Aggregation method: **weighted average** (video-classifier ×1.5, rppg ×1.2, syncnet ×1.2, aasist ×1.0).
  This is a placeholder heuristic — see `orchestrator/app/aggregate.py` for detail.
- Verdict thresholds: score ≥ 0.65 → SYNTHETIC, score ≤ 0.35 → AUTHENTIC, between → UNCERTAIN.
- UNCERTAIN and NO_RESULTS verdicts are treated as 'real' (authentic) for accuracy calculation purposes.
- Raw per-sample data: `eval/reports/week_benchmark_raw.csv`.
- Manifest: `eval/data/eval_manifest.csv`.

