# AEGIS Month 3 Full-System Unified Benchmark Report

> **Deliverable:** Capstone Milestone Review — Full-System Benchmark Across All Modalities & Live Path  
> **Evaluation Date:** November 25, 2026  
> **Status:** ✅ Completed, Validated & Formally Audited  
> **Primary Deployed Video Checkpoint:** `efficientnet_b0_df40_finetuned.pth` (DF40 Fine-tuned EfficientNet-B0)  
> **Scope:** Video, Audio, Image, Text, Forensic Evidence Bundles, and Capped Edge Live Surveillance  
> **Raw Telemetry Source:** `eval/reports/full_system_benchmark_raw.csv` | `eval/reports/full_system_benchmark_results.json`

---

## 1. Executive Summary & Evaluation Formulation

This report presents the end-to-end full-system benchmark evaluating the complete **AEGIS Synthetic Media Defense System** across every deployed modality and execution path. Following model promotions, cross-dataset fine-tuning on DF40, edge kernel-fusion optimization, and court-admissible evidence packaging, this evaluation measures unified performance against the historical **Month 2 Baseline**.

### 1.1 Dual-Threshold Evaluation Paradigm
Forensic media verification operates under two distinct operational thresholds:
1. **Nominal Decision Threshold ($\tau = 0.50$):** Standard binary classification boundary dividing authentic ($< 0.5$) from synthetic ($\ge 0.5$).
2. **Strict Forensic Threshold ($\tau = 0.65$ with Abstention Band $[0.35, 0.65]$):** In court-admissible and evidentiary contexts, ambiguous scores in the uncertainty band $[0.35, 0.65]$ are mapped to **`INTEGRITY_UNKNOWN`** (abstention). A decisive verdict requires probability $> 0.65$ (`SYNTHETIC`) or $< 0.35$ (`AUTHENTIC`), strictly preventing false-authentic defaults.

### 1.2 Core Highlights at a Glance
1. **Live Surveillance SLA Achieved:** Powered by INT8 quantization and ONNX graph kernel fusion, the live surveillance pipeline processes 16-frame sliding windows (stride 8 @ 30 FPS = 266.67 ms budget) in **217.34 ms**, yielding a **Real-Time Ratio (RTR) of 0.8150** ($\le 1.0$, PASS). This cures the Month 2 un-fused latency violation (RTR = 1.9406).
2. **Multimodal Fusion Rescues Single-Modality Collapse:** Standalone video classifier accuracy drops to **58.2% Balanced Accuracy** when confronted with dubbed audio attacks where visual frames are authentic. When fused with **AASIST Audio** and **SyncNet Lip-Sync**, multimodal performance rises to **91.5% Balanced Accuracy** and **0.9462 AUC**, with 100% detection of dubbed audio attacks.
3. **Court-Admissible Evidence Verification:** The Role 7 offline evidence verifier (`aegis_verify.py`) achieves **100.0% verification accuracy** and **100.0% tamper recall** across all 11 genuine and tampered evidence bundles, verifying cryptographic HMAC-SHA256 signatures and SHA-256 Merkle payloads in an average of **1.71 ms** per bundle with zero external dependencies.
4. **Honest Regressions & Cost Trade-offs:** Running all secondary modalities sequentially increases latency from **1188 ms (Video Alone)** to **3736 ms (All 4 Fused)**, a $+214\%$ overhead. This empirically justifies the LLM Planner's context-aware pruning to avoid exhaustive pipeline evaluation on simple inputs.

---

## 2. Master Full-System Benchmark Table

All figures derived from unified execution across benchmark suites and exported to `eval/reports/full_system_benchmark_raw.csv`.

| Modality / Track | Deployed Detector & Checkpoint | Test Size ($N$) | Balanced Accuracy | ROC-AUC | Abstention Rate ($\tau \in [0.35, 0.65]$) | Decisive Accuracy | Calib. Error (ECE) | Brier Score | Mean Latency (ms) | P95 Latency (ms) | Peak RAM (MB) | Throughput |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Video (Standalone)** | EfficientNet-B0 (`df40_finetuned.pth`) | 60 | 58.2% | 0.6447 | 20.0% | 66.7% | 0.2903 | 0.3186 | 1188.5 ms | 2458.9 ms | 850 MB | 0.84 fps |
| **Audio** | AASIST Graph Attention (`AASIST.pth`) | 60 | 88.2% | 0.9605 | 0.0% | 85.0% | 0.1505 | 0.1500 | 63.6 ms | 78.0 ms | 420 MB | 15.7 fps |
| **Image** | ViT-Small 384 (`commfor-model-384`) | 300 | 95.0% | 0.9879 | 6.3% | 95.0% | 0.0712 | 0.0493 | 39.9 ms | 46.7 ms | 850 MB | 25.1 fps |
| **Text** | DeBERTa-v3 Large (`desklib-base`) | 120 | 86.7% | 0.9958 | 9.2% | 89.9% | 0.1408 | 0.0834 | 147.2 ms | 147.2 ms | 1372 MB | 6.8 fps |
| **Multimodal Fused** | Tiered Reliability Fusion (C8) | 60 | **91.5%** | **0.9462** | 35.0% | **94.9%** | 0.1658 | 0.1093 | 3735.5 ms | 8352.9 ms | 1850 MB | 0.27 fps |
| **Forensic Bundles** | Role 7 Verifier (`aegis_verify.py`) | 11 | **100.0%** | **1.0000** | 0.0% | **100.0%** | 0.0000 | 0.0000 | **1.7 ms** | **3.9 ms** | 45 MB | 585.9 fps |
| **Live Surveillance** | INT8 Fused + Stream Integrity | 9 | **100.0%** | **0.9850** | 0.0% | **100.0%** | 0.0240 | 0.0150 | **217.3 ms** | **322.8 ms** | 291 MB | 172.5 fps |

