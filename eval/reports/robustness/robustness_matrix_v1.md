# AEGIS Robustness Matrix v1 — detection rate vs perturbation strength

**Task:** Week 10 Cybersecurity Task 2 (joint AI/security) · **Harness:** `python -m eval.robustness.harness`
Decision threshold P(synthetic) ≥ 0.5. Evasion rate = synthetic samples detected when clean but missed after the perturbation. Strengths deliberately avoid the fine-tuning augmentations and the team's existing `jpeg75`/`jpeg50`/`resize0.5` eval variants (see `eval/robustness/perturbations.py`).

## detector_image — `commfor-model-384 (fp32 CPU)`

Dataset: Hemg/AI-Generated-vs-Real-Images-Datasets (seeded sample, see eval/DATA.md) · samples: 200 · generated 2026-11-18T17:28 UTC

| Perturbation | Strength | Detection rate | FPR | AUC | Evasion rate | Mean P(syn) synthetic / real |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| clean | 0 | 38% | 9% | 0.743 | 0% | 0.390 / 0.096 |
| jpeg | 90 | 40% | 8% | 0.745 | 3% | 0.389 / 0.092 |
| jpeg | 60 | 30% | 4% | 0.734 | 24% | 0.306 / 0.064 |
| jpeg | 40 | 24% | 4% | 0.705 | 39% | 0.250 / 0.052 |
| jpeg | 25 | 15% | 2% | 0.647 | 61% | 0.141 / 0.028 |
| resize | 0.75 | 36% | 9% | 0.742 | 5% | 0.382 / 0.098 |
| resize | 0.4 | 37% | 7% | 0.742 | 13% | 0.366 / 0.083 |
| resize | 0.25 | 25% | 2% | 0.679 | 45% | 0.253 / 0.037 |
| blur | 0.8 | 38% | 10% | 0.732 | 3% | 0.398 / 0.113 |
| blur | 1.6 | 38% | 10% | 0.713 | 11% | 0.376 / 0.106 |
| blur | 2.4 | 28% | 7% | 0.683 | 34% | 0.298 / 0.098 |
| noise | 4 | 42% | 8% | 0.753 | 8% | 0.411 / 0.103 |
| noise | 8 | 26% | 4% | 0.723 | 34% | 0.275 / 0.057 |
| noise | 14 | 17% | 3% | 0.675 | 55% | 0.187 / 0.041 |
| crop | 0.9 | 40% | 8% | 0.764 | 16% | 0.423 / 0.095 |
| crop | 0.7 | 51% | 10% | 0.813 | 13% | 0.533 / 0.111 |
| crop | 0.5 | 66% | 9% | 0.848 | 8% | 0.641 / 0.098 |

## detector_text — `desklib-v1.01-lora-finetuned-fp32`

Dataset: yaful/MAGE test_ood_set_gpt + test_ood_set_gpt_para (seeded sample, see eval/DATA.md) · samples: 180 · generated 2026-11-18T18:16 UTC

| Perturbation | Strength | Detection rate | FPR | AUC | Evasion rate | Mean P(syn) synthetic / real |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| clean | 0 | 100% | 27% | 0.996 | 0% | 0.993 / 0.288 |
| homoglyph | 0.03 | 98% | 10% | 0.993 | 2% | 0.966 / 0.188 |
| homoglyph | 0.1 | 95% | 13% | 0.977 | 5% | 0.913 / 0.242 |
| homoglyph | 0.25 | 88% | 42% | 0.871 | 12% | 0.763 / 0.429 |
| zero_width | 0.03 | 100% | 27% | 0.996 | 0% | 0.993 / 0.288 |
| zero_width | 0.1 | 100% | 27% | 0.996 | 0% | 0.993 / 0.288 |
| zero_width | 0.25 | 100% | 27% | 0.996 | 0% | 0.993 / 0.288 |
| paraphrase | 0.15 | 100% | 23% | 0.992 | 0% | 0.983 / 0.275 |
| paraphrase | 0.35 | 100% | 20% | 0.991 | 0% | 0.980 / 0.272 |
| paraphrase | 0.6 | 97% | 22% | 0.982 | 3% | 0.962 / 0.254 |
| gpt4_paraphrase | 1 | 98% | 27% | 0.987 | — | 0.972 / 0.288 |

_gpt4_paraphrase = independent GPT-4 paraphrases (not paired with the clean GPT-4 samples), so its evasion_rate is not defined; compare detection rates._
