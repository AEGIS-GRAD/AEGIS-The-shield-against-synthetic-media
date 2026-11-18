# Robustness Matrix v1 — Findings

**Task:** Week 10 Cybersecurity Task 2 (joint AI/security) · **Date:** 2026-11-18
**Matrix:** [robustness_matrix_v1.md](robustness_matrix_v1.md) · per-sample scores: `detector_image_scores.csv`, `detector_text_scores.csv`
**Harness:** `python -m eval.robustness.harness {image,text} [--http URL]` (`eval/robustness/`, unit tests `eval/tests/test_robustness_perturbations.py`)
**Depends on:** Week 9 AI Tasks 1–3 (image detector, text detector, fine-tuned weights), all merged.

## Image detector (Community Forensics ViT-S/384, 100 AI + 100 real web images)

1. **The clean baseline is weak on this data:** 38% detection and 9% FPR at P ≥ 0.5, AUC 0.74. The web AI-art images are out of
   distribution for the model. Read the matrix as *relative* movement, and re-run it on the OpenFake Task 4 set when it is staged.
2. **Cheap, everyday transformations evade it.** Of the AI images detected when clean, these share are missed afterwards:

   | Transformation | Evasion | Detection |
   |---|:-:|:-:|
   | JPEG quality 60 (typical social-media re-encode) | 24% | 30% |
   | JPEG quality 25 | **61%** | 15% |
   | Gaussian noise σ = 14 | **55%** | 17% |
   | 4× downscale then upscale | 45% | 25% |
   | Gaussian blur σ = 2.4 | 34% | 28% |

   False positives also *fall* under these transformations. The detector reads compression and noise as "real camera"
   evidence, so an attacker gains on both axes.
3. **Cropping raises detection (50% centre crop: 66%, AUC 0.85).** The service shrinks the whole image to 384×384, which
   destroys the high-frequency generator traces that the downscaling attack also targets. **Cheap fix for the AI team:**
   score several 384-px tiles at native resolution and take the maximum (or a calibrated mean), instead of one global resize.

## Text detector (desklib v1.01 + team LoRA, MAGE out-of-distribution GPT-4 set, 60 per class)

1. **Evasion robustness is good.** Detection stays ≥ 88% under every perturbation. Rule-based paraphrase at a 60% rate still
   gets 97%, and **real GPT-4 paraphrases are still detected 98% of the time**, which was the task's key test for desklib.
2. **Zero-width injection has no effect at any rate.** The service's own ingest (NFKC + format-character stripping) removes it
   before the model runs. This is a working defence, now covered by a regression test.
3. **Homoglyphs survive NFKC.** At 25% substitution, detection drops to 88% and false positives on *human* text rise from 27% to
   42%. **Fix:** fold Unicode confusables (UTS #39 skeleton) in `detectors/text-detector/ingest.py`. The Week 9 gateway validator
   (`security/gateway/validator/app/content_safety.py`, merged in #91) applies the same NFKC + zero-width stripping but does
   not fold confusables either, so homoglyphs currently pass both layers.
4. **The real weakness is false positives, not evasion:** 27% of human-written MAGE texts score ≥ 0.5 (mean P = 0.29). The
   threshold or calibration needs AI-team attention before text verdicts carry weight.

## Caveats

* In-process runs use fp32 on CPU; the services use fp16 on GPU (same weights and preprocessing).
* Sample sizes are small (200 images, 60 texts per class). Treat differences under about ±10 points as noise.
* Image labels come from the uploader of a web-scraped dataset (see `eval/DATA.md`).
* The per-sample score CSVs are ready input for the AI team's hard-negative pool (Week 11 AI work).
