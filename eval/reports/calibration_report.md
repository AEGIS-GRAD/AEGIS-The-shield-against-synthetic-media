# AEGIS Task 3 — Detector Calibration & Reliability Audit Report

**Document Version:** 1.0 (Task 3 Deliverable)  
**Status:** Completed  
**Scope:** Held-out Probability Calibration (Platt Scaling, Temperature Scaling, Isotonic Regression)  
**Target Modalities:** Audio (`aasist`), Image (`wang_cnndet_dire`), Text (`binoculars`), Video (`video-classifier`)  

---

## Executive Summary

Modern deepfake detection backbones frequently exhibit overconfidence in their uncalibrated sigmoid/softmax outputs. In multi-modal court-admissible forensic pipelines, uncalibrated raw scores distort downstream Bayesian/evidentiary weighting and lead to distorted arbitration verdicts.

Task 3 implements reusable probability calibrators (`eval/calibration/`) supporting:
1. **Platt Scaling** (logistic sigmoid fitting on logits)
2. **Temperature Scaling** (single-parameter entropy preservation $z / T$)
3. **Isotonic Regression** (non-parametric monotonic step mapping)

Each calibrator was fit on strictly **held-out calibration datasets** that models never saw during fine-tuning. The module is modularly designed so that new video checkpoints dropped into `detectors/video-classifier/models/` can be calibrated immediately via `eval/scripts/calibrate.py`.

---

## Calibration Performance Across Modalities

| Modality | Detector Backbone | Calibration Method | ECE (Before) | ECE (After) | ECE Reduction | Brier Score (After) | Status |
|:---|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **AUDIO** | `aasist` | **Platt** | `0.1594` | `0.0363` | **-77.2%** | `0.0186` | PASS |
| **AUDIO** | `aasist` | **Temperature** | `0.1594` | `0.0235` | **-85.3%** | `0.0190` | PASS |
| **AUDIO** | `aasist` | **Isotonic** | `0.1594` | `0.0000` | **-100.0%** | `0.0100` | PASS |
| **IMAGE** | `wang_cnndet_dire` | **Platt** | `0.1619` | `0.0565` | **-65.1%** | `0.0524` | PASS |
| **IMAGE** | `wang_cnndet_dire` | **Temperature** | `0.1619` | `0.0729` | **-55.0%** | `0.0543` | PASS |
| **IMAGE** | `wang_cnndet_dire` | **Isotonic** | `0.1619` | `0.0000` | **-100.0%** | `0.0369` | PASS |
| **TEXT** | `binoculars` | **Platt** | `0.1808` | `0.0513` | **-71.6%** | `0.0354` | PASS |
| **TEXT** | `binoculars` | **Temperature** | `0.1808` | `0.0502` | **-72.2%** | `0.0354` | PASS |
| **TEXT** | `binoculars` | **Isotonic** | `0.1808` | `0.0000` | **-100.0%** | `0.0188` | PASS |
| **VIDEO** | `video-classifier` | **Platt** | `0.1156` | `0.0243` | **-79.0%** | `0.0186` | PASS |
| **VIDEO** | `video-classifier` | **Temperature** | `0.1156` | `0.0232` | **-79.9%** | `0.0186` | PASS |
| **VIDEO** | `video-classifier` | **Isotonic** | `0.1156` | `0.0000` | **-100.0%** | `0.0125` | PASS |

---

## Per-Modality Reliability Visualizations

### AUDIO Detector Reliability Curves

#### Platt Scaling (AUDIO)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/audio_platt_calibrator.json`](eval/calibration/checkpoints/audio_platt_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_audio_platt.pdf`](eval/reports/calibration/reliability_audio_platt.pdf)
![AUDIO Platt Diagram](eval/reports/calibration/reliability_audio_platt.png)

#### Temperature Scaling (AUDIO)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/audio_temperature_calibrator.json`](eval/calibration/checkpoints/audio_temperature_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_audio_temperature.pdf`](eval/reports/calibration/reliability_audio_temperature.pdf)
![AUDIO Temperature Diagram](eval/reports/calibration/reliability_audio_temperature.png)

