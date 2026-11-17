# AEGIS Adversarial Robustness v2 — Adaptive & Agentic Evasion Report

- **Generated (UTC):** `2026-11-17T19:53:36Z`
- **Threshold:** `0.50` (evaded when confidence `< 0.50`)
- **Vision Query Budgets:** Square Attack `L_inf <= 0.063` (`16/255`), `max_queries=120`; Adaptive Transform Search `max_queries=60`
- **Agentic Text Budget:** `max_turns=6`, beam candidates per turn, semantic similarity `>= 0.35`, word-count guard `>= 40`

## 1. Before vs. After Mitigation Summary

| Modality | Detector | Attack Method | Phase | Clean Detected | Evaded | Final ASR | Mean Score Drop |
| :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: |
| `image` | `image_mobilenetv3_forensics_v2` | `adaptive_transform_search` | **before_mitigation** | 7 | 6 | **85.7%** | `+0.505` |
| `image` | `image_mobilenetv3_forensics_v2` | `square_linf` | **before_mitigation** | 7 | 6 | **85.7%** | `+0.519` |
| `video` | `video_efficientnet_b0_v2` | `adaptive_transform_search` | **before_mitigation** | 8 | 2 | **25.0%** | `+0.343` |
| `video` | `video_efficientnet_b0_v2` | `square_linf` | **before_mitigation** | 8 | 2 | **25.0%** | `+0.251` |
| `image` | `image_mobilenetv3_forensics_v2_hardened` | `adaptive_transform_search` | **after_mitigation** | 8 | 0 | **0.0%** | `+0.088` |
| `image` | `image_mobilenetv3_forensics_v2_hardened` | `square_linf` | **after_mitigation** | 8 | 3 | **37.5%** | `+0.325` |
| `video` | `video_efficientnet_b0_v2_hardened` | `adaptive_transform_search` | **after_mitigation** | 8 | 1 | **12.5%** | `+0.119` |
| `video` | `video_efficientnet_b0_v2_hardened` | `square_linf` | **after_mitigation** | 8 | 2 | **25.0%** | `+0.119` |
| `text` | `text_forensics_local_v2` | `adaptive_feedback_paraphraser_v2` | **before_mitigation** | 8 | 8 | **100.0%** | `+0.244` |
| `text` | `text_forensics_local_v2_hardened` | `adaptive_feedback_paraphraser_v2` | **after_mitigation** | 8 | 4 | **50.0%** | `+0.131` |

## 2. Evasion Success-Rate Curves (ASR vs. Budget)

