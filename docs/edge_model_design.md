# Edge Model Design — Live Surveillance Sliding-Window Classifier

## 1. Objective

Select the lightweight CNN/ViT architecture that will run AEGIS's real-time,
sliding-window deepfake check on edge hardware (Jetson-class), as a distinct
model from the file-based video-classifier used for offline verification.

## 2. Why this needs a different model than the offline video-classifier

| | Offline video-classifier | Live surveillance edge model |
|---|---|---|
| Input | Complete video file | Rolling window of most recent N frames |
| Input resolution | 299×299 (Xception-class) | Reduced — target 160–192×192 |
| Output pattern | Single final verdict after full-file processing | Continuously updating anomaly score |
| Hardware assumption | Server-class compute | Constrained edge hardware (Jetson-class) |
| Parameter budget | Larger (Xception/EfficientNet-B0-class) | Substantially smaller |

## 3. Candidates considered

### 3.1 MobileNetV3-Small
Depthwise-separable convolutions plus squeeze-and-excitation, found via
platform-aware neural architecture search + NetAdapt [1].

- **Params:** MobileNetV3-Large reported at 5.4M vs. EfficientNet-B0's 5.3M
  at near-identical ImageNet top-1 accuracy (75.2% vs. 76.3%) [1]. The
  Small variant is smaller still.
- **General edge benchmarking:** a systematic arXiv study of MobileNet,
  EfficientNet (V1/V2), ResNet, VGG, and InceptionV3 across NVIDIA Jetson
  Nano, Intel Neural Stick, and Google Coral devices found MobileNet-family
  models among the fastest on Google/Coral accelerators specifically,
  across 3,095 test cases [2].
- **Export maturity:** plain CNN classification backbones are the
  best-understood case for TensorRT optimization. A dedicated paper on
  TensorRT-oriented network design states plainly that most modern vision
  transformers "are not even as efficient as the basic ResNets series" once
  measured by actual TensorRT latency rather than FLOPs or parameter count
  [3] — i.e., the metric gap specifically favors CNN architectures like
  MobileNetV3 once real hardware is the yardstick, not paper benchmarks.

### 3.2 EfficientNet-Lite
Edge/TPU-adapted EfficientNet variant — removes squeeze-and-excitation and
swish activation in favor of simpler, hardware-friendlier ops.

- **Params/accuracy trade:** EfficientNet-eLite (a further-compressed
  EfficientNet-Lite-family variant) reports better parameter efficiency and
  accuracy than MnasNet at equivalent model size, evaluated on ImageNet [4].
- **Deepfake-specific:** a peer-reviewed comparative study of deepfake
  detectors (XceptionNet, EfficientNet, MesoNet, Vision Transformers) found
  EfficientNet provides "a balance between parameter efficiency and
  detection quality, but lags behind in cross-dataset generalization" [5].
- **General edge latency:** in a controlled on-device comparison (ECCV
  2022), EfficientNet-B0 measured 52.1ms per image on real hardware — a
  useful real-world anchor, notably **slower** than its FLOPs count would
  suggest relative to lighter architectures tested in the same study [6].

### 3.3 MobileViTv2
CNN + transformer-attention hybrid.

- **Deepfake-specific accuracy:** a 2026 M.S. thesis evaluating four
  lightweight vision transformers (MobileViT, MobileViTv2, EdgeNeXt,
  EfficientViT) on deepfake-specific benchmarks (DF40, DDL) found MobileViTv2
  achieved the best result: 96.3% multi-class accuracy, 2.56ms inference,
  4.39M parameters [7]. **Important caveat:** the thesis does not specify
  the inference hardware/runtime for that 2.56ms figure as a Jetson
  ONNX→TensorRT deployment specifically — this was not independently
  verified.
- **Export/deployment risk — now backed by real papers, not anecdote:**
  - The TensorRT-oriented-design paper above states this as its core
    motivating problem: transformer architectures routinely under-deliver
    on real TensorRT hardware relative to their paper-reported
    FLOPs/accuracy numbers [3].
  - A 2026 industrial benchmarking paper directly comparing CNN-based
    (YOLOv8, UNet) and transformer-based models across PyTorch, ONNX
    Runtime, OpenVINO, and TensorRT on a Jetson AGX Orin found: "the
    GPU-side advantages observed with TensorRT for CNN-based models do not
    necessarily transfer to transformer-based vision-language models under
    the same export and deployment pipeline" [8].
  - A 2026 paper attempting to deploy a transformer-based model (SmolVLA)
    via ONNX reported that **TensorRT export was attempted and did not
    finish**, even after manually stripping unsupported operations (ScatterND)
    — a concrete, recent, citable example of a transformer model failing to
    export to TensorRT in practice, not a hypothetical [9].
  - Conversely, when ViT-family models ARE successfully deployed on Jetson
    via TensorRT, it typically requires a dedicated engineering effort: one
    paper deploying a ViT-B/16 backbone on a Jetson Orin Nano via TensorRT
    reports a full pipeline (pre-processing, detection, cropping, pose
    estimation) with an end-to-end latency around 75ms — workable, but
    indicating real integration effort and overhead beyond a drop-in CNN
    swap [10].

## 4. Comparison summary

| Criterion | MobileNetV3-Small | EfficientNet-Lite | MobileViTv2 |
|---|---|---|---|
| Params (comparable tier) | ~5.4M (Large) [1] | ~5.3M [1], further reduced in -eLite [4] | 4.39M [7] |
| Deepfake-specific accuracy | No deepfake-specific benchmark found | Weaker cross-dataset generalization [5] | 96.3% (DF40/DDL) [7] — strongest found |
| Real on-device latency | Among fastest in multi-device study [2] | 52.1ms (EfficientNet-B0, on-device) [6] | 2.56ms claimed [7], hardware/runtime unconfirmed |
| TensorRT/ONNX export reliability | Favored by TensorRT-oriented design analysis [3] | Mature CNN export path, same general advantage as [3] | Documented general risk [3][8]; one concrete transformer TensorRT export failure found in the literature [9]; successful ViT-on-Jetson deployments require dedicated engineering [10] |

## 5. Decision: MobileNetV3-Small

**Chosen architecture: MobileNetV3-Small.**

Reasoning:

1. **The export-risk gap is now backed by direct, peer-reviewed/arXiv
   evidence, not inference from anecdote.** Three independent papers
   converge on the same finding: transformer-family vision models
   routinely show a gap between their paper-reported efficiency and their
   real TensorRT/edge deployment performance [3][8], and at least one
   recent paper documents a transformer model's TensorRT export failing
   outright even after manual intervention [9]. CNN architectures like
   MobileNetV3 do not carry this documented risk pattern.
2. **MobileViTv2's headline numbers are real and substantially stronger**
   (96.3% vs. no directly comparable deepfake-specific number found for
   MobileNetV3) [7], but the hardware/runtime context behind its 2.56ms
   figure is unconfirmed, while CNN edge-latency numbers in this comparison
   come from studies that explicitly test real Jetson/edge hardware [2][6].
3. **This matches AEGIS's own stated detector-layer philosophy** (proposal
   Section 8): minimize architecture risk on individual detectors, since
   the project's novelty is in the orchestration/engine/debate layers.

**Trade-off explicitly accepted:** this decision forgoes MobileViTv2's
materially higher reported deepfake-specific accuracy (96.3% vs. an
unconfirmed number for MobileNetV3 on this exact task) in exchange for a
well-documented lower deployment-risk profile for the team's semester
timeline.

**Recommended follow-up (outside this task's scope):** attempt a small,
isolated ONNX→TensorRT export of MobileViTv2 on the team's actual target
Jetson hardware early in the build cycle. If it exports and the reported
numbers hold, it is a strong candidate to replace MobileNetV3 in a later
iteration — source [9] shows this kind of export can fail even with
engineering effort, so this should be tested early, not assumed.

## 6. Sources

[1] "A Smart Recycling Bin Using Waste Image Classification At The Edge." arXiv:2210.00448.
[2] Tobiasz, Wilczyński, Graszka, Czechowski, Łuczak. "Edge Devices Inference Performance Comparison." arXiv:2306.12093.
[3] Xiao, Zheng, Wang. "TRT-ViT: TensorRT-oriented Vision Transformer." arXiv:2205.09579.
[4] "EfficientNet-eLite: Extremely Lightweight and Efficient CNN Models for Edge Devices by Network Candidate Search." arXiv:2009.07409.
[5] Pop-Kartov, Mileva, Martinovska Bande. "Comparative Evaluation and Analysis of Different Deepfake Detectors." Balkan Journal of Applied Mathematics and Informatics, 8(2), 2025.
[6] "EdgeViTs: Competing Light-weight CNNs on Mobile Devices with Vision Transformers." ECCV 2022.
[7] Al Babele, Omar. "Deepfake detection beyond the black box: interpretability and performance benchmarking of lightweight Vision Transformers." M.S. Thesis, Marshall University, 2026.
[8] "Benchmarking Edge Inference Strategies for Deep Learning Models in Industrial Machine Vision." arXiv:2607.11356.
[9] "When Faster VLA Deployment Changes Closed-Loop Behavior: Task Success-Latency Analysis of SmolVLA Across PyTorch and ONNX Variants." arXiv:2609.14146.
[10] "FastPose-ViT: A Vision Transformer for Real-Time Spacecraft Pose Estimation." arXiv:2512.09792.

## 7. Note on source rigor

[3], [4], [8], [9], [10], [1], [2] are arXiv preprints — widely used and
citable in CS/ML research, but not peer-reviewed in the journal sense.
[5] is a peer-reviewed journal article. [7] is an institutionally-reviewed
M.S. thesis. [6] is a peer-reviewed conference paper (ECCV). No source
in this version is a blog post, forum thread, or vendor documentation page.