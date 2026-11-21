# Edge Hardware Profiling Report: Live Surveillance Path

> **Evaluation Mode:** `[EMULATION - EDGE CAPPED]`  
> **Target Device Architecture:** NVIDIA Jetson-class (Emulated via 4-Core CPU, 4GB RAM Capped Docker Container)  
> **Pipeline Components:** MobileNetV3 Spatial Frame Classifier + Streaming rPPG (16-frame sliding window, stride 8)  
> **Benchmark Source:** `engine/benchmark/profile_edge_hardware.py`  
> **Artifact Source:** `engine/benchmark/results_edge_profiling.json` | `engine/benchmark/results_edge_profiling.csv`

---

## 1. Executive Summary & Hardware Context

Per project requirements, the live surveillance pipeline was benchmarked for edge deployment. A hardware verification probe checked for physical NVIDIA Jetson hardware (`/etc/nv_tegra_release`, `/proc/device-tree/model`, and CUDA runtime availability). 

Because no physical Jetson-class board or discrete NVIDIA GPU was detected on the host system, all profiling experiments were executed inside a CPU- and memory-capped container environment enforcing exact Jetson-class resource limits (`--cpus=4 --memory=4g`). In compliance with evaluation instructions:
> **Every single latency, throughput, and memory figure in this report is strictly labeled as `[EMULATION - EDGE CAPPED]`.**

### Key Takeaways
1. **Real-Time Feasibility Achieved:** With INT8 quantization and Kernel Fusion enabled, the live pipeline attains a Mean Window Latency of **217.34 ms [EMULATION - EDGE CAPPED]**, satisfying the strict real-time requirement with a **Real-Time Ratio (RTR) of 0.8150 [EMULATION - EDGE CAPPED]** ($\le 1.0$).
2. **Impact of Kernel Fusion & Vectorization:** Standalone INT8 quantization without kernel fusion exhibited operator translation overhead on edge CPU cores, resulting in RTR of **1.4007 [EMULATION - EDGE CAPPED]** (FAIL). Enabling level-all ONNX runtime graph optimization (Conv+BN+Activation fusion) and vectorized preprocessing slashed window processing latency from **373.52 ms down to 217.34 ms** (a **41.8% latency reduction**), bringing the pipeline safely inside the real-time budget.
3. **Accuracy / Latency Pareto Trade-off:** The optimal INT8 + Fusion configuration achieves a **2.44× throughput speedup** over FP32 at batch size 16 (172.5 FPS vs 70.8 FPS, peaking at 200.3 FPS at $B=8$) with negligible accuracy impact (EER increased from **5.2% to 5.5% [EMULATION - EDGE CAPPED]**, a delta of only $+0.3\%$).

---

## 2. Benchmark Formulation & Real-Time Constraints

The live surveillance path (`LiveSurveillancePipeline`) ingests a continuous video stream at 30 FPS. Detection evaluates video in sliding temporal windows:
* **Window Size ($W$):** 16 frames
* **Stride ($S$):** 8 frames
* **Operational Ingestion Frame Rate:** 30 FPS
* **Stride Time Budget:**
  $$\Delta t_{\text{budget}} = \frac{S}{\text{FPS}} = \frac{8\text{ frames}}{30\text{ FPS}} = 266.67\text{ ms}$$
* **Real-Time Ratio (RTR):**
  $$\text{RTR} = \frac{T_{\text{window}}}{\Delta t_{\text{budget}}}$$

An operational configuration is viable for edge surveillance **if and only if $\text{RTR} \le 1.0$**. If $\text{RTR} > 1.0$, the pipeline falls behind ingestion, causing queue buildup, frame drops, and sensor latency drift.

---

## 3. Latency, Memory, and Accuracy Pareto Frontier

The table below summarizes the comprehensive edge profiling results across precision variants, dynamic batching, memory utilization, and detection accuracy under cgroup limits (`--cpus=4 --memory=4g`).

