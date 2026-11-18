# AEGIS Red-Team Poisoning Log (Judge & Planner)

- **Total Attack Scenarios:** 30
- **Unmitigated Baseline Attack Success Rate (ASR):** **93.3%** (28/30)
- **Mitigated System Attack Success Rate (ASR):** **0.0%** (0/30)
- **Benign Control Preservation:** 4/4 controls preserved without collateral degradation

## 1. Attack Category Summary

| Category | Scenarios | Baseline ASR | Mitigated ASR | Primary Cheap Mitigation |
|---|---:|---:|---:|---|
| `miscalibrated_overconfidence` | 6 | 100.0% | 0.0% | Raw-score calibration mismatch penalty + confidence/weight caps |
| `rogue_outlier_injection` | 6 | 66.7% | 0.0% | Leave-one-out statistical outlier rejection + pre-rule Precedence isolation |
| `spoofed_corroboration_and_flag_poisoning` | 6 | 100.0% | 0.0% | Cross-modal corroboration quorum + objective metadata cross-checks |
| `manifest_reliability_feedback_poisoning` | 6 | 100.0% | 0.0% | Primary-Authority Quorum (rPPG secondary proxy cannot excuse primary skip) |
| `adversarial_media_and_telemetry_cost_poisoning` | 6 | 100.0% | 0.0% | Telemetry latency spike clamping (2x baseline) + decisive detector guarantee |

## 2. Detailed Scenario Execution Log

| ID | Category | Target | Modality | Attack Scenario | Baseline Result | Base ASR? | Mitigated Result | Mitigated ASR? |
|---|---|---|---|---|---|---|---|---|
| `PS-A01` | `miscalibrated_overconfidence` | `judge` | `video` | Tampered confidence vs raw_score on video-classifier (0.99 vs raw 0.22) | SYNTHETIC (score=0.8500) | YES | UNCERTAIN (score=0.5223) | NO |
| `PS-A02` | `miscalibrated_overconfidence` | `judge` | `image` | Miscalibrated image-mirror confidence (0.99 vs raw 0.28) | SYNTHETIC (score=0.8150) | YES | UNCERTAIN (score=0.3882) | NO |
| `PS-A03` | `miscalibrated_overconfidence` | `judge` | `text` | Miscalibrated text-desklib confidence (0.99 vs raw 0.25) | SYNTHETIC (score=0.7178) | YES | UNCERTAIN (score=0.4648) | NO |
| `PS-A04` | `miscalibrated_overconfidence` | `judge` | `video` | False-negative raw_score tampering (0.001 AUTHENTIC vs raw 0.85) | AUTHENTIC (score=0.2193) | YES | SYNTHETIC (score=0.6896) | NO |
| `PS-A05` | `miscalibrated_overconfidence` | `judge` | `audio` | Tampered AASIST confidence (0.98 vs raw 0.20) forcing Rule 5 | SYNTHETIC (score=0.8500) | YES | UNCERTAIN (score=0.5097) | NO |
| `PS-A06` | `miscalibrated_overconfidence` | `judge` | `image` | Single-detector uncorroborated 0.999 saturation (raw=0.52) | SYNTHETIC (score=0.8951) | YES | UNCERTAIN (score=0.5131) | NO |
| `PS-B01` | `rogue_outlier_injection` | `judge` | `multimodal` | Rogue AASIST outlier (0.98) hijacking Rule 5 against 3 AUTHENTIC peers | SYNTHETIC (score=0.8500) | YES | AUTHENTIC (score=0.2125) | NO |
| `PS-B02` | `rogue_outlier_injection` | `judge` | `video` | Rogue video-classifier outlier (0.97) hijacking Rules 3 & 6 | SYNTHETIC (score=0.8500) | YES | AUTHENTIC (score=0.2213) | NO |
| `PS-B03` | `rogue_outlier_injection` | `judge` | `multimodal` | Compromised video-classifier outputting 0.04 AUTHENTIC on deepfake | SYNTHETIC (score=0.8500) | NO | SYNTHETIC (score=0.8500) | NO |
| `PS-B04` | `rogue_outlier_injection` | `judge` | `image` | Rogue image-mirror outlier (0.96) discounting clean frequency & EXIF | SYNTHETIC (score=0.7950) | YES | AUTHENTIC (score=0.2118) | NO |
| `PS-B05` | `rogue_outlier_injection` | `judge` | `text` | Rogue text-desklib outlier (0.96) discounting authentic stylometry/perplexity | SYNTHETIC (score=0.8172) | YES | AUTHENTIC (score=0.2166) | NO |
| `PS-B06` | `rogue_outlier_injection` | `judge` | `multimodal` | Compromised AASIST outputting 0.05 AUTHENTIC on deepfake consensus | SYNTHETIC (score=0.8500) | NO | SYNTHETIC (score=0.8500) | NO |
| `PS-C01` | `spoofed_corroboration_and_flag_poisoning` | `judge` | `image` | Single-detector frequency_anomaly flag spoofing on clean image | SYNTHETIC (score=0.9000) | YES | AUTHENTIC (score=0.2516) | NO |
| `PS-C02` | `spoofed_corroboration_and_flag_poisoning` | `judge` | `text` | Single-detector stylometry/perplexity flag spoofing on human text | SYNTHETIC (score=0.9200) | YES | AUTHENTIC (score=0.2513) | NO |
| `PS-C03` | `spoofed_corroboration_and_flag_poisoning` | `judge` | `video` | Spoofed low_light_attenuation flag in bright daylight (lum=160) | UNCERTAIN (score=0.6059) | YES | SYNTHETIC (score=0.6583) | NO |
| `PS-C04` | `spoofed_corroboration_and_flag_poisoning` | `judge` | `video` | Spoofed short_clip_attenuation flag on 12.0s video | UNCERTAIN (score=0.6057) | YES | SYNTHETIC (score=0.6583) | NO |
| `PS-C05` | `spoofed_corroboration_and_flag_poisoning` | `judge` | `image` | Single borderline image claim (0.71) self-inflating to >=0.90 via Rule 7C flag | SYNTHETIC (score=0.9000) | YES | UNCERTAIN (score=0.6155) | NO |
| `PS-C06` | `spoofed_corroboration_and_flag_poisoning` | `judge` | `text` | Self-flag inflation on consensus text detectors without perplexity detector | SYNTHETIC (score=0.9200) | YES | SYNTHETIC (score=0.7039) | NO |
| `PS-D01` | `manifest_reliability_feedback_poisoning` | `planner` | `video` | Poisoned nominal reliability drops video-classifier in favor of rPPG | EVICTED (called=['streaming-rppg', 'fusion']) | YES | RETAINED (called=['video-classifier', 'streaming-rppg', 'fusion']) | NO |
| `PS-D02` | `manifest_reliability_feedback_poisoning` | `planner` | `video` | Poisoned silent video reliability leaves rPPG as sole witness | EVICTED (called=['streaming-rppg', 'fusion']) | YES | RETAINED (called=['video-classifier', 'streaming-rppg', 'fusion']) | NO |
| `PS-D03` | `manifest_reliability_feedback_poisoning` | `planner` | `video` | Poisoned low_light reliability evicts primary spatial video-classifier | EVICTED (called=['streaming-rppg', 'fusion']) | YES | RETAINED (called=['video-classifier', 'streaming-rppg', 'fusion']) | NO |
| `PS-D04` | `manifest_reliability_feedback_poisoning` | `planner` | `video` | Poisoned short_clip reliability evicts video-classifier | EVICTED (called=['fusion']) | YES | RETAINED (called=['video-classifier', 'fusion']) | NO |
| `PS-D05` | `manifest_reliability_feedback_poisoning` | `planner` | `video` | Poisoned dubbed_audio reliability evicts video-classifier | EVICTED (called=['streaming-rppg', 'fusion']) | YES | RETAINED (called=['video-classifier', 'streaming-rppg', 'fusion']) | NO |
| `PS-D06` | `manifest_reliability_feedback_poisoning` | `planner` | `video` | Poisoned manifest + high-risk budget pressure evicts video-classifier | EVICTED (called=['fusion', 'streaming-rppg']) | YES | RETAINED (called=['video-classifier', 'fusion', 'streaming-rppg']) | NO |
| `PS-E01` | `adversarial_media_and_telemetry_cost_poisoning` | `planner+judge` | `video` | Hard-negative vid_deepfake_feed (adaptive_transform_search) + spoofed 48s telemetry + cost_weight=0.55 | EVICTED_DECISIVE (evaded=0.359, plan=['fusion', 'streaming-rppg']) | YES | RETAINED (evaded=0.359, plan=['fusion', 'streaming-rppg', 'video-classifier']) | NO |
| `PS-E02` | `adversarial_media_and_telemetry_cost_poisoning` | `planner+judge` | `video` | Hard-negative vid_manipulated_feed (adaptive_transform_search) + spoofed 48s telemetry + cost_weight=0.55 | EVICTED_DECISIVE (evaded=0.405, plan=['fusion', 'streaming-rppg']) | YES | RETAINED (evaded=0.405, plan=['fusion', 'streaming-rppg', 'video-classifier']) | NO |
| `PS-E03` | `adversarial_media_and_telemetry_cost_poisoning` | `planner+judge` | `image` | Hard-negative img_borderline_short (adaptive_transform_search) + spoofed 42s telemetry + cost_weight=0.55 | EVICTED_DECISIVE (evaded=0.102, plan=['image']) | YES | RETAINED (evaded=0.102, plan=['image', 'detector_image']) | NO |
| `PS-E04` | `adversarial_media_and_telemetry_cost_poisoning` | `planner+judge` | `image` | Hard-negative img_manipulated_feed (square_linf) + spoofed 42s telemetry + cost_weight=0.55 | EVICTED_DECISIVE (evaded=0.175, plan=['image']) | YES | RETAINED (evaded=0.175, plan=['image', 'detector_image']) | NO |
| `PS-E05` | `adversarial_media_and_telemetry_cost_poisoning` | `planner+judge` | `text` | Hard-negative txt_ai_edu_05 (adaptive_feedback_paraphraser_v2) + spoofed 42s telemetry | EVICTED_DECISIVE (evaded=0.282, plan=[]) | YES | RETAINED (evaded=0.282, plan=['detector_text']) | NO |
| `PS-E06` | `adversarial_media_and_telemetry_cost_poisoning` | `planner+judge` | `text` | Hard-negative txt_ai_legal_08 (adaptive_feedback_paraphraser_v2) + spoofed 42s telemetry | EVICTED_DECISIVE (evaded=0.278, plan=[]) | YES | RETAINED (evaded=0.278, plan=['detector_text']) | NO |

## 3. Clean Benign Control Verification

| Control ID | Scenario | Baseline | Mitigated | Preserved? |
|---|---|---|---|---|
| `CTRL-01` | Clean Face-Swap (Rule 3) | `SYNTHETIC` | `SYNTHETIC` | PASS |
| `CTRL-02` | Clean Authentic Consensus | `AUTHENTIC` | `AUTHENTIC` | PASS |
| `CTRL-03` | Clean Deepfake Consensus | `SYNTHETIC` | `SYNTHETIC` | PASS |
| `CTRL-04` | Clean Nominal Video Planning | `['video-classifier', 'streaming-rppg', 'fusion']` | `['video-classifier', 'streaming-rppg', 'fusion']` | PASS |