#### Isotonic Scaling (AUDIO)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/audio_isotonic_calibrator.json`](eval/calibration/checkpoints/audio_isotonic_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_audio_isotonic.pdf`](eval/reports/calibration/reliability_audio_isotonic.pdf)
![AUDIO Isotonic Diagram](eval/reports/calibration/reliability_audio_isotonic.png)

### IMAGE Detector Reliability Curves

#### Platt Scaling (IMAGE)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/image_platt_calibrator.json`](eval/calibration/checkpoints/image_platt_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_image_platt.pdf`](eval/reports/calibration/reliability_image_platt.pdf)
![IMAGE Platt Diagram](eval/reports/calibration/reliability_image_platt.png)

#### Temperature Scaling (IMAGE)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/image_temperature_calibrator.json`](eval/calibration/checkpoints/image_temperature_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_image_temperature.pdf`](eval/reports/calibration/reliability_image_temperature.pdf)
![IMAGE Temperature Diagram](eval/reports/calibration/reliability_image_temperature.png)

#### Isotonic Scaling (IMAGE)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/image_isotonic_calibrator.json`](eval/calibration/checkpoints/image_isotonic_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_image_isotonic.pdf`](eval/reports/calibration/reliability_image_isotonic.pdf)
![IMAGE Isotonic Diagram](eval/reports/calibration/reliability_image_isotonic.png)

### TEXT Detector Reliability Curves

#### Platt Scaling (TEXT)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/text_platt_calibrator.json`](eval/calibration/checkpoints/text_platt_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_text_platt.pdf`](eval/reports/calibration/reliability_text_platt.pdf)
![TEXT Platt Diagram](eval/reports/calibration/reliability_text_platt.png)

#### Temperature Scaling (TEXT)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/text_temperature_calibrator.json`](eval/calibration/checkpoints/text_temperature_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_text_temperature.pdf`](eval/reports/calibration/reliability_text_temperature.pdf)
![TEXT Temperature Diagram](eval/reports/calibration/reliability_text_temperature.png)

#### Isotonic Scaling (TEXT)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/text_isotonic_calibrator.json`](eval/calibration/checkpoints/text_isotonic_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_text_isotonic.pdf`](eval/reports/calibration/reliability_text_isotonic.pdf)
![TEXT Isotonic Diagram](eval/reports/calibration/reliability_text_isotonic.png)

### VIDEO Detector Reliability Curves

#### Platt Scaling (VIDEO)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/video_platt_calibrator.json`](eval/calibration/checkpoints/video_platt_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_video_platt.pdf`](eval/reports/calibration/reliability_video_platt.pdf)
![VIDEO Platt Diagram](eval/reports/calibration/reliability_video_platt.png)

#### Temperature Scaling (VIDEO)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/video_temperature_calibrator.json`](eval/calibration/checkpoints/video_temperature_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_video_temperature.pdf`](eval/reports/calibration/reliability_video_temperature.pdf)
![VIDEO Temperature Diagram](eval/reports/calibration/reliability_video_temperature.png)

#### Isotonic Scaling (VIDEO)
- **Calibrator Artifact:** [`eval/calibration/checkpoints/video_isotonic_calibrator.json`](eval/calibration/checkpoints/video_isotonic_calibrator.json)
- **PDF Vector Diagram:** [`eval/reports/calibration/reliability_video_isotonic.pdf`](eval/reports/calibration/reliability_video_isotonic.pdf)
![VIDEO Isotonic Diagram](eval/reports/calibration/reliability_video_isotonic.png)

---

## Modular Video Checkpoint Calibration Instructions

To calibrate any new video checkpoint dropped into the system, execute:
```bash
# Calibrate custom video checkpoint with all methods:
python eval/scripts/calibrate.py --modality video --checkpoint path/to/new_checkpoint.pth --method all

# Save custom calibrator output and inspect reliability curves:
python eval/scripts/calibrate.py --modality video --checkpoint engine/edge_model/mobilenetv3_small_ffpp.pth
```

*Report generated automatically by `eval/scripts/calibrate.py`.*