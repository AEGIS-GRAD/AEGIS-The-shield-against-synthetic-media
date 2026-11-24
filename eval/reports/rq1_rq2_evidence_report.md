# AEGIS Month 3 Task #2 — RQ1 & RQ2 Evidence Package Report

**RQ1 Execution Mode:** `deterministic_reference` ($N = 48$ paired inputs across all 4 modalities)  
**RQ2 Protocol:** 8 sessions × 50 paired inputs ($N = 400$ per arm; S2–S8 = 350)

---

## 1. RQ1 — Planner-Efficiency Comparison (Overall, N = 48 Paired Inputs)

| Arm | Mean Detectors | Mean Compute (s) | Mean Wall Latency (s) | Budget Compliance (95% CI) | Wasted Dispatches | Verdict Accuracy | False-Authentics |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Static Ensemble | 2.00 | 12.74s | 5.97s | 89.6% [77.8%, 95.5%] | 17 | 89.6% | 2 |
| Rule-Based Baseline | 1.88 | 11.54s | 5.65s | 89.6% [77.8%, 95.5%] | 11 | 89.6% | 2 |
| **AEGIS LLM Planner** | 1.48 | 7.56s | 4.18s | 100.0% [92.6%, 100.0%] | 0 | 89.6% | 2 |

### RQ1 Per-Modality Compute Cost & Wall Latency

| Modality (N) | Static Compute / Wall | Rule-Based Compute / Wall | LLM Planner Compute / Wall |
| :--- | :---: | :---: | :---: |
| `video` (24) | 25.00s / 11.45s | 22.60s / 10.81s | **14.66s / 7.79s** |
| `audio` (8) | 0.23s / 0.23s | 0.23s / 0.23s | **0.18s / 0.30s** |
| `image` (8) | 0.94s / 0.94s | 0.94s / 0.94s | **0.94s / 1.05s** |
| `text` (8) | 0.27s / 0.27s | 0.27s / 0.27s | **0.27s / 0.38s** |

### RQ1 Paired Statistical Significance Tests

| Contrast | Metric | Mean Paired Delta (95% CI) | Paired t ($p_{\text{Holm}}$) | Wilcoxon $W$ ($p_{\text{Holm}}$) | Cohen's $d_z$ | Rank-Biserial $r$ |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| Static − LLM Planner | `compute_cost_s` | +5.182 [+3.143, +7.402] | 4.69 (7.24e-05) | 0.0 (2.28e-04) | 0.68 | 1.00 |
| Static − LLM Planner | `wall_latency_s` | +1.783 [+0.857, +2.883] | 3.38 (4.44e-03) | 481.0 (5.55e-01) | 0.49 | 0.18 |
| Static − LLM Planner | `wasted_dispatches` | +0.354 [+0.208, +0.521] | 4.35 (2.21e-04) | 0.0 (6.72e-04) | 0.63 | 1.00 |
| Rule-Based − LLM Planner | `compute_cost_s` | +3.983 [+2.083, +5.990] | 3.80 (8.35e-04) | 0.0 (8.32e-04) | 0.55 | 1.00 |
| Rule-Based − LLM Planner | `wall_latency_s` | +1.464 [+0.507, +2.562] | 2.74 (1.73e-02) | 490.0 (5.55e-01) | 0.40 | -0.17 |
| Rule-Based − LLM Planner | `wasted_dispatches` | +0.229 [+0.125, +0.354] | 3.74 (1.00e-03) | 0.0 (1.82e-03) | 0.54 | 1.00 |
| Static − Rule-Based | `compute_cost_s` | +1.198 [+0.400, +2.197] | 2.59 (1.27e-02) | 0.0 (1.43e-02) | 0.37 | 1.00 |
| Static − Rule-Based | `wall_latency_s` | +0.320 [+0.107, +0.586] | 2.59 (1.73e-02) | 0.0 (4.29e-02) | 0.37 | 1.00 |
| Static − Rule-Based | `wasted_dispatches` | +0.125 [+0.042, +0.229] | 2.59 (1.27e-02) | 0.0 (1.43e-02) | 0.37 | 1.00 |

---

## 2. RQ2 — Closed-Loop Reliability Feedback (Sessions 2–8, N = 350 Paired Inputs)

| Metric | Loop OFF | Loop ON | Paired Delta | Wilcoxon $p$ | Paired t $p$ | McNemar $p$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| Failing-Condition Dispatch | 100.0% | **9.0%** | -91.0 pp | 0.0156 | 4.36e-06 | 0.00e+00 |
| Nominal Retention Rate | 100.0% | **100.0%** | +0.0 pp | — | — | — |
| Confirmed-Wrong Overrules | 184 | **42** | -142 | 0.0156 | 2.87e-06 | — |
| Multi-Detector Conflict Rate | 59.1% | **23.4%** | -35.7 pp | 0.0156 | 1.08e-05 | — |
| Mean Compute Cost (s/input) | 19.30s | **15.47s** | -3.83s | 0.00e+00 | 0.00e+00 | — |
| Mean Wall Latency (s/input) | 8.78s | **8.62s** | -0.16s | 1.24e-02 | 4.64e-02 | — |
| Verdict Accuracy | 78.9% | **82.3%** | +3.4 pp | — | — | 0.0060 |