| Configuration | Precision | Kernel Fusion | Latency ($B=1$) [EMULATION - EDGE CAPPED] | Window Latency (16f, Stride 8) [EMULATION - EDGE CAPPED] | Real-Time Ratio (RTR) [EMULATION - EDGE CAPPED] | Max Throughput ($B=16$) [EMULATION - EDGE CAPPED] | Peak RAM [EMULATION - EDGE CAPPED] | Equal Error Rate (EER) [EMULATION - EDGE CAPPED] | SLA Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **MobileNetV3 FP32 (Baseline)** | FP32 | Disabled | 12.30 ms | 340.64 ms | 1.2774 | 70.8 FPS | 281.88 MB | 5.2% | **FAIL** ($\text{RTR} > 1.0$) |
| **MobileNetV3 INT8 (Quantized)** | INT8 | Disabled | 15.30 ms | 373.52 ms | 1.4007 | 60.6 FPS | 294.81 MB | 5.5% | **FAIL** ($\text{RTR} > 1.0$) |
| **MobileNetV3 INT8 + Kernel Fusion** | INT8 | **Enabled** | **6.18 ms** | **217.34 ms** | **0.8150** | **172.5 FPS** | **291.00 MB** | **5.5%** | **PASS** ($\text{RTR} \le 1.0$) |

```
                       LATENCY / ACCURACY PARETO FRONTIER
                       
  EER (%)
   5.6% |                                                [INT8 Quantized]
        |                                                Latency: 373.52 ms | RTR: 1.4007
   5.5% |     ★ [INT8 + Kernel Fusion]
        |     Latency: 217.34 ms | RTR: 0.8150
        |     (PARETO OPTIMAL - MEETS SLA)
   5.4% |
        |
   5.3% |
        |
   5.2% |                                            [FP32 Baseline]
        |                                            Latency: 340.64 ms | RTR: 1.2774
        +------------------------------------------------------------------------>
        0 ms          150 ms       217 ms   266.67 ms (SLA Limit)   350 ms     400 ms
                                 Mean Window Latency (ms)
```

---

## 4. Dynamic Batching Sweep ($B \in [1, 2, 4, 8, 16]$)

Dynamic batching was evaluated across batch dimensions $B \in [1, 2, 4, 8, 16]$ inside the capped container to profile batching saturation and throughput scaling under edge constraints.

### 4.1 MobileNetV3 INT8 + Kernel Fusion (Optimal Profile)
*All metrics labeled `[EMULATION - EDGE CAPPED]`*

| Batch Size ($B$) | p50 Latency (ms) | p90 Latency (ms) | p95 Latency (ms) | Mean Latency (ms) | Throughput (FPS) | Per-Frame Latency (ms) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 5.77 | 8.40 | 9.76 | 6.18 | 161.7 | 6.18 |
| **2** | 11.62 | 14.76 | 14.84 | 11.67 | 171.4 | 5.84 |
| **4** | 21.14 | 28.13 | 33.28 | 22.63 | 176.7 | 5.66 |
| **8** | 37.45 | 51.27 | 56.35 | 39.94 | **200.3** | **4.99** |
| **16** | 89.25 | 112.26 | 120.51 | 92.74 | 172.5 | 5.80 |

*Peak per-frame efficiency is reached at $B=8$ (4.99 ms/frame), delivering 200.3 FPS.*

### 4.2 MobileNetV3 FP32 Baseline
*All metrics labeled `[EMULATION - EDGE CAPPED]`*

| Batch Size ($B$) | p50 Latency (ms) | p90 Latency (ms) | p95 Latency (ms) | Mean Latency (ms) | Throughput (FPS) | Per-Frame Latency (ms) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 11.51 | 15.32 | 16.31 | 12.30 | 81.3 | 12.30 |
| **2** | 21.47 | 39.68 | 53.14 | 26.21 | 76.3 | 13.11 |
| **4** | 55.06 | 107.13 | 128.94 | 66.42 | 60.2 | 16.61 |
| **8** | 104.20 | 130.54 | 144.40 | 108.26 | 73.9 | 13.53 |
| **16** | 218.36 | 266.05 | 290.28 | 225.94 | 70.8 | 14.12 |

### 4.3 MobileNetV3 INT8 Without Kernel Fusion
*All metrics labeled `[EMULATION - EDGE CAPPED]`*

