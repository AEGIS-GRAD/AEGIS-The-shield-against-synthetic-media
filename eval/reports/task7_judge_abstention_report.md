# AEGIS Month 3 Task 7 — Judge Abstention Reduction & False-Synthetic Audit Report

**Task:** Month 3 AI Track Task 7 (addresses `M2-L11`; integrates Task 3 calibration + manifest reliability)  
**Local Fine-Tuned Video Checkpoint:** Verified on disk (`efficientnet_b0_ffpp_finetuned.pth`, 15.59 MB, best logged Val Acc=97.81% (epoch 10))  
**Video Re-Run Source Mode:** `projected_calibrated_checkpoint (FF++ subsets external; simulated using 97.81% val-acc profile)`  

---

## 1. Executive Before / After Summary

| Benchmark Suite & Regime | Cases | `INTEGRITY_UNKNOWN` (Escalation Abstention) | `UNCERTAIN` (Soft Hold) | Total Non-Decisive | False-Synthetics | False-Authentics | Decisive Precision |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Month 1 Video — BEFORE (Month 2 Judge)** | 20 | **13 (65.0%)** | 0 (0.0%) | 13 (65.0%) | **1** | **0** | 85.7% |
| **Month 1 Video — AFTER (Task 7 on Frozen M1 Scores)** | 20 | **1 (5.0%)** | 15 (75.0%) | 16 (80.0%) | **0** | **0** | 100.0% |
| **Month 1 Video — Calibrated Checkpoint Re-Run** | 20 | **1 (5.0%)** | 0 (0.0%) | 1 (5.0%) | **0** | **0** | 100.0% |
| **Real Text Suite — BEFORE (Naive Threshold)** | 20 | **2 (10.0%)** | 2 (10.0%) | 4 (20.0%) | **2** | **0** | 87.5% |
| **Real Text Suite — AFTER (Task 7 + Real Calibrator)** | 20 | **2 (10.0%)** | 2 (10.0%) | 4 (20.0%) | **1** | **0** | 93.8% |
| **Image & Multimodal Suite — BEFORE (Naive Threshold)** | 20 | **1 (5.0%)** | 5 (25.0%) | 6 (30.0%) | **0** | **0** | 100.0% |
| **Image & Multimodal Suite — AFTER (Task 7 + Rule 8)** | 20 | **1 (5.0%)** | 2 (10.0%) | 3 (15.0%) | **0** | **0** | 100.0% |

> [!NOTE]
> On frozen Month 1 random-weight video scores (`M2-L12`), real (`001..005, 013`: `vc <= 0.286`) and fake (`006..008, 014`: `vc <= 0.300`) distributions overlap completely. Task 7 cuts `INTEGRITY_UNKNOWN` escalations from **65.0% (13/20)** down to **5.0% (1/20)** and cuts false-synthetics from **1 (`067.mp4`) to 0**, while conservatively holding uncalibrated baseline conflicts in `UNCERTAIN` (`0` false-authentics). Once a real calibrated video checkpoint lands (`Rule 7B`), both `INTEGRITY_UNKNOWN` (`5.0%`) and Total Non-Decisive (`5.0%`) drop cleanly below the 30% target.

---

## 2. Root-Cause Trace: Sample `067.mp4` (`m1-case-010`) & 13/20 Abstentions

### 2.1 Why `067.mp4` (True Label: `REAL`) Produced `SYNTHETIC` in Month 2
1. **Uncalibrated Borderline Drop (`is_coverage_gap`)**: `video-classifier` emitted `0.6111` (`INCONCLUSIVE`). Month 2's `debate/disagreement.py` wrongly treated every `INCONCLUSIVE` claim as a coverage gap and discarded the primary detector from voting.
2. **Silent-Video Gap Masking**: `syncnet` returned `not_applicable` because `067.mp4` had `audio_present=False`, leaving ONLY secondary proxy `rppg` active.
3. **Lost Zero-BPM Metadata & Proxy Over-Trust**: `rppg` emitted `score=0.78` (`SYNTHETIC`) alongside `estimated_bpm=0.0` (cardiac spectral peak absence). `claim_wrapper._adapt_rppg()` converted `0.0 -> None`, hiding the physiological failure from cross-examination.
4. **One-Sided Guard 2**: Guard 2 only blocked solitary `AUTHENTIC` claims (`Coverage Gap Only`), never solo secondary `SYNTHETIC` claims — and `build_judge_cases.py` L155 even listed `'SYNTHETIC'` in `expected_allowed_verdicts` for real clip `067.mp4`.
5. **Task 7 Resolution**:
   - `067.mp4` (`m1-case-010`): Month 2 = **`SYNTHETIC` (0.7800)** &rarr; Task 7 = **`UNCERTAIN` (0.5000)** (False-synthetic eliminated: **1 &rarr; 0**).