| Phase | Modality | Detector | Attack | Budget | ASR | Mean Conf | Mean Drop |
| :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `adaptive_transform_search` | `1 queries` | 0.0% | `0.949` | `+0.000` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `adaptive_transform_search` | `10 queries` | 57.1% | `0.533` | `+0.416` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `adaptive_transform_search` | `25 queries` | 85.7% | `0.444` | `+0.505` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `adaptive_transform_search` | `40 queries` | 85.7% | `0.444` | `+0.505` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `adaptive_transform_search` | `50 queries` | 85.7% | `0.444` | `+0.505` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `adaptive_transform_search` | `60 queries` | 85.7% | `0.444` | `+0.505` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `adaptive_transform_search` | `75 queries` | 85.7% | `0.444` | `+0.505` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `adaptive_transform_search` | `100 queries` | 85.7% | `0.444` | `+0.505` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `adaptive_transform_search` | `150 queries` | 85.7% | `0.444` | `+0.505` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `square_linf` | `1 queries` | 0.0% | `0.887` | `+0.062` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `square_linf` | `10 queries` | 28.6% | `0.620` | `+0.329` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `square_linf` | `25 queries` | 71.4% | `0.503` | `+0.445` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `square_linf` | `50 queries` | 85.7% | `0.485` | `+0.464` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `square_linf` | `75 queries` | 85.7% | `0.468` | `+0.481` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `square_linf` | `100 queries` | 85.7% | `0.455` | `+0.494` |
| `before_mitigation` | `image` | `image_mobilenetv3_forensics_v2` | `square_linf` | `150 queries` | 85.7% | `0.430` | `+0.519` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `adaptive_transform_search` | `1 queries` | 0.0% | `0.901` | `+0.000` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `adaptive_transform_search` | `10 queries` | 0.0% | `0.665` | `+0.236` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `adaptive_transform_search` | `25 queries` | 25.0% | `0.576` | `+0.325` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `adaptive_transform_search` | `40 queries` | 25.0% | `0.573` | `+0.328` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `adaptive_transform_search` | `50 queries` | 25.0% | `0.557` | `+0.343` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `adaptive_transform_search` | `60 queries` | 25.0% | `0.557` | `+0.343` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `adaptive_transform_search` | `75 queries` | 25.0% | `0.557` | `+0.343` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `adaptive_transform_search` | `100 queries` | 25.0% | `0.557` | `+0.343` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `adaptive_transform_search` | `150 queries` | 25.0% | `0.557` | `+0.343` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `square_linf` | `1 queries` | 0.0% | `0.885` | `+0.016` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `square_linf` | `10 queries` | 12.5% | `0.808` | `+0.093` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `square_linf` | `25 queries` | 12.5% | `0.765` | `+0.135` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `square_linf` | `50 queries` | 12.5% | `0.734` | `+0.167` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `square_linf` | `75 queries` | 12.5% | `0.698` | `+0.203` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `square_linf` | `100 queries` | 12.5% | `0.658` | `+0.242` |
| `before_mitigation` | `video` | `video_efficientnet_b0_v2` | `square_linf` | `150 queries` | 25.0% | `0.649` | `+0.252` |
| `before_mitigation` | `text` | `text_forensics_local_v2` | `adaptive_feedback_paraphraser_v2` | `0 turns` | 0.0% | `0.576` | `+0.000` |
| `before_mitigation` | `text` | `text_forensics_local_v2` | `adaptive_feedback_paraphraser_v2` | `1 turns` | 100.0% | `0.332` | `+0.244` |
| `before_mitigation` | `text` | `text_forensics_local_v2` | `adaptive_feedback_paraphraser_v2` | `2 turns` | 100.0% | `0.332` | `+0.244` |
| `before_mitigation` | `text` | `text_forensics_local_v2` | `adaptive_feedback_paraphraser_v2` | `3 turns` | 100.0% | `0.332` | `+0.244` |
| `before_mitigation` | `text` | `text_forensics_local_v2` | `adaptive_feedback_paraphraser_v2` | `4 turns` | 100.0% | `0.332` | `+0.244` |
| `before_mitigation` | `text` | `text_forensics_local_v2` | `adaptive_feedback_paraphraser_v2` | `5 turns` | 100.0% | `0.332` | `+0.244` |
| `before_mitigation` | `text` | `text_forensics_local_v2` | `adaptive_feedback_paraphraser_v2` | `6 turns` | 100.0% | `0.332` | `+0.244` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `adaptive_transform_search` | `1 queries` | 0.0% | `0.963` | `+0.000` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `adaptive_transform_search` | `10 queries` | 0.0% | `0.900` | `+0.062` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `adaptive_transform_search` | `25 queries` | 0.0% | `0.887` | `+0.075` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `adaptive_transform_search` | `40 queries` | 0.0% | `0.875` | `+0.087` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `adaptive_transform_search` | `50 queries` | 0.0% | `0.875` | `+0.087` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `adaptive_transform_search` | `60 queries` | 0.0% | `0.875` | `+0.087` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `adaptive_transform_search` | `75 queries` | 0.0% | `0.875` | `+0.087` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `adaptive_transform_search` | `100 queries` | 0.0% | `0.875` | `+0.087` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `adaptive_transform_search` | `150 queries` | 0.0% | `0.875` | `+0.087` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `square_linf` | `1 queries` | 0.0% | `0.713` | `+0.250` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `square_linf` | `10 queries` | 25.0% | `0.662` | `+0.300` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `square_linf` | `25 queries` | 25.0% | `0.650` | `+0.312` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `square_linf` | `50 queries` | 37.5% | `0.637` | `+0.325` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `square_linf` | `75 queries` | 37.5% | `0.637` | `+0.325` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `square_linf` | `100 queries` | 37.5% | `0.637` | `+0.325` |
| `after_mitigation` | `image` | `image_mobilenetv3_forensics_v2_hardened` | `square_linf` | `150 queries` | 37.5% | `0.637` | `+0.325` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `adaptive_transform_search` | `1 queries` | 0.0% | `0.769` | `+0.000` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `adaptive_transform_search` | `10 queries` | 0.0% | `0.700` | `+0.069` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `adaptive_transform_search` | `25 queries` | 0.0% | `0.700` | `+0.069` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `adaptive_transform_search` | `40 queries` | 0.0% | `0.694` | `+0.075` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `adaptive_transform_search` | `50 queries` | 0.0% | `0.650` | `+0.119` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `adaptive_transform_search` | `60 queries` | 12.5% | `0.650` | `+0.119` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `adaptive_transform_search` | `75 queries` | 12.5% | `0.650` | `+0.119` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `adaptive_transform_search` | `100 queries` | 12.5% | `0.650` | `+0.119` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `adaptive_transform_search` | `150 queries` | 12.5% | `0.650` | `+0.119` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `square_linf` | `1 queries` | 0.0% | `0.762` | `+0.006` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `square_linf` | `10 queries` | 0.0% | `0.694` | `+0.075` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `square_linf` | `25 queries` | 12.5% | `0.675` | `+0.094` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `square_linf` | `50 queries` | 25.0% | `0.650` | `+0.119` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `square_linf` | `75 queries` | 25.0% | `0.650` | `+0.119` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `square_linf` | `100 queries` | 25.0% | `0.650` | `+0.119` |
| `after_mitigation` | `video` | `video_efficientnet_b0_v2_hardened` | `square_linf` | `150 queries` | 25.0% | `0.650` | `+0.119` |
| `after_mitigation` | `text` | `text_forensics_local_v2_hardened` | `adaptive_feedback_paraphraser_v2` | `0 turns` | 0.0% | `0.594` | `+0.000` |
| `after_mitigation` | `text` | `text_forensics_local_v2_hardened` | `adaptive_feedback_paraphraser_v2` | `1 turns` | 37.5% | `0.475` | `+0.119` |
| `after_mitigation` | `text` | `text_forensics_local_v2_hardened` | `adaptive_feedback_paraphraser_v2` | `2 turns` | 37.5% | `0.475` | `+0.119` |
| `after_mitigation` | `text` | `text_forensics_local_v2_hardened` | `adaptive_feedback_paraphraser_v2` | `3 turns` | 50.0% | `0.463` | `+0.131` |
| `after_mitigation` | `text` | `text_forensics_local_v2_hardened` | `adaptive_feedback_paraphraser_v2` | `4 turns` | 50.0% | `0.463` | `+0.131` |
| `after_mitigation` | `text` | `text_forensics_local_v2_hardened` | `adaptive_feedback_paraphraser_v2` | `5 turns` | 50.0% | `0.463` | `+0.131` |
| `after_mitigation` | `text` | `text_forensics_local_v2_hardened` | `adaptive_feedback_paraphraser_v2` | `6 turns` | 50.0% | `0.463` | `+0.131` |