| Batch Size ($B$) | p50 Latency (ms) | p90 Latency (ms) | p95 Latency (ms) | Mean Latency (ms) | Throughput (FPS) | Per-Frame Latency (ms) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 13.92 | 19.43 | 19.70 | 15.30 | 65.4 | 15.30 |
| **2** | 30.00 | 41.46 | 42.60 | 31.92 | 62.7 | 15.96 |
| **4** | 53.52 | 73.39 | 75.52 | 58.02 | 68.9 | 14.51 |
| **8** | 146.76 | 190.21 | 211.45 | 151.67 | 52.7 | 18.96 |
| **16** | 258.27 | 322.18 | 329.14 | 263.93 | 60.6 | 16.50 |

---

## 5. Live Pipeline Breakdown: Spatial vs Streaming rPPG

Under the sliding window operational profile ($W=16$, $S=8$), processing each stride involves:
1. Updating streaming pulse signal extraction (rPPG green-channel spatial averaging and temporal Welch PSD computation via SciPy) across the 8 incoming frames.
2. Vectorized image normalization and batched inference through the spatial model.

### Stride Window Timing Breakdown [EMULATION - EDGE CAPPED]

| Pipeline Subsystem | FP32 Baseline | INT8 (No Fusion) | INT8 + Kernel Fusion | Target Budget |
| :--- | :---: | :---: | :---: | :---: |
| **Streaming rPPG Extractor** | 126.76 ms | 77.09 ms | 87.31 ms | < 100 ms |
| **Spatial Model Inference** | 213.87 ms | 296.43 ms | 130.02 ms | < 166.67 ms |
| **Total Stride Window Latency** | **340.64 ms** | **373.52 ms** | **217.34 ms** | **266.67 ms** |
| **Real-Time Ratio (RTR)** | 1.2774 | 1.4007 | **0.8150** | **$\le 1.0$** |
| **SLA Status** | FAIL | FAIL | **PASS** | -- |

```
Window Stride Budget: 266.67 ms [30 FPS Stride 8]
-----------------------------------------------------------------------------------------
FP32 Baseline:         [======== Spatial: 213.87 ms ========][=== rPPG: 126.76 ===] => 340.64 ms (FAIL)
INT8 (No Fusion):      [=========== Spatial: 296.43 ms ===========][= rPPG: 77.09 =] => 373.52 ms (FAIL)
INT8 + Kernel Fusion:  [==== Spatial: 130.02 ms ====][= rPPG: 87.31 =] => 217.34 ms (PASS - 0.8150 RTR)
-----------------------------------------------------------------------------------------
```

---

## 6. Containerized Deployment & Edge Reproduction

Container configuration files and execution scripts have been added to ensure deterministic execution within the resource limits:

* **Container Definition:** [engine/docker/Dockerfile.edge_profile](file:///e:/AEGIS-The-shield-against-synthetic-media/engine/docker/Dockerfile.edge_profile)
* **Linux/Jetson Shell Script:** [engine/docker/run_edge_profile_container.sh](file:///e:/AEGIS-The-shield-against-synthetic-media/engine/docker/run_edge_profile_container.sh)
* **Windows PowerShell Script:** [engine/docker/run_edge_profile_container.ps1](file:///e:/AEGIS-The-shield-against-synthetic-media/engine/docker/run_edge_profile_container.ps1)

### Execution Command:
```bash
docker run --rm \
  --cpus=4 \
  --memory=4g \
  --name aegis-edge-profiling \
  -v $(pwd)/engine/benchmark:/app/engine/benchmark \
  aegis-edge-profile:latest
```

When deployed on a physical Jetson device (e.g. Jetson Orin Nano / Orin NX), the benchmark script auto-detects Tegra hardware via `is_jetson_hardware()` and switches the label from `[EMULATION - EDGE CAPPED]` to `[HARDWARE: NVIDIA JETSON]`.

---

## 7. Final Recommendation

For production deployment of AEGIS live surveillance feeds on edge-constrained hardware:
1. **Model Deployment:** Deploy **MobileNetV3 INT8 with Graph Kernel Fusion** enabled (`GraphOptimizationLevel.ORT_ENABLE_ALL`).
2. **Batching:** Configure spatial inference to process frames in batches of $B=8$ matching the sliding stride interval, maximizing compute density (200.3 FPS throughput).
3. **Surveillance SLA:** Maintains an RTR of **0.8150 [EMULATION - EDGE CAPPED]**, keeping surveillance end-to-end processing strictly within the 266.67 ms temporal stride limit while maintaining a 5.5% EER.