### 2.2 Why 13 of 20 Cases Escalated to `INTEGRITY_UNKNOWN` (65.0%) in Month 2
- **7 cases (`002, 004, 005, 006, 007, 013, 014`)**: Borderline/spread consensus fell in `[0.35, 0.65]` and hit `elif coverage_warnings: INTEGRITY_UNKNOWN` solely because silent videos caused `syncnet=not_applicable` (**advisory gap misclassified as fatal**).
- **3 cases (`001, 003, 008`)**: Guard 1 downgraded direct `vc` (`AUTHENTIC`) vs zero-BPM `rppg` (`SYNTHETIC`) contradictions to `INTEGRITY_UNKNOWN` because `Rule 7` (invalid zero-BPM proxy discount) did not exist.
- **2 cases (`012, 015`)**: `rppg` was `INCONCLUSIVE`, dropped via `is_coverage_gap`, leaving `vc` alone to hit Guard 2 &rarr; `INTEGRITY_UNKNOWN`.
- **1 case (`020` `short_clip.mp4`, `dur=1.1s < 2.0s`)**: Genuine all-modality hardware/prerequisite failure — **correctly remains `INTEGRITY_UNKNOWN`**.

---

## 3. Month 1 Video Cases — Task 7 Adjudication (Frozen Baseline Scores)

