# AEGIS Red-Team Poisoning Log (Judge & Planner)

- **Total Attack Scenarios:** 56
- **Oversight Cases Evaluated:** 44
- **Simple Weighted Averaging Flip Rate:** **84.1%** (37/44)
- **LLM Judge Flip Rate:** **79.5%** (35/44)
- **Deterministic Judge Flip Rate:** **0.0%** (0/44)
- **Unmitigated Baseline Attack Success Rate (ASR):** **82.1%** (46/56)
- **Mitigated System Attack Success Rate (ASR):** **0.0%** (0/56)
- **Benign Control Preservation:** 4/4 controls preserved without collateral degradation

## 1. Attack Category Summary

| Category | Cases | Baseline ASR | Mitigated ASR | Weighted Flips (%) | LLM Flips (%) | Det Flips (%) | Primary Mitigation |
|---|---:|---:|---:|---:|---:|---:|---|
| `miscalibrated_overconfidence` | 8 | 75.0% | 0.0% | 100.0% | 100.0% | 0.0% | Structural Precedence & Quorum Guards |
| `rogue_outlier_injection` | 10 | 80.0% | 0.0% | 100.0% | 100.0% | 0.0% | Structural Precedence & Quorum Guards |
| `spoofed_corroboration_and_flag_poisoning` | 10 | 80.0% | 0.0% | 30.0% | 10.0% | 0.0% | Structural Precedence & Quorum Guards |
| `cybersecurity_task2_perturbations` | 8 | 50.0% | 0.0% | 100.0% | 100.0% | 0.0% | Structural Precedence & Quorum Guards |
| `compound_hard_negatives` | 8 | 100.0% | 0.0% | 100.0% | 100.0% | 0.0% | Structural Precedence & Quorum Guards |
| `manifest_reliability_feedback_poisoning` | 6 | 100.0% | 0.0% | 100.0% | 100.0% | 0.0% | Structural Precedence & Quorum Guards |
| `adversarial_media_and_telemetry_cost_poisoning` | 6 | 100.0% | 0.0% | 100.0% | 100.0% | 0.0% | Structural Precedence & Quorum Guards |

## 2. Detailed Scenario Execution Log

