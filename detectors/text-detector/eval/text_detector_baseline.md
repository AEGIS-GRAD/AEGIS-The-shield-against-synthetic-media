# AEGIS Text Detector (`desklib/ai-text-detector-v1.01`) Baseline Note

- **Generated:** 2026-11-13 23:49 UTC
- **Dataset:** `D:\Grad Projectt eccuuuuu\eval\data\text\text_eval_manifest.jsonl` (**Interim public dataset from `yaful/MAGE`** pending AI Task 4 final text benchmark)
- **Model Status:** As-is `desklib/ai-text-detector-v1.01` (`microsoft/deberta-v3-large`), zero fine-tuning applied (Task 3 owns LoRA adaptation).

## 1. Headline Performance & GPU Budget

| Mode | Device / Dtype | N | AUROC (raw) | TPR @ 1% FPR | Cond. Acc@0.5 | Not Applicable | Avg ms | P95 ms | Peak VRAM (MB) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `as_is_512tok` | CUDA fp16 | 440 | 0.931 | 0.5107 | 0.8545 | 0 | 95.53 | 97.49 | 1905.83 |
| `service_detect` | CUDA fp16 | 440 | 0.8219 | 0.4964 | 0.8794 | 67 | 225.65 | 643.46 | 1913.95 |

## Breakdown — `as_is_512tok`

### By Length Bucket

| Length Bucket | N | AUROC | TPR @ 1% FPR | Accuracy@0.5 | F1@0.5 |
|---|---:|---:|---:|---:|---:|
| `long_500_plus` | 73 | 0.9647 | 0.6591 | 0.9315 | 0.9412 |
| `marginal_40_149` | 147 | 0.8937 | 0.2444 | 0.8027 | 0.8398 |
| `medium_150_499` | 153 | 0.9862 | 0.8039 | 0.9281 | 0.9458 |
| `short_lt40` | 67 | 0.7263 | 0.1818 | 0.7164 | 0.7912 |

### By Generator / Subset

| Generator | Class | N | Pred AI Rate (@0.5) | Mean Score |
|---|---|---:|---:|---:|
| `13B` | ai | 4 | 1.0 | 0.963 |
| `30B` | ai | 4 | 0.75 | 0.7967 |
| `65B` | ai | 3 | 0.6667 | 0.5668 |
| `7B` | ai | 4 | 1.0 | 0.9905 |
| `GLM130B` | ai | 4 | 0.75 | 0.7343 |
| `bloom_7b` | ai | 4 | 0.75 | 0.7843 |
| `flan_t5_base` | ai | 3 | 1.0 | 0.9982 |
| `flan_t5_large` | ai | 3 | 1.0 | 0.9251 |
| `flan_t5_small` | ai | 2 | 1.0 | 0.9375 |
| `flan_t5_xl` | ai | 3 | 1.0 | 0.8398 |
| `flan_t5_xxl` | ai | 4 | 1.0 | 0.9723 |
| `gpt-3.5-trubo` | ai | 4 | 1.0 | 0.8916 |
| `gpt-4` | ai | 120 | 0.9833 | 0.9541 |
| `gpt-4_para` | ai | 44 | 0.9545 | 0.927 |
| `gpt-paraphraser_para` | ai | 36 | 0.5833 | 0.5614 |
| `gpt_j` | ai | 4 | 0.75 | 0.8151 |
| `gpt_neox` | ai | 4 | 0.75 | 0.7933 |
| `human` | human | 160 | 0.2 | 0.2477 |
| `opt_1.3b` | ai | 4 | 0.75 | 0.722 |
| `opt_125m` | ai | 4 | 1.0 | 0.9885 |
| `opt_13b` | ai | 4 | 0.75 | 0.8531 |
| `opt_2.7b` | ai | 4 | 1.0 | 0.9303 |
| `opt_30b` | ai | 4 | 0.5 | 0.6859 |
| `opt_350m` | ai | 4 | 0.75 | 0.7558 |
| `opt_6.7b` | ai | 4 | 0.75 | 0.7406 |
| `opt_iml_30b` | ai | 2 | 0.5 | 0.5707 |

## Breakdown — `service_detect`

### By Length Bucket

| Length Bucket | N | AUROC | TPR @ 1% FPR | Accuracy@0.5 | F1@0.5 |
|---|---:|---:|---:|---:|---:|
| `long_500_plus` | 73 | 0.9765 | 0.8636 | 0.9315 | 0.9412 |
| `marginal_40_149` | 147 | 0.8834 | 0.1444 | 0.8027 | 0.8398 |
| `medium_150_499` | 153 | 0.9856 | 0.7549 | 0.9281 | 0.9458 |
| `short_lt40` | 67 | 0.5 | 0.0 | 0.6567 | 0.7928 |

### By Generator / Subset

| Generator | Class | N | Pred AI Rate (@0.5) | Mean Score |
|---|---|---:|---:|---:|
| `13B` | ai | 4 | 1.0 | 0.8286 |
| `30B` | ai | 4 | 1.0 | 0.7825 |
| `65B` | ai | 3 | 0.6667 | 0.6728 |
| `7B` | ai | 4 | 1.0 | 0.8271 |
| `GLM130B` | ai | 4 | 0.75 | 0.6918 |
| `bloom_7b` | ai | 4 | 1.0 | 0.8414 |
| `flan_t5_base` | ai | 3 | 1.0 | 0.7465 |
| `flan_t5_large` | ai | 3 | 1.0 | 0.7139 |
| `flan_t5_small` | ai | 2 | 1.0 | 0.5559 |
| `flan_t5_xl` | ai | 3 | 1.0 | 0.7062 |
| `flan_t5_xxl` | ai | 4 | 1.0 | 0.7825 |
| `gpt-3.5-trubo` | ai | 4 | 1.0 | 0.8525 |
| `gpt-4` | ai | 120 | 0.9833 | 0.8479 |
| `gpt-4_para` | ai | 44 | 0.9545 | 0.8238 |
| `gpt-paraphraser_para` | ai | 36 | 0.6111 | 0.5756 |
| `gpt_j` | ai | 4 | 0.75 | 0.7413 |
| `gpt_neox` | ai | 4 | 1.0 | 0.8465 |
| `human` | human | 160 | 0.275 | 0.2546 |
| `opt_1.3b` | ai | 4 | 1.0 | 0.7798 |
| `opt_125m` | ai | 4 | 1.0 | 0.8465 |
| `opt_13b` | ai | 4 | 1.0 | 0.8017 |
| `opt_2.7b` | ai | 4 | 1.0 | 0.8349 |
| `opt_30b` | ai | 4 | 0.75 | 0.7362 |
| `opt_350m` | ai | 4 | 1.0 | 0.7636 |
| `opt_6.7b` | ai | 4 | 0.75 | 0.7359 |
| `opt_iml_30b` | ai | 2 | 0.5 | 0.6568 |