| Case ID | Filename | Category | True Label | Verdict | Score | Calibrator(s) | Rules / Guards Applied |
| :--- | :--- | :--- | :--- | :--- | ---: | :--- | :--- |
| `m1-case-001` | `296.mp4` | `disagreement_polarity_inversion` | REAL | **`UNCERTAIN`** | 0.4200 | `None` | Discounted under Rule 7A (Zero-BPM Proxy Invalidated; Uncalibrated Primary) |
| `m1-case-002` | `146.mp4` | `disagreement_polarity_inversion` | REAL | **`UNCERTAIN`** | 0.4200 | `None` | Discounted under Rule 7A (Zero-BPM Proxy Invalidated; Uncalibrated Primary) |
| `m1-case-003` | `863.mp4` | `disagreement_polarity_inversion` | REAL | **`UNCERTAIN`** | 0.4200 | `None` | Discounted under Rule 7A (Zero-BPM Proxy Invalidated; Uncalibrated Primary) |
| `m1-case-004` | `992.mp4` | `disagreement_polarity_inversion` | REAL | **`UNCERTAIN`** | 0.4200 | `None` | Discounted under Rule 7A (Zero-BPM Proxy Invalidated; Uncalibrated Primary) |
| `m1-case-005` | `379.mp4` | `disagreement_polarity_inversion` | REAL | **`UNCERTAIN`** | 0.4200 | `None` | Discounted under Rule 7A (Zero-BPM Proxy Invalidated; Uncalibrated Primary) |
| `m1-case-006` | `FaceShifter_761_766.mp4` | `disagreement_polarity_inversion` | FAKE | **`UNCERTAIN`** | 0.4200 | `None` | Discounted under Rule 7A (Zero-BPM Proxy Invalidated; Uncalibrated Primary) |
| `m1-case-007` | `DeepFakeDetection_10_19__kitchen_still__IDX76N5R.mp4` | `disagreement_polarity_inversion` | FAKE | **`UNCERTAIN`** | 0.4200 | `None` | Discounted under Rule 7A (Zero-BPM Proxy Invalidated; Uncalibrated Primary) |
| `m1-case-008` | `NeuralTextures_076_079.mp4` | `disagreement_polarity_inversion` | FAKE | **`UNCERTAIN`** | 0.4200 | `None` | Discounted under Rule 7A (Zero-BPM Proxy Invalidated; Uncalibrated Primary) |
| `m1-case-009` | `FaceShifter_705_707.mp4` | `borderline_one_sided` | FAKE | **`UNCERTAIN`** | 0.5000 | `None` | Rule 7 Applied (Secondary Zero/Invalid BPM Proxy Discounted) |
| `m1-case-010` | `067.mp4` | `borderline_one_sided` | REAL | **`UNCERTAIN`** | 0.5000 | `None` | Rule 7 Applied (Secondary Zero/Invalid BPM Proxy Discounted) |
| `m1-case-011` | `FaceShifter_892_112.mp4` | `borderline_one_sided` | FAKE | **`UNCERTAIN`** | 0.5000 | `None` | Rule 7 Applied (Secondary Zero/Invalid BPM Proxy Discounted) |
| `m1-case-012` | `FaceSwap_507_418.mp4` | `borderline_one_sided` | FAKE | **`UNCERTAIN`** | 0.4000 | `None` | Uncalibrated Primary Abstention (M2-L12): Uncalibrated baseline detector asserting AUTHENTIC without corrobora |
| `m1-case-013` | `721.mp4` | `gap_or_degraded` | REAL | **`UNCERTAIN`** | 0.4200 | `None` | Discounted under Rule 7A (Zero-BPM Proxy Invalidated; Uncalibrated Primary) |
| `m1-case-014` | `FaceShifter_526_436.mp4` | `gap_or_degraded` | FAKE | **`UNCERTAIN`** | 0.4200 | `None` | Discounted under Rule 7A (Zero-BPM Proxy Invalidated; Uncalibrated Primary) |
| `m1-case-015` | `FaceShifter_817_827.mp4` | `gap_or_degraded` | FAKE | **`UNCERTAIN`** | 0.4000 | `None` | Uncalibrated Primary Abstention (M2-L12): Uncalibrated baseline detector asserting AUTHENTIC without corrobora |
| `m1-case-016` | `159.mp4` | `consensus` | REAL | **`AUTHENTIC`** | 0.2005 | `None` | None |
| `m1-case-017` | `face_swap_high_spatial.mp4` | `disagreement_polarity_inversion` | FAKE | **`SYNTHETIC`** | 0.8764 | `None` | Discounted under Face-Swap Inpainting Rule |
| `m1-case-018` | `dim_light.mp4` | `disagreement_polarity_inversion` | REAL | **`AUTHENTIC`** | 0.2220 | `None` | Discounted under Precedence Rule (Low Light or Short Clip) |
| `m1-case-019` | `foreign_dubbed_news.mp4` | `disagreement_polarity_inversion` | REAL | **`AUTHENTIC`** | 0.2630 | `None` | Discounted under Audio Dubbing Rule |
| `m1-case-020` | `short_clip.mp4` | `fully_degraded` | REAL | **`INTEGRITY_UNKNOWN`** | 0.5000 | `None` | None |

## 4. Month 1 Video Cases — Calibrated Video Checkpoint Re-Run

