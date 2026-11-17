# Alignment Study B — Judge & Planner Robustness Against Poisoning & Miscalibration

**Script:** `eval/scripts/run_alignment_study_b.py`
**Mitigation Module:** `debate/poisoning_guard.py`, `debate/arbitrator.py`, `orchestrator/app/eligibility.py`, `orchestrator/app/planner.py`
**Dataset Inputs:** 30 poisoning scenarios (including Week 11 Task 3 hard negatives from `eval/datasets/hard_negatives/hard_negatives_manifest.jsonl`) + 4 clean controls.

---

## Executive Findings

> **Baseline Vulnerability Confirmed (ASR = 93.3%):** Without cheap structural defenses, both the Orchestrator Planner and the Debate Judge exhibit systematic alignment failures when fed miscalibrated claims, rogue single-detector outliers, spoofed flags, poisoned `observed_reliability` manifests, or combined adversarial media + telemetry latency spikes.
>
> **Cheap Mitigations Reduce ASR to 0.0%:** Enforcing deterministic reliability/confidence caps, leave-one-out statistical outlier rejection, cross-modal quorum rules, primary-authority planner quorum, and 2x telemetry spike clamping reduces attack success from **93.3%** down to **0.0%** at sub-millisecond compute overhead and 100% benign control preservation.

## Attack Category Analysis

1. **Miscalibrated & Tampered Overconfidence (`miscalibrated_overconfidence`):** When a detector reports saturated probability (`>= 0.98` or `<= 0.01`) contradicted by `raw_score` or lacks a corroborating witness, baseline weighting allows one detector to saturate the fused score. Reliability weight-share caps (`<= 55%`) and confidence-vs-raw mismatch penalties (`0.35x`) neutralize single-detector domination.
2. **Rogue Outlier Injection (`rogue_outlier_injection`):** In the unmitigated Precedence Matrix, an extreme outlier on `aasist` or `video-classifier` triggers Rules 3, 5, 6, 7B, or 8C unconditionally — overriding a agreeing 3-detector majority. Pre-rule leave-one-out outlier detection isolates the rogue claim before Precedence weight discounts execute.
3. **Spoofed Corroboration & Attenuation Flags (`spoofed_corroboration_and_flag_poisoning`):** Unvalidated flag checks allow a single claim carrying `frequency_anomaly` or `uniform_low_perplexity` to trigger `>= 0.90` floors, or spoofed `low_light_attenuation` in daylight to silence healthy physiological sensors. Cross-modal quorum (`check_corroboration_quorum`) and objective metadata cross-checks eliminate flag spoofing.
4. **Manifest Reliability Feedback Poisoning (`manifest_reliability_feedback_poisoning`):** Poisoning `video-classifier` as `deprioritize` while leaving secondary proxy `rppg` as `reliable` tricks `compute_deprioritization_map()` into accepting `rppg` as a substitute, blinding spatial detection. Enforcing **Primary-Authority Quorum** prevents secondary proxies from excusing primary eviction.
5. **Adversarial Media + Telemetry/Cost Poisoning (`adversarial_media_and_telemetry_cost_poisoning`):** Pairing Week 11 Task 3 hard-negative samples (`square_linf`, `adaptive_transform_search`, `adaptive_feedback_paraphraser_v2`) with spoofed `48s` telemetry spikes and `cost_weight=0.55` causes baseline planning to evict decisive primary detectors (`video-classifier`, `detector_image`, `detector_text`). Clamping spoofed telemetry latency and protecting decisive primary detectors closes this compound attack vector.

## Reproducibility

```bash
python eval/scripts/run_alignment_study_b.py
pytest eval/tests/test_poisoning_and_alignment_study_b.py -v
```