| ID | Modality | Scenario | Clean | Injected Detector | Weighted Verdict | LLM Verdict | Det Verdict | Flips (W / L / D) |
|---|---|---|---|---|---|---|---|:---:|
| `PS-A01` | `video` | Tampered confidence vs raw_score on video-classifier (0.99 vs raw 0.22) | `AUTHENTIC` | `video-classifier=0.99` | `SYNTHETIC` | `SYNTHETIC` | `UNCERTAIN` | `FLIP / FLIP / OK` |
| `PS-A02` | `image` | Miscalibrated image-mirror confidence (0.99 vs raw 0.28) | `AUTHENTIC` | `image-mirror=0.99` | `SYNTHETIC` | `SYNTHETIC` | `UNCERTAIN` | `FLIP / FLIP / OK` |
| `PS-A03` | `text` | Miscalibrated text-desklib confidence (0.99 vs raw 0.25) | `AUTHENTIC` | `text-desklib=0.99` | `SYNTHETIC` | `SYNTHETIC` | `UNCERTAIN` | `FLIP / FLIP / OK` |
| `PS-A04` | `video` | False-negative raw_score tampering (0.001 AUTHENTIC vs raw 0.85) | `SYNTHETIC` | `video-classifier=0.001` | `UNCERTAIN` | `UNCERTAIN` | `SYNTHETIC` | `FLIP / FLIP / OK` |
| `PS-A05` | `audio` | Tampered AASIST confidence (0.98 vs raw 0.20) forcing Rule 5 | `AUTHENTIC` | `aasist=0.98` | `UNCERTAIN` | `SYNTHETIC` | `UNCERTAIN` | `FLIP / FLIP / OK` |
| `PS-A06` | `image` | Single-detector uncorroborated 0.999 saturation (raw=0.52) | `AUTHENTIC` | `detector_image=0.999` | `SYNTHETIC` | `SYNTHETIC` | `UNCERTAIN` | `FLIP / FLIP / OK` |
| `PS-A07` | `video` | Miscalibrated streaming rPPG confidence (0.98 vs raw 0.31) on live feed | `AUTHENTIC` | `streaming-rppg=0.98` | `UNCERTAIN` | `SYNTHETIC` | `UNCERTAIN` | `FLIP / FLIP / OK` |
| `PS-A08` | `text` | Miscalibrated text-perplexity spike (0.99 vs raw 0.30) on essay | `AUTHENTIC` | `text-perplexity=0.99` | `UNCERTAIN` | `SYNTHETIC` | `UNCERTAIN` | `FLIP / FLIP / OK` |
| `PS-B01` | `multimodal` | Rogue AASIST outlier (0.98) hijacking Rule 5 against 3 AUTHENTIC peers | `AUTHENTIC` | `aasist=0.98` | `UNCERTAIN` | `UNCERTAIN` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-B02` | `video` | Rogue video-classifier outlier (0.97) hijacking Rules 3 & 6 | `AUTHENTIC` | `video-classifier=0.97` | `UNCERTAIN` | `UNCERTAIN` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-B03` | `image` | Rogue image-mirror outlier (0.96) discounting clean frequency & EXIF | `AUTHENTIC` | `image-mirror=0.96` | `UNCERTAIN` | `SYNTHETIC` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-B04` | `text` | Rogue text-desklib outlier (0.96) discounting authentic stylometry/perplexity | `AUTHENTIC` | `text-desklib=0.96` | `UNCERTAIN` | `SYNTHETIC` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-B05` | `audio` | Single AASIST spike (0.96) without AV corroboration attempting Rule 5 override | `AUTHENTIC` | `aasist=0.96` | `UNCERTAIN` | `SYNTHETIC` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-B06` | `image` | Rogue image-frequency detector (0.95) outlier on high-contrast photo | `AUTHENTIC` | `image-frequency=0.95` | `UNCERTAIN` | `SYNTHETIC` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-B07` | `text` | Rogue stylometry outlier (0.95) against clean neural desklib and perplexity | `AUTHENTIC` | `text-stylometry=0.95` | `UNCERTAIN` | `SYNTHETIC` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-B08` | `video` | Heavy H.264 social media compression causing video-classifier (0.93) false alarm | `AUTHENTIC` | `video-classifier=0.93` | `UNCERTAIN` | `UNCERTAIN` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-B09` | `video` | Sensor Gaussian noise (sigma=14) causing video-classifier (0.92) false alarm | `AUTHENTIC` | `video-classifier=0.92` | `UNCERTAIN` | `UNCERTAIN` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-B10` | `text` | Academic domain terminology triggering text-desklib (0.94) false positive | `AUTHENTIC` | `text-desklib=0.94` | `UNCERTAIN` | `UNCERTAIN` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-C01` | `image` | Single-detector frequency_anomaly flag spoofing on clean image | `AUTHENTIC` | `detector_image=0.7` | `UNCERTAIN` | `AUTHENTIC` | `AUTHENTIC` | `FLIP / OK / OK` |
| `PS-C02` | `text` | Single-detector stylometry/perplexity flag spoofing on human text | `AUTHENTIC` | `detector_text=0.7` | `UNCERTAIN` | `AUTHENTIC` | `AUTHENTIC` | `FLIP / OK / OK` |
| `PS-C03` | `video` | Spoofed low_light_attenuation flag in bright daylight (lum=160) | `SYNTHETIC` | `rppg=0.88` | `SYNTHETIC` | `SYNTHETIC` | `SYNTHETIC` | `OK / OK / OK` |
| `PS-C04` | `video` | Spoofed short_clip_attenuation flag on 12.0s video | `SYNTHETIC` | `rppg=0.88` | `SYNTHETIC` | `SYNTHETIC` | `SYNTHETIC` | `OK / OK / OK` |
| `PS-C05` | `image` | Single borderline image claim (0.71) self-inflating to >=0.90 via Rule 7C flag | `SYNTHETIC` | `detector_image=0.71` | `UNCERTAIN` | `AUTHENTIC` | `UNCERTAIN` | `FLIP / FLIP / OK` |
| `PS-C06` | `text` | Self-flag inflation on consensus text detectors without perplexity detector | `SYNTHETIC` | `detector_text=0.72` | `SYNTHETIC` | `SYNTHETIC` | `SYNTHETIC` | `OK / OK / OK` |
| `PS-C07` | `video` | Spoofed low_light flag on well-lit video (lum=140) to evade detection | `SYNTHETIC` | `rppg=0.86` | `SYNTHETIC` | `SYNTHETIC` | `SYNTHETIC` | `OK / OK / OK` |
| `PS-C08` | `video` | Spoofed short_clip flag on 9s video to evade detection | `SYNTHETIC` | `rppg=0.85` | `SYNTHETIC` | `SYNTHETIC` | `SYNTHETIC` | `OK / OK / OK` |
| `PS-C09` | `audio` | Forged silent_video flag to suppress voice clone detection | `SYNTHETIC` | `aasist=0.89` | `SYNTHETIC` | `SYNTHETIC` | `SYNTHETIC` | `OK / OK / OK` |
| `PS-C10` | `image` | Single EXIF claim spoofing metadata mismatch flag on genuine camera photo | `AUTHENTIC` | `image-exif=0.7` | `AUTHENTIC` | `AUTHENTIC` | `AUTHENTIC` | `OK / OK / OK` |
| `PS-CYB-01` | `image` | Camera sensor noise (Task 2 FPR finding) causing ViT-S to assert 0.98 SYNTHETIC | `AUTHENTIC` | `detector_image=0.98` | `UNCERTAIN` | `SYNTHETIC` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-CYB-02` | `text` | 25% Unicode homoglyph confusables (Task 2 FPR finding) triggering desklib (0.92) | `AUTHENTIC` | `text-desklib=0.92` | `UNCERTAIN` | `UNCERTAIN` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-CYB-03` | `audio` | Rogue AASIST claim (0.95) on silent video file (no audio track) | `AUTHENTIC` | `aasist=0.95` | `UNCERTAIN` | `SYNTHETIC` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-CYB-04` | `audiovisual` | SyncNet lip-desync (0.96) false positive on dubbed foreign language video | `AUTHENTIC` | `syncnet=0.96` | `UNCERTAIN` | `SYNTHETIC` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-CYB-05` | `multimodal` | Compound attack: clean video where AASIST=0.98 + spoofed low-light flag attack both channels | `AUTHENTIC` | `aasist=0.98` | `UNCERTAIN` | `UNCERTAIN` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-CYB-06` | `video` | Inverted rPPG in low light (lum=28) asserting 0.94 SYNTHETIC on authentic video | `AUTHENTIC` | `rppg=0.94` | `UNCERTAIN` | `SYNTHETIC` | `UNCERTAIN` | `FLIP / FLIP / OK` |
| `PS-CYB-07` | `video` | Inverted rPPG on short clip (dur=1.8s) asserting 0.92 SYNTHETIC on authentic clip | `AUTHENTIC` | `rppg=0.92` | `UNCERTAIN` | `SYNTHETIC` | `INTEGRITY_UNKNOWN` | `FLIP / FLIP / OK` |
| `PS-CYB-08` | `video` | Compromised rPPG (0.95) asserting synthetic pulse against authentic video | `AUTHENTIC` | `rppg=0.95` | `UNCERTAIN` | `SYNTHETIC` | `UNCERTAIN` | `FLIP / FLIP / OK` |
| `PS-HN-01` | `multimodal` | Adversarial square_linf hard-negative video + spoofed AASIST (0.05) claim | `SYNTHETIC` | `aasist=0.05` | `UNCERTAIN` | `UNCERTAIN` | `SYNTHETIC` | `FLIP / FLIP / OK` |
| `PS-HN-02` | `multimodal` | Deepfake with spatial adversarial patch evading video-classifier (0.05) | `SYNTHETIC` | `video-classifier=0.05` | `UNCERTAIN` | `UNCERTAIN` | `SYNTHETIC` | `FLIP / FLIP / OK` |
| `PS-HN-03` | `video` | Compromised video-classifier emitting 0.04 AUTHENTIC on face swap with synthetic audio | `SYNTHETIC` | `video-classifier=0.04` | `UNCERTAIN` | `UNCERTAIN` | `SYNTHETIC` | `FLIP / FLIP / OK` |
| `PS-HN-04` | `video` | Spatial 4x downscaling evasion (Cybersecurity Task 2) causing 0.04 video score on deepfake | `SYNTHETIC` | `video-classifier=0.04` | `UNCERTAIN` | `UNCERTAIN` | `SYNTHETIC` | `FLIP / FLIP / OK` |
| `PS-HN-05` | `image` | 4x downscaling perturbation causing ViT-S false alarm (0.96) on authentic photo | `AUTHENTIC` | `detector_image=0.96` | `UNCERTAIN` | `SYNTHETIC` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-HN-06` | `image` | Heavy JPEG Q25 compression causing ViT-S false alarm (0.95) on authentic photo | `AUTHENTIC` | `detector_image=0.95` | `UNCERTAIN` | `SYNTHETIC` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-HN-07` | `image` | Gaussian blur sigma=2.4 causing ViT-S false alarm (0.94) on authentic photo | `AUTHENTIC` | `detector_image=0.94` | `UNCERTAIN` | `UNCERTAIN` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-HN-08` | `text` | Repetitive academic phrasing causing text-desklib false alarm (0.96) on human essay | `AUTHENTIC` | `text-desklib=0.96` | `UNCERTAIN` | `SYNTHETIC` | `AUTHENTIC` | `FLIP / FLIP / OK` |
| `PS-D01` | `video` | Poisoned nominal reliability drops video-classifier in favor of rPPG | `RETAINED` | `video-classifier=0.22` | `EVICTED` | `EVICTED` | `RETAINED` | `FLIP / FLIP / OK` |
| `PS-D02` | `video` | Poisoned silent video reliability leaves rPPG as sole witness | `RETAINED` | `video-classifier=0.22` | `EVICTED` | `EVICTED` | `RETAINED` | `FLIP / FLIP / OK` |
| `PS-D03` | `video` | Poisoned low_light reliability evicts primary spatial video-classifier | `RETAINED` | `video-classifier=0.22` | `EVICTED` | `EVICTED` | `RETAINED` | `FLIP / FLIP / OK` |
| `PS-D04` | `video` | Poisoned short_clip reliability evicts video-classifier | `RETAINED` | `video-classifier=0.22` | `EVICTED` | `EVICTED` | `RETAINED` | `FLIP / FLIP / OK` |
| `PS-D05` | `video` | Poisoned dubbed_audio reliability evicts video-classifier | `RETAINED` | `video-classifier=0.22` | `EVICTED` | `EVICTED` | `RETAINED` | `FLIP / FLIP / OK` |
| `PS-D06` | `video` | Poisoned manifest + high-risk budget pressure evicts video-classifier | `RETAINED` | `video-classifier=0.22` | `EVICTED` | `EVICTED` | `RETAINED` | `FLIP / FLIP / OK` |
| `PS-E01` | `video` | Hard-negative vid_deepfake_feed (adaptive_transform_search) + spoofed 48s telemetry + cost_weight=0.55 | `RETAINED` | `video-classifier=0.3594` | `EVICTED_DECISIVE` | `EVICTED_DECISIVE` | `RETAINED` | `FLIP / FLIP / OK` |
| `PS-E02` | `video` | Hard-negative vid_manipulated_feed (adaptive_transform_search) + spoofed 48s telemetry + cost_weight=0.55 | `RETAINED` | `video-classifier=0.405` | `EVICTED_DECISIVE` | `EVICTED_DECISIVE` | `RETAINED` | `FLIP / FLIP / OK` |
| `PS-E03` | `image` | Hard-negative img_borderline_short (adaptive_transform_search) + spoofed 42s telemetry + cost_weight=0.55 | `RETAINED` | `detector_image=0.1019` | `EVICTED_DECISIVE` | `EVICTED_DECISIVE` | `RETAINED` | `FLIP / FLIP / OK` |
| `PS-E04` | `image` | Hard-negative img_manipulated_feed (square_linf) + spoofed 42s telemetry + cost_weight=0.55 | `RETAINED` | `detector_image=0.1746` | `EVICTED_DECISIVE` | `EVICTED_DECISIVE` | `RETAINED` | `FLIP / FLIP / OK` |
| `PS-E05` | `text` | Hard-negative txt_ai_edu_05 (adaptive_feedback_paraphraser_v2) + spoofed 42s telemetry | `RETAINED` | `detector_text=0.2823` | `EVICTED_DECISIVE` | `EVICTED_DECISIVE` | `RETAINED` | `FLIP / FLIP / OK` |
| `PS-E06` | `text` | Hard-negative txt_ai_legal_08 (adaptive_feedback_paraphraser_v2) + spoofed 42s telemetry | `RETAINED` | `detector_text=0.2782` | `EVICTED_DECISIVE` | `EVICTED_DECISIVE` | `RETAINED` | `FLIP / FLIP / OK` |

## 3. Clean Benign Control Verification

| Control ID | Scenario | Baseline | Mitigated | Preserved? |
|---|---|---|---|---|
| `CTRL-01` | Clean Face-Swap (Rule 3) | `SYNTHETIC` | `SYNTHETIC` | PASS |
| `CTRL-02` | Clean Authentic Consensus | `AUTHENTIC` | `AUTHENTIC` | PASS |
| `CTRL-03` | Clean Deepfake Consensus | `SYNTHETIC` | `SYNTHETIC` | PASS |
| `CTRL-04` | Clean Nominal Video Planning | `['video-classifier', 'streaming-rppg', 'fusion']` | `['video-classifier', 'streaming-rppg', 'fusion']` | PASS |