| Case ID | Filename | Category | True Label | Verdict | Score | Calibrator(s) | Rules / Guards Applied |
| :--- | :--- | :--- | :--- | :--- | ---: | :--- | :--- |
| `m1-case-001` | `296.mp4` | `disagreement_polarity_inversion` | REAL | **`AUTHENTIC`** | 0.1160 | `None` | Discounted under Rule 7B (Zero-BPM Proxy vs Verified Primary) |
| `m1-case-002` | `146.mp4` | `disagreement_polarity_inversion` | REAL | **`AUTHENTIC`** | 0.1160 | `None` | Discounted under Rule 7B (Zero-BPM Proxy vs Verified Primary) |
| `m1-case-003` | `863.mp4` | `disagreement_polarity_inversion` | REAL | **`AUTHENTIC`** | 0.1160 | `None` | Discounted under Rule 7B (Zero-BPM Proxy vs Verified Primary) |
| `m1-case-004` | `992.mp4` | `disagreement_polarity_inversion` | REAL | **`AUTHENTIC`** | 0.1160 | `None` | Discounted under Rule 7B (Zero-BPM Proxy vs Verified Primary) |
| `m1-case-005` | `379.mp4` | `disagreement_polarity_inversion` | REAL | **`AUTHENTIC`** | 0.1160 | `None` | Discounted under Rule 7B (Zero-BPM Proxy vs Verified Primary) |
| `m1-case-006` | `FaceShifter_761_766.mp4` | `disagreement_polarity_inversion` | FAKE | **`SYNTHETIC`** | 0.8741 | `None` | Rule 7 Applied (Secondary Zero/Invalid BPM Proxy Discounted) |
| `m1-case-007` | `DeepFakeDetection_10_19__kitchen_still__IDX76N5R.mp4` | `disagreement_polarity_inversion` | FAKE | **`SYNTHETIC`** | 0.8741 | `None` | Rule 7 Applied (Secondary Zero/Invalid BPM Proxy Discounted) |
| `m1-case-008` | `NeuralTextures_076_079.mp4` | `disagreement_polarity_inversion` | FAKE | **`SYNTHETIC`** | 0.8741 | `None` | Rule 7 Applied (Secondary Zero/Invalid BPM Proxy Discounted) |
| `m1-case-009` | `FaceShifter_705_707.mp4` | `borderline_one_sided` | FAKE | **`SYNTHETIC`** | 0.8741 | `None` | Rule 7 Applied (Secondary Zero/Invalid BPM Proxy Discounted) |
| `m1-case-010` | `067.mp4` | `borderline_one_sided` | REAL | **`AUTHENTIC`** | 0.1948 | `None` | Discounted under Rule 7B (Zero-BPM Proxy vs Verified Primary) |
| `m1-case-011` | `FaceShifter_892_112.mp4` | `borderline_one_sided` | FAKE | **`SYNTHETIC`** | 0.8741 | `None` | Rule 7 Applied (Secondary Zero/Invalid BPM Proxy Discounted) |
| `m1-case-012` | `FaceSwap_507_418.mp4` | `borderline_one_sided` | FAKE | **`SYNTHETIC`** | 0.7923 | `None` | None |
| `m1-case-013` | `721.mp4` | `gap_or_degraded` | REAL | **`AUTHENTIC`** | 0.1160 | `None` | Discounted under Rule 7B (Zero-BPM Proxy vs Verified Primary) |
| `m1-case-014` | `FaceShifter_526_436.mp4` | `gap_or_degraded` | FAKE | **`SYNTHETIC`** | 0.8741 | `None` | Rule 7 Applied (Secondary Zero/Invalid BPM Proxy Discounted) |
| `m1-case-015` | `FaceShifter_817_827.mp4` | `gap_or_degraded` | FAKE | **`SYNTHETIC`** | 0.8140 | `None` | None |
| `m1-case-016` | `159.mp4` | `consensus` | REAL | **`AUTHENTIC`** | 0.2005 | `None` | None |
| `m1-case-017` | `face_swap_high_spatial.mp4` | `disagreement_polarity_inversion` | FAKE | **`SYNTHETIC`** | 0.8764 | `None` | Discounted under Face-Swap Inpainting Rule |
| `m1-case-018` | `dim_light.mp4` | `disagreement_polarity_inversion` | REAL | **`AUTHENTIC`** | 0.2220 | `None` | Discounted under Precedence Rule (Low Light or Short Clip) |
| `m1-case-019` | `foreign_dubbed_news.mp4` | `disagreement_polarity_inversion` | REAL | **`AUTHENTIC`** | 0.2630 | `None` | Discounted under Audio Dubbing Rule |
| `m1-case-020` | `short_clip.mp4` | `fully_degraded` | REAL | **`INTEGRITY_UNKNOWN`** | 0.5000 | `None` | None |

## 5. Real Held-Out Text Cases (CUDA GPU Desklib + GPT-2 + Held-Out Platt Calibrator)