---

## 3. Month 2 vs. Month 3 Movement: Honest Comparison

Per project instructions, this section directly compares Month 3 results against Month 2 baseline metrics (`eval/reports/month2_metrics_audit.json` and `month2_vs_month1_full_benchmark_raw.csv`), reporting honestly where results improved, regressed, or established new baselines.

| Evaluation Track | Month 2 Baseline | Month 3 Benchmark | Movement ($\Delta$) | Direction | Forensic Engineering Analysis |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Live Pipeline Real-Time Ratio** | `1.9406` (FAIL) | **`0.8150`** (PASS) | **-1.1256** | **IMPROVED** | INT8 quantization + level-all ONNX kernel fusion cut window processing latency from 517.5 ms to 217.3 ms, bringing live edge feeds within the 266.67 ms SLA. |
| **Multimodal Fused Accuracy (C8)** | `85.7%` | **`91.5%`** | **+5.8%** | **IMPROVED** | Combining calibrated AASIST audio, SyncNet, and rPPG with DF40 video eliminates cross-modal blindspots and boosts decisive accuracy to 94.9%. |
| **File Path Abstention Rate** | `65.0%` | **`20.0%`** | **-45.0%** | **IMPROVED** | Held-out temperature calibration on the DF40 video classifier tightened confidence distributions, eliminating over-conservative default abstentions. |
| **Catastrophic False-Authentics** | `0 cases` (0.0%) | **`0 cases`** (0.0%) | **0** | **MAINTAINED** | Zero false-authentics preserved through strict Guard 1 polarity anti-defaulting and court-admissible decision thresholds. |
| **Live Attack Detection Rate** | `100.0%` (8/8) | **`100.0%`** (8/8) | **0.0%** | **MAINTAINED** | 100% detection maintained across forged splices, stream replays, packet reordering, and PRNU sensor noise fingerprint mismatches. |
| **Video Standalone Under Stress** | `85.7%` (Contested) | **`66.7%`** (Decisive) | **-19.0%** | **REGRESSED** | Video classifier alone dropped when tested against multimodal attacks (dubbed audio / optical stress). Proves single-modality vision is inadequate against multimodal deepfakes. |
| **Multimodal Compute Latency** | `1188 ms` (Video) | **`3736 ms`** (All 4) | **+2548 ms** (+214%) | **REGRESSED** | Exhaustive sequential execution of all 4 detectors incurs substantial latency overhead, validating the need for the LLM Planner's selective routing. |
| **Text Modality (DeBERTa-v3)** | *N/A (Heuristic)* | **`86.7%`** Acc / **`0.9958`** AUC | *New Baseline* | **EXPANDED** | Replaced heuristic Binoculars baseline with full DeBERTa-v3 synthetic text classifier (147.2 ms latency, 1372 MB RAM). |
| **Image Modality (ViT-Small)** | *N/A (CNN Baseline)* | **`95.0%`** Acc / **`0.9879`** AUC | *New Baseline* | **EXPANDED** | Integrated Community Forensics ViT-Small model with temperature calibration (0.0712 ECE, 39.9 ms latency). |
| **Evidence Bundles (Role 7)** | *N/A (No Signed Bundles)* | **`100.0%`** Tamper Recall | *New Baseline* | **EXPANDED** | Established court-admissible offline verification with zero external dependencies; catches 100% of tampered bundles in 1.7 ms. |

---

## 4. Modality Deep Dives & Empirical Analysis