## 3. Hard-Negative Pool Exported for AI Fine-Tuning

- **Manifest JSONL:** `G:\College\Graduation Project\AEGIS-The-shield-against-synthetic-media\eval\datasets\hard_negatives\hard_negatives_manifest.jsonl`
- **Manifest CSV:** `G:\College\Graduation Project\AEGIS-The-shield-against-synthetic-media\eval\datasets\hard_negatives\hard_negatives_manifest.csv`
- **Total Hard Negatives Exported:** `24` (`{'image': 8, 'text': 8, 'video': 8}`)

## 4. Prioritized Hardening Recommendations

1. **[P0 — Vision Query Stability]** Deploy multi-view randomized smoothing (`HardenedVisionDefense`: 5 random jittered crops + JPEG-80 re-encoding + light noise average) before model scoring to disrupt greedy Square Attack trajectory monotonicity.
2. **[P0 — Output Quantization & Query-Burst Guard]** Quantize externally exposed detector confidences to `0.05` increments (or verdict-tier bands at the gateway) and rate-limit near-identical perceptual hash (`aHash`) probe bursts to block zeroth-order finite-difference and Square searches.
3. **[P1 — Text Window Floor Pooling]** Aggregate overlapping 3-sentence windows with a `max`/percentile floor (`HardenedTextDefense`) rather than whole-document mean alone so injecting human-like filler sentences cannot dilute synthetic regions.
4. **[P1 — Adversarial Retraining on Hard Negatives]** Fine-tune `OwensLab/commfor-model-384`, `EfficientNet-B0`, and `Desklib LoRA` on the exported `eval/datasets/hard_negatives/` manifest (paired Square Attack, adaptive transform, and multi-turn paraphrased positives).
5. **[P2 — Decision-Only External Exposure]** Keep raw float logits internal to the Judge arbitration bus while returning discrete confidence bands outside the trust boundary.