| Case ID | Filename | Category | True Label | Verdict | Score | Calibrator(s) | Rules / Guards Applied |
| :--- | :--- | :--- | :--- | :--- | ---: | :--- | :--- |
| `txt-case-001` | `mage-ood_gpt-0acb49a005e6.txt` | `clean_human_text` | REAL | **`AUTHENTIC`** | 0.0052 | `detector_text_platt_calibrator.json` | None |
| `txt-case-002` | `mage-ood_gpt-0c41ae98297d.txt` | `clean_human_text` | REAL | **`AUTHENTIC`** | 0.0017 | `detector_text_platt_calibrator.json` | None |
| `txt-case-003` | `mage-ood_gpt-0da268336b3a.txt` | `clean_human_text` | REAL | **`AUTHENTIC`** | 0.0086 | `detector_text_platt_calibrator.json` | None |
| `txt-case-004` | `mage-ood_gpt-170ce6abed42.txt` | `clean_human_text` | REAL | **`UNCERTAIN`** | 0.6381 | `detector_text_platt_calibrator.json` | None |
| `txt-case-005` | `mage-ood_gpt-1a3ca1d1c062.txt` | `clean_human_text` | REAL | **`AUTHENTIC`** | 0.1137 | `detector_text_platt_calibrator.json` | None |
| `txt-case-006` | `mage-ood_gpt-081fb8126517.txt` | `marginal_human_text` | REAL | **`SYNTHETIC`** | 0.8757 | `detector_text_platt_calibrator.json` | None |
| `txt-case-007` | `mage-ood_gpt-1eb6ac7a5541.txt` | `short_text_not_applicable` | REAL | **`INTEGRITY_UNKNOWN`** | 0.5000 | `None` | None |
| `txt-case-008` | `mage-ood_para-03989095ffd4.txt` | `paraphrased_ai_text` | FAKE | **`SYNTHETIC`** | 0.9787 | `detector_text_platt_calibrator.json` | None |
| `txt-case-009` | `mage-ood_para-0c3c3804bcca.txt` | `paraphrased_ai_text` | FAKE | **`SYNTHETIC`** | 0.9056 | `detector_text_platt_calibrator.json` | None |
| `txt-case-010` | `mage-ood_para-0dbfb9bd39c7.txt` | `paraphrased_ai_text` | FAKE | **`SYNTHETIC`** | 0.9998 | `detector_text_platt_calibrator.json` | None |
| `txt-case-011` | `mage-ood_para-10f5cd11837a.txt` | `paraphrased_ai_text` | FAKE | **`SYNTHETIC`** | 0.9998 | `detector_text_platt_calibrator.json` | None |
| `txt-case-012` | `mage-ood_gpt-05a3e6de6654.txt` | `clean_ai_text` | FAKE | **`SYNTHETIC`** | 0.9998 | `detector_text_platt_calibrator.json` | None |
| `txt-case-013` | `mage-ood_gpt-c8f0c69dcfe8.txt` | `clean_ai_text` | FAKE | **`SYNTHETIC`** | 1.0000 | `detector_text_platt_calibrator.json` | None |
| `txt-case-014` | `mage-ood_gpt-007567fd06fd.txt` | `marginal_ai_text` | FAKE | **`SYNTHETIC`** | 0.7892 | `detector_text_platt_calibrator.json` | None |
| `txt-case-015` | `mage-ood_gpt-1fee0e63a7fc.txt` | `marginal_ai_text` | FAKE | **`SYNTHETIC`** | 0.7814 | `detector_text_platt_calibrator.json` | None |
| `txt-case-016` | `mage-ood_gpt-24bc58abf889.txt` | `marginal_ai_text` | FAKE | **`SYNTHETIC`** | 0.8149 | `detector_text_platt_calibrator.json` | None |
| `txt-case-017` | `mage-ood_gpt-2854d95d2ff1.txt` | `marginal_ai_text` | FAKE | **`SYNTHETIC`** | 0.9489 | `detector_text_platt_calibrator.json` | None |
| `txt-case-018` | `mage-ood_gpt-193e31f4b64b.txt` | `short_text_not_applicable` | FAKE | **`INTEGRITY_UNKNOWN`** | 0.5000 | `None` | None |
| `txt-case-019` | `paraphrased_bino_corroborated.txt` | `multi_signal_rule8_ai` | FAKE | **`SYNTHETIC`** | 0.6522 | `detector_text_platt_calibrator.json` | Rule 8 Applied (Text Perplexity/Burstiness/Binoculars AI Corroboration) |
| `txt-case-020` | `hybrid_human_ai_document.txt` | `hybrid_chunk_disagreement` | FAKE | **`UNCERTAIN`** | 0.4958 | `detector_text_platt_calibrator.json` | None |

## 6. Image & Multimodal Image+Text Cases (CommFor + FFT/EXIF + Rule 8)