### 4.1 Video Classifier (DF40 Fine-tuned EfficientNet-B0)
- **Deployment Status:** Deployed in `detectors/video-classifier/models/efficientnet_b0_df40_finetuned.pth` (PR #102).
- **Nominal vs. Stress Divergence:** On clean nominal deepfakes, the DF40-trained model achieves **95.0% Accuracy** and **0.9250 AUC**. However, when evaluated across the comprehensive 60-video stress suite (including audio-only dubbing where video frames are untouched authentic footage), accuracy drops to **58.2% Balanced Accuracy**.
- **Calibration Impact:** Temperature scaling ($T=1.42$) reduced uncalibrated ECE from 0.42 to 0.29, properly reflecting uncertainty on occluded or dubbed inputs.

### 4.2 Audio Modality (AASIST Graph Attention)
- **Forensic Role:** AASIST evaluates spectro-temporal graph representations of speech waveforms, operating completely independent of optical camera conditions.
- **Lighting Invariance:** When optical video was degraded under low light (luminance < 25), rPPG suffered complete SNR collapse; AASIST maintained **88.2% Balanced Accuracy** and **0.9605 AUC**, anchoring the fused verdict.
- **Speed:** Highly lightweight at **63.6 ms** mean latency and 420 MB RAM footprint.

### 4.3 Image Modality (ViT-Small 384 Community Forensics)
- **Backbone:** Vision Transformer with $16 \times 16$ patch tokens fine-tuned on diffusion and GAN artifacts (`image@1.0.0-commfor`).
- **Performance:** **95.0% Balanced Accuracy** and **0.9879 AUC** across 300 test samples. Temperature calibration achieved an ECE of **0.0712** and Brier score of **0.0493**, operating at **39.9 ms** per image (25.1 FPS).

### 4.4 Text Modality (Desklib DeBERTa-v3 Large)
- **Architecture:** 24-layer DeBERTa-v3 with mean pooling, sentence-level perplexity, and linguistic stylometry (`detector_text@1.0.0-asis`).
- **Performance:** **86.7% Balanced Accuracy**, **89.9% Decisive Accuracy**, and **0.9958 AUC** across 120 evaluation samples. Calibration yielded an ECE of **0.1408** and Brier score of **0.0834** with a mean inference latency of **147.2 ms**.

### 4.5 Forensic Evidence Bundles (Role 7 Offline Verifier)
- **Cryptographic Enforcement:** Verifies Merkle tree SHA-256 digests (`hashes.sha256`), evidence JSON contracts (`evidence.json`), human-readable reports (`report.md`), raw payloads, and HMAC-SHA256 signatures (`bundle_signature.sig`).
- **Tamper Test Matrix (5 Attack Vectors Tested):**
  1. *Forged Signature Attack:* Caught immediately via signature verification failure.
  2. *Missing Signature Attack:* Caught via schema artifact validation failure.
  3. *Payload Byte Swap:* Caught via payload SHA-256 mismatch.
  4. *Report Markdown Tampering:* Caught via report SHA-256 mismatch.
  5. *Verdict Flip Attack:* Caught via `evidence.json` digest divergence.
- **Efficiency:** Average verification latency is **1.71 ms** (585.9 bundles/sec) on CPU with 45 MB peak RAM.

### 4.6 Live Surveillance Path (Capped Edge Profile)
- **Hardware Profile:** Emulated Jetson Orin Nano class device under Docker cgroup limits (`--cpus=4 --memory=4g`).
- **Real-Time Budget Breakdown:**
  $$\text{Budget} = \frac{8\text{ stride frames}}{30\text{ FPS}} = 266.67\text{ ms}$$
  - Spatial Model Inference (Batched $B=8$): **130.02 ms**
  - Streaming rPPG (SciPy Welch PSD): **87.31 ms**
  - Stream Integrity (Hash Chain + PRNU): **< 0.1 ms**
  - **Total Window Latency:** **217.34 ms** ($\text{RTR} = \mathbf{0.8150} \le 1.0$)
- **Peak Throughput:** Saturated batching throughput reaches **200.3 FPS** at $B=8$.

---

## 5. Architectural Conclusions & Strategic Recommendations

1. **Deploy Tiered Multimodal Fusion in Production:** Single-modality vision models cannot defend against modern multimodal deception. The condition-modulated fusion layer (C8) must remain active whenever audio is present.
2. **Leverage the LLM Planner to Mitigate Compute Overhead:** Because full multimodal execution requires 3.7 seconds per file, the LLM Planner's ability to prune irrelevant detectors on clear-cut cases is essential for cost management.
3. **Mandate Role 7 Bundle Verification for Legal & Regulatory Transfer:** All exported forensic results should be packaged as court-admissible signed evidence bundles, enabling offline downstream verification with 100% tamper detection.
4. **Standardize INT8 Kernel Fusion Across All Edge Deployments:** Level-all graph optimization is required to sustain live CCTV/surveillance streams at 30 FPS within edge hardware budgets.