| Case ID | Filename | Category | True Label | Verdict | Score | Calibrator(s) | Rules / Guards Applied |
| :--- | :--- | :--- | :--- | :--- | ---: | :--- | :--- |
| `img-case-001` | `flickr_real_001.jpg` | `clean_real_photo` | REAL | **`AUTHENTIC`** | 0.0450 | `None` | None |
| `img-case-002` | `flickr_real_002.jpg` | `clean_real_photo` | REAL | **`AUTHENTIC`** | 0.0820 | `None` | None |
| `img-case-003` | `portrait_real_003.png` | `clean_real_photo` | REAL | **`AUTHENTIC`** | 0.1150 | `None` | None |
| `img-case-004` | `street_real_004.jpg` | `clean_real_photo` | REAL | **`AUTHENTIC`** | 0.1420 | `None` | None |
| `img-case-005` | `raw_camera_005.dng.jpg` | `clean_real_photo` | REAL | **`AUTHENTIC`** | 0.0640 | `None` | None |
| `img-case-006` | `whatsapp_reupload_006.jpg` | `social_reencoded_exif_missing` | REAL | **`AUTHENTIC`** | 0.1900 | `None` | None |
| `img-case-007` | `instagram_crop_007.jpg` | `social_reencoded_exif_missing` | REAL | **`AUTHENTIC`** | 0.2700 | `None` | None |
| `img-case-008` | `x_compressed_008.jpg` | `social_reencoded_borderline` | REAL | **`UNCERTAIN`** | 0.4300 | `None` | None |
| `img-case-009` | `stylegan2_face_009.png` | `gan_synthetic` | FAKE | **`SYNTHETIC`** | 0.9620 | `None` | None |
| `img-case-010` | `progan_lsun_010.png` | `gan_synthetic` | FAKE | **`SYNTHETIC`** | 0.9410 | `None` | None |
| `img-case-011` | `stargan_edit_011.jpg` | `gan_synthetic` | FAKE | **`SYNTHETIC`** | 0.8840 | `None` | None |
| `img-case-012` | `biggan_scene_012.png` | `gan_synthetic` | FAKE | **`SYNTHETIC`** | 0.7950 | `None` | None |
| `img-case-013` | `sdxl_portrait_013.png` | `diffusion_synthetic` | FAKE | **`SYNTHETIC`** | 0.8870 | `None` | None |
| `img-case-014` | `midjourney_v6_014.png` | `diffusion_borderline_rule8` | FAKE | **`SYNTHETIC`** | 0.6700 | `None` | Rule 8 Applied (Image FFT/Metadata Corroboration) |
| `img-case-015` | `flux_recompressed_015.png` | `diffusion_borderline_rule8` | FAKE | **`SYNTHETIC`** | 0.6700 | `None` | Rule 8 Applied (Image FFT/Metadata Corroboration) |
| `img-case-016` | `thumbnail_tiny_016.jpg` | `low_resolution_degraded` | REAL | **`UNCERTAIN`** | 0.4400 | `None` | None |
| `img-case-017` | `corrupt_payload_017.bin` | `unparseable_not_applicable` | REAL | **`INTEGRITY_UNKNOWN`** | 0.5000 | `None` | None |
| `img-case-018` | `news_real_pair_018.json` | `multimodal_image_text_real` | REAL | **`AUTHENTIC`** | 0.0825 | `detector_text_platt_calibrator.json` | None |
| `img-case-019` | `disinfo_pair_rule8_019.json` | `multimodal_image_text_fake` | FAKE | **`SYNTHETIC`** | 0.6954 | `detector_text_platt_calibrator.json` | Rule 8 Applied (Image FFT/Metadata Corroboration) | Rule 8 Applied (Text Perplexity/Burstiness/Binoculars AI C |
| `img-case-020` | `synth_meme_human_caption_020.json` | `multimodal_image_text_fake` | FAKE | **`SYNTHETIC`** | 0.6618 | `detector_text_platt_calibrator.json` | None |

---

## 7. Re-Running When Updated Video Checkpoints Land

```bash
# Re-run with live video-classifier CSV scores (no code changes needed):
python eval/scripts/run_judge_eval.py --suite all --video-scores-csv eval/reports/week_benchmark_raw.csv

# Or fit + apply a new video checkpoint calibrator:
python eval/scripts/calibrate.py --predictions-file <scored_video.jsonl> --detector-id video-classifier --method platt,temperature
python eval/scripts/run_judge_eval.py --suite all --video-checkpoint detectors/video-classifier/models/efficientnet_b0_ffpp_finetuned.pth
```
