# AEGIS — Detector Limitations Discovered During Benchmarking

**Author:** Role 3 — Benchmarking & Limitations
**Status:** Week 4 baseline + Month 2 addendum — updated after each benchmark pass
**Feeds:** Month 2/3 debate-layer design, `orchestrator/app/rules.py` eligibility logic, and live surveillance pipeline
**Cross-references:** `docs/failure_notes.md`, `capability_manifests/*.json`, `eval/scripts/test_edge_cases.py`

---

## Purpose

This document synthesises all **systematic failure patterns** observed during the Week 3–4 benchmarking runs into detector-by-detector limitation profiles. Unlike `failure_notes.md` (a running log of individual misclassifications), this document captures *patterns* — generalised failure modes that the Month 2 debate layer, reliability loop, and LLM-driven orchestrator **must account for**.

Each section follows the same structure:

1. **Failure mode** — what breaks and in which conditions
2. **Root cause** — why it breaks technically
3. **Observed behaviour** — what the detector actually emits (before or after guardrails)
4. **Current mitigation** — guardrail or workaround already in place
5. **Residual risk** — what the mitigation does *not* cover
6. **Debate-layer implication** — how Month 2 should treat evidence from this detector in this condition

---

## 1. rPPG — Heartbeat Consistency Detector (CHROM Algorithm)

> **Modality:** Video only | **Input requirement:** >= 2.0 s, clear face, adequate light
> **Capability manifest:** `capability_manifests/rppg.json`

### 1.1 Low-Light / Underexposed Footage

| Attribute | Detail |
|---|---|
| **Failure mode** | Cannot extract a valid BVP pulse signal |
| **Root cause** | CHROM relies on sub-pixel skin-tone reflectance changes. Mean pixel luminance < 18/255 produces a near-zero RGB signal where all three channels collapse to the same noise floor, making the chrominance projections (Xc, Yc) indistinguishable from random thermal noise. |
| **Pre-guardrail behaviour** | Spectral purity score = 0.0 → `score = 1.0 - quality = 1.000` — a **confident 100% synthetic verdict** on content that may be completely authentic. |
| **Observed in** | `eval/fixtures/edge_cases/poorly_lit.mp4` (mean lum ~4.0/255) |
| **Current mitigation** | Luminance guardrail in `preprocess.py`: if `mean_lum < 18.0` the video is short-circuited before filtering, returning `inconclusive` (score 0.5, confidence 0.0) with flags `["insufficient_lighting", "insufficient_signal"]`. |
| **Residual risk** | Threshold of 18.0/255 is heuristic; videos shot in dim-but-recoverable lighting (lum ~18–40) may still produce degraded signals that pass the guardrail and emit a falsely confident verdict. Night-vision footage (IR-lit) will have a different luminance profile that the current guardrail ignores. |
| **Debate-layer implication** | Any rPPG result produced at luminance < 40/255 should be down-weighted to <= 0.3 confidence in the aggregation step. Never allow rPPG to cast the deciding vote on low-light inputs. |

---

### 1.2 Short Clips (< 2 Seconds / < 30 Frames)

| Attribute | Detail |
|---|---|
| **Failure mode** | Insufficient temporal signal for bandpass filtering |
| **Root cause** | The Butterworth bandpass filter (order 4) uses `sosfiltfilt` (zero-phase). `sosfiltfilt` requires a padding length of `3 x (2 x n_sections + 1)` samples; at 30 fps this exceeds 27 frames. Any clip shorter than ~1.0 s at 30 fps caused a `ValueError: length of input vector must be greater than padlen`. Additionally, the CHROM algorithm needs enough cardiac cycles to distinguish real pulse from noise — at least 1.5–2.0 s (2–3 heartbeats at typical 60–80 bpm). |
| **Pre-guardrail behaviour** | Hard crash (`ValueError` propagated to the caller) — no score returned, request failed. |
| **Observed in** | `eval/fixtures/edge_cases/short_clip.mp4` (0.8 s, 24 frames at 30 fps) |
| **Current mitigation** | Duration guardrail in `preprocess.py`: `duration_sec < 2.0 OR n_frames < 30` → `inconclusive`, flags `["insufficient_duration", "insufficient_signal"]`. Dynamic filter-order reduction in `_bandpass_filter` prevents the crash even if the guardrail is bypassed. |
| **Residual risk** | Clips of 2.0–3.0 s pass the guardrail but produce only 1–2 detectable heartbeat cycles. Spectral resolution is poor; the dominant peak is easily confused with motion artefacts or camera shake. |
| **Debate-layer implication** | For video under 5 s, treat rPPG confidence as halved. The orchestrator manifest already sets `min_duration_seconds: 2.0`; the debate layer must additionally apply a confidence decay for 2–5 s clips. |

---

### 1.3 Partially Occluded Face

| Attribute | Detail |
|---|---|
| **Failure mode** | Non-skin surface sampled as the face region, producing spurious or misleading BVP signal |
| **Root cause** | When the face detector (MTCNN or Haar cascade) cannot localise a face, the preprocessor falls back to a center-crop of the full frame. That crop includes whatever objects or surfaces occupy the frame center — masks, sunglasses, hats, hands — whose RGB variance can incidentally mimic a cardiac rhythm at 40–180 bpm. |
| **Pre-guardrail behaviour** | At ~10% skin coverage (lower face blocked by a black mask), CHROM extracted a signal reporting ~140 BPM and returned `authentic` — a false negative with non-trivial confidence. |
| **Observed in** | `eval/fixtures/edge_cases/occluded_face.mp4` (black mask covering lower 70% of face) |
| **Current mitigation** | YCrCb skin-tone coverage heuristic: if `avg_skin_ratio < 0.12` (< 12% of the bounding-box region contains skin-toned pixels) the video is flagged with `["face_occluded", "insufficient_signal"]` and returned as `inconclusive`. |
| **Residual risk** | The threshold of 12% is fragile for subjects with darker or lighter skin tones (YCrCb ranges Cr in [130,175], Cb in [75,130] are calibrated for medium skin). Faces partially occluded by transparent glasses, medical masks with skin-colored fabric, or heavy stage makeup may evade the heuristic. |
| **Debate-layer implication** | If `face_detection_ratio < 0.5` is reported in metadata, suppress rPPG's vote from the ensemble entirely, regardless of the guardrail status. The video-classifier or SyncNet lip-region detector is a more reliable signal when facial visibility is partial. |

---

### 1.4 Synthetic Baseline Scores Misleadingly High (Design-Level Limitation)

| Attribute | Detail |
|---|---|
| **Failure mode** | The rPPG quality score is a *proxy*, not a ground-truth measurement |
| **Root cause** | `score = 1.0 - signal_quality_score()` maps spectral purity of the BVP signal to a deepfake probability. This is a heuristic: real faces that happen to move a lot (head turns, talking) produce lower spectral purity → score shifts toward synthetic. Deepfakes generated from video-to-video face-swap of a live-action source can preserve the original's cardiac signal → score shifts toward authentic. |
| **Observed in** | `clean_baseline.mp4` (sinusoidal fixture with artificial oscillation) scored 0.703 synthetic — above the 0.5 threshold — because the synthetic cardiac pattern was too uniform (single pure frequency, no harmonic variation). |
| **Current mitigation** | None — this is a fundamental model limitation, not an input quality issue. |
| **Residual risk** | High for face-swap deepfakes (source video preserves real BVP) and low-activity real videos (still talking-head clips reduce spectral variation). |
| **Debate-layer implication** | rPPG should never be the primary signal for face-swap detection. It is most useful as a *confirming* secondary signal for reenactment deepfakes where temporal frame generation disrupts pulse continuity. Mark rPPG weight as 0.2–0.3 in the ensemble for face-swap inputs. |

---

## 2. SyncNet — Audio-Visual Lip Sync Detector

> **Modality:** Video + Audio | **Input requirement:** audio track present, clear lip region, adequate light
> **Capability manifest:** `capability_manifests/syncnet.json`

### 2.1 Silent Video (No Audio Track)

| Attribute | Detail |
|---|---|
| **Failure mode** | Cannot compute any lip-sync score |
| **Root cause** | SyncNet measures the cosine distance between audio-mel embeddings and visual lip-crop embeddings. Without an audio track there is no embedding to compare against. |
| **Pre-guardrail behaviour** | N/A — audio check existed from early implementation |
| **Observed in** | `eval/fixtures/edge_cases/silent_video.mp4` |
| **Current mitigation** | Early audio-absence check in `preprocess.py`: returns `([], [], has_audio=False)` immediately; `infer.py` returns `confidence=0.5`, `flags=["not_applicable"]`, forensic claim explicitly states audio is absent. |
| **Residual risk** | No false result risk. However, the orchestrator **must** exclude SyncNet before dispatch on silent inputs — calling it is wasted compute, not a correctness error. |
| **Debate-layer implication** | When SyncNet returns `not_applicable` due to absent audio, the debate layer must note a **coverage gap**: no AV-sync evidence is available. This gap must be surfaced in the final report and may require escalating to a higher-confidence detector (e.g., frame-level classifier plus AASIST on the extracted audio if one exists). |

---

### 2.2 Genuinely Authentic Dubbed / Foreign-Language Content

| Attribute | Detail |
|---|---|
| **Failure mode** | False positives on legitimately post-dubbed authentic video |
| **Root cause** | SyncNet was trained on English-language datasets (primarily VoxCeleb). The audio-visual correlation it learned reflects English phoneme-to-lip-shape pairings. Professional dubbing — whether for accessibility (voiceover), localisation (foreign language), or narration (documentary) — produces a valid audio track that is intentionally out-of-sync with the lip movements. SyncNet cannot distinguish intentional dubbing from deepfake AV-desync. |
| **Observed in** | Documented as a known risk in `capability_manifests/syncnet.json` and `docs/orchestrator_design.md`. Not yet quantified in benchmark (Week 4 TODO). |
| **Current mitigation** | None at the detector level. |
| **Residual risk** | High for foreign-language content, news clips with interpreter overlays, audiobook-style narration videos, and any content explicitly submitted for localisation review. |
| **Debate-layer implication** | The input metadata check should flag if the submitted language is non-English (via audio language detection or user-declared metadata) and suppress SyncNet's vote, or at minimum attach a `low_language_confidence` flag that the debate layer treats as a 50% weight reduction. If SyncNet fires a high-confidence synthetic verdict on content flagged as non-English, it should be challenged by the debate layer. |

---

### 2.3 Poorly Lit / Underexposed Frames

| Attribute | Detail |
|---|---|
| **Failure mode** | No lip sequences can be extracted |
| **Root cause** | The lip-crop pipeline relies on frame luminance to locate the mouth region. Severely dark frames (mean lum < threshold) cause the landmark detector to fail, producing zero valid lip sequences. |
| **Observed in** | `eval/fixtures/edge_cases/poorly_lit.mp4` |
| **Current mitigation** | Frame luminance guard in `extract_lip_sequences` (added Week 3): dark frames are skipped. If all frames are dark, returns `([], [], has_audio)` → `not_applicable`. |
| **Residual risk** | Same as rPPG: the luminance threshold is heuristic and may misclassify dim-but-recoverable footage. |
| **Debate-layer implication** | Treat identically to the silent-video case — surface a coverage gap. |

---

### 2.4 Face / Mouth Occlusion

| Attribute | Detail |
|---|---|
| **Failure mode** | Lip sequences extracted from wrong facial region, or not at all |
| **Root cause** | If the mouth is covered (mask, hand, off-screen), the landmark detector may return zero lip crops, or may lock onto a non-lip region that produces a spurious sync score. |
| **Observed in** | `eval/fixtures/edge_cases/occluded_face.mp4` |
| **Current mitigation** | Graceful skip: no lip crops → `not_applicable` returned. |
| **Residual risk** | Partial occlusion (e.g. only part of the mouth visible) may still produce embeddings from the partial region whose cosine distance is unreliable. |
| **Debate-layer implication** | If `face_detection_ratio < 0.5` (from rPPG metadata or orchestrator's ffprobe face check), apply an identical coverage gap note for SyncNet. |

---

## 3. AASIST — Audio Spoofing Detector

> **Modality:** Audio only | **Input requirement:** audio track >= 1.0 s
> **Capability manifest:** `capability_manifests/aasist.json`

### 3.1 Very Short Audio Clips (< 1 Second)

| Attribute | Detail |
|---|---|
| **Failure mode** | Unreliable or misfiring predictions |
| **Root cause** | AASIST uses spectro-temporal graph attention over the full clip. With < 1 s of audio, the spectrogram has too few temporal frames to build a meaningful graph; the model extrapolates from noise. |
| **Current mitigation** | Input constraint documented in `capability_manifests/aasist.json` (`min_duration_seconds: 1.0`). Not yet enforced by a runtime guardrail — the orchestrator eligibility filter must block short-audio dispatch. |
| **Residual risk** | The 1.0 s minimum is generous; informal testing suggests 2.0–3.0 s produces substantially more reliable results. |
| **Debate-layer implication** | For audio clips 1.0–2.0 s, halve AASIST's confidence weight in the ensemble. |

---

### 3.2 Channel / Codec Mismatch

| Attribute | Detail |
|---|---|
| **Failure mode** | Inference errors or degraded accuracy on non-standard audio formats |
| **Root cause** | AASIST was evaluated on 16 kHz mono WAV (ASVspoof 2019 LA set). Stereo MP3 at 44.1 kHz, or highly compressed codec artefacts (e.g. very low bitrate AAC), may interact unpredictably with the resampling step. |
| **Current mitigation** | Resampling is applied in preprocessing, but no guardrail validates the codec artefact level. |
| **Residual risk** | High for social-media video where audio has been transcoded multiple times. |
| **Debate-layer implication** | Weight AASIST results lower when the input audio has been through lossy re-encoding >= 2x (detectable via `ffprobe` codec history or bitrate anomalies). This is a Month 2 metadata enrichment task. |

---

### 3.3 Environmental Noise / Non-Speech Audio

| Attribute | Detail |
|---|---|
| **Failure mode** | False positives on crowd noise, music, or background audio |
| **Root cause** | AASIST is a binary synthetic-speech classifier. When the audio track contains significant non-speech content (music, background crowd, telephone ring), the model may classify the non-speech portions as synthetic because they lack the prosodic and phonation features of natural speech. |
| **Current mitigation** | None. |
| **Residual risk** | Moderate — most video input has some background noise. |
| **Debate-layer implication** | If a Voice Activity Detection (VAD) pre-filter is available, apply it before AASIST and only score speech segments. Until VAD is implemented, flag AASIST results as `low_confidence` for inputs where estimated speech-to-noise ratio < 10 dB. |

---

## 4. Video Frame-Level Classifier (Xception / EfficientNet-B0)

> **Modality:** Video, Image | **Input requirement:** face present, min 0.1 s
> **Capability manifest:** `capability_manifests/video-classifier.json`

### 4.1 Heavy Compression and Re-encoding Artefacts

| Attribute | Detail |
|---|---|
| **Failure mode** | Reduced detection accuracy; high false-negative rate on high-quality deepfakes |
| **Root cause** | Deepfake frame-level classifiers trained on FF++ (c23, mid-quality compression) are sensitive to compression level. Social-media platforms apply lossy re-encoding which destroys the subtle spatial artefacts (blending boundaries, frequency residuals) that the classifier relies on. A deepfake video downloaded from a social platform after 2x re-encoding may look identical to the classifier as an authentic compressed video. |
| **Current mitigation** | Documented in `capability_manifests/video-classifier.json`. No runtime mitigation. |
| **Residual risk** | Very high — this is the most serious failure mode for real-world deployment. All videos shared on major platforms are compressed. |
| **Debate-layer implication** | When the orchestrator detects high compression (via `ffprobe` video bitrate below threshold or quality estimate), the video-classifier verdict should be down-weighted. The rPPG and SyncNet detectors (which are not trained on specific artefacts) become relatively more reliable for compression-heavy inputs. |

---

### 4.2 Out-of-Distribution Face Types and Demographics

| Attribute | Detail |
|---|---|
| **Failure mode** | Systematic performance gap across demographic groups |
| **Root cause** | EfficientNet / Xception models trained on FF++ inherit the dataset's demographic distribution. FF++ skews toward lighter-skinned subjects. Dark skin absorbs more near-infrared light and has different texture frequency profiles — both factors affect the blending artefact signatures the model detects. |
| **Current mitigation** | None in place. |
| **Residual risk** | High — this is a known bias in the academic deepfake detection literature. |
| **Debate-layer implication** | Do not treat the classifier as equally reliable across all demographic groups until bias benchmarks (disaggregated by skin tone, age, and gender) are completed. Flag this as a Month 2 priority before any production deployment. |

---

### 4.3 Frame-Level Aggregation Variance

| Attribute | Detail |
|---|---|
| **Failure mode** | High per-frame score variance can mask or amplify actual video-level deepfake probability |
| **Root cause** | The classifier scores individual frames independently. Deepfake editing may affect only a subset of frames (e.g. a lip-sync deepfake where only the mouth region is manipulated). Averaging over all frames dilutes the signal; taking the max may amplify a single noisy frame. |
| **Current mitigation** | The current aggregation strategy (`orchestrator/app/aggregate.py`) uses mean or max — specific method to be confirmed. |
| **Debate-layer implication** | The debate layer should receive the *distribution* of per-frame scores (mean, max, std dev, % frames > 0.5), not just a single aggregated value. A high standard deviation with mean near 0.5 is diagnostically different from a low-variance mean of 0.5. |

---

## 5. Cross-Detector Patterns

### 5.1 The Silent-Video Coverage Gap

A video with no audio track completely disables both SyncNet and AASIST. Only the video-classifier and rPPG can provide evidence. For any deepfake technique that primarily manipulates audio (voice clone over authentic video), the two remaining detectors provide no signal.

**Debate-layer response:** Any analysis of a silent video must include a mandatory coverage-gap warning: *"No audio-based evidence is available. Audio-manipulation deepfakes (voice cloning, audio dubbing) cannot be assessed."*

---

### 5.2 The Dark-Frame Cascade

Poorly lit footage disables rPPG (no pulse extraction) and SyncNet (no lip crops). Only the video-classifier operates — with degraded accuracy, since FF++ models assume normal lighting. All four detectors are compromised simultaneously.

**Debate-layer response:** Reject or flag any analysis result on content where mean luminance < 40/255 as `insufficient_evidence`. Report this clearly rather than emitting a confident verdict from the weakest detector.

---

### 5.3 Score Inversion Trap

Multiple detectors map a "cannot extract signal" result to a neutral or low-quality score that is then *inverted* to produce a high synthetic-confidence output:

- rPPG: `score = 1.0 - spectral_quality`; if quality = 0.0 (signal unextractable), score = 1.0 = "100% synthetic"
- Any detector that conflates "I see nothing" with "this is fake" will produce false positives on all degraded inputs

**Pattern:** Every detector must distinguish `insufficient_signal` from `confident_synthetic`. This is now encoded in the orchestrator's `output` contract (`status` field), but the debate layer must enforce it — never escalate a result whose `status` is `insufficient_signal` to a confident verdict, regardless of the numeric score.

---

### 5.4 Guardrail Uniformity Gap

The three guardrails implemented in Week 3 (duration, luminance, occlusion) exist for rPPG and SyncNet. AASIST and the video-classifier do not yet have equivalent runtime input-quality checks. Until they do, the orchestrator's pre-dispatch eligibility filter (`orchestrator/app/rules.py`) is the only protection for those two detectors.

**Month 2 action item:** Each detector should implement its own `status: insufficient_signal` response path analogous to the rPPG guardrails. This is a prerequisite for the debate layer to function correctly on degraded inputs.

---

## 6. Month 2 Debate-Layer Design Implications Summary

| Limitation | Detector | Debate-Layer Action |
|---|---|---|
| Low-light footage | rPPG, SyncNet | Down-weight to <= 0.3 confidence; surface coverage gap |
| Short clip (< 2 s) | rPPG, AASIST | Confidence decay for 2–5 s; coverage gap for < 2 s |
| Face/mouth occlusion | rPPG, SyncNet | Suppress vote if `face_detection_ratio < 0.5` |
| Silent video | SyncNet, AASIST | Mandatory audio-coverage gap warning |
| Dubbed / foreign-language | SyncNet | Suppress or down-weight 50% |
| High compression | Video-classifier | Down-weight; elevate rPPG and SyncNet relatively |
| Demographic bias | Video-classifier | Flag until bias benchmarks complete |
| `insufficient_signal` status | All | Never escalate to confident verdict |
| Score inversion (0 quality → 1.0 synthetic) | rPPG (resolved in file path; open in streaming) | Mandate `status` field in all detector responses |
| Frame score variance | Video-classifier | Surface distribution (mean, max, std, % > 0.5) to debate layer |
| Non-speech audio | AASIST | Require VAD pre-filter or flag `low_confidence` |
| Streaming flat-signal inversion (M2-L1) | Streaming rPPG | Re-route flat signals to `UNCERTAIN` / `INSUFFICIENT_SIGNAL` |
| Warmup & gap blind spots (M2-L2) | Streaming rPPG | Invalidate rolling alerts during buffer re-accumulation |
| Uncalibrated SNR logistic (M2-L4) | Streaming rPPG | Calibrate midpoint and slope against in-distribution benchmarks |
| Equal-weights fusion collapse (M2-L6) | Live Pipeline Fusion | Decouple AI anomaly thresholds from static 0.5 weight dilution |
| Placeholder alert defaults (M2-L7) | Ingestion / Fusion | Enforce strict non-null evidence validation prior to SIEM escalation |
| Audio exclusion in debate (M2-L9) | Judge Agent / Bridge | Build dedicated AASIST claim adapter in `debate/claim_wrapper.py` |
| Static operating conditions (M2-L10) | Orchestrator Bridge | Dynamically bind real-time luminance & MTCNN bounding-box metadata |

---

## 7. Open Gaps and Month 2/3 Tasks

- [ ] **Quantified FPR/FNR tables per condition** — limitations above are qualitative; Task 1 benchmark report must fill in per-detector accuracy numbers for each failure condition.
- [ ] **Demographic bias benchmark** — disaggregated accuracy by skin tone, age, gender for the video-classifier.
- [ ] **Dubbed-content test set** — at least 20 authentic dubbed clips from public film/TV sources to quantify SyncNet's false-positive rate on legitimate dubbing.
- [ ] **AASIST input guardrails** — runtime `insufficient_signal` path matching rPPG's implementation. *(Note: ~~video-classifier guardrails~~ resolved in Month 2 via startup checkpoint validation and MTCNN alignment).*
- [ ] **Night-vision / IR footage handling** — current luminance guardrail is not calibrated for IR (which has high luminance values but is monochromatic).
- [ ] **Compression-level metadata enrichment** — `ffprobe` bitrate and codec history added to orchestrator `metadata.py` as an eligibility signal.
- [ ] **Per-frame score distribution surfaced to debate layer** — not just aggregated mean from the video-classifier.
- [ ] **VAD pre-filter for AASIST** — to isolate speech segments before scoring.
- [ ] **Fix Score-Inversion Trap in Streaming rPPG (M2-L1)** — Prevent flat signal from emitting `score=1.000` (SYNTHETIC) in `detectors/rppg/streaming/streaming.py`.
- [ ] **Eliminate Temporal Blind Spots during Gap Resets (M2-L2)** — Implement graceful interpolation or state carry-over for face-tracking interruptions.
- [ ] **Streaming rPPG Face ROI & Luminance Guardrails (M2-L3)** — Port MTCNN bounding-box and minimum luminance checks into `detectors/rppg/streaming/`.
- [ ] **Calibrate Streaming rPPG Logistic Mapping (M2-L4)** — Fit `snr_midpoint_db` and `snr_slope` against empirical benchmark distributions.
- [ ] **Wire Streaming rPPG into Live Surveillance Pipeline (M2-L5)** — Integrate multi-modal physiological verification alongside MobileNetV3 in `live_pipeline/`.
- [ ] **Calibrate Feed-Integrity Fusion Weights (M2-L6)** — Eliminate dead-zone where `ai_score in (0.35, 0.65)` trivially yields `UNCERTAIN`.
- [ ] **Remove Placeholder Evidence Fallbacks in SIEM Alerts (M2-L7)** — Replace empty-string SHA-256 and dummy camera IP with authentic forensic hardware bindings.
- [ ] **Fix Sliding Window Anomaly Attribution (M2-L8)** — Attribute stream anomalies across all overlapping temporal windows in `live_pipeline.py`.
- [ ] **Develop AASIST Debate Adapter (M2-L9)** — Enable Judge Agent to adjudicate audio deepfake claims alongside video detectors.
- [ ] **Dynamic Operating Conditions Binding in Orchestrator (M2-L10)** — Replace hardcoded `mean_luminance=None, face_detected=True` in `judge_bridge.py`.
- [ ] **Mitigate Judge Agent Over-Abstention & False-Alerts (M2-L11)** — Refine consensus thresholds to reduce 65% `INTEGRITY_UNKNOWN` rate and fix false-synthetic classifications.
- [ ] **Regenerate Clean Benchmark Fixtures (M2-L12, M2-L13)** — Replace random-weight Month 1 fixtures and commit authentic tampered stream datasets.
- [ ] **Resolve LLM Planner Latency SLA (M2-L14)** — Transition from high-latency shared free endpoints (21.8s–365s) to dedicated low-latency inference.
- [ ] **End-to-End Multi-Feed AI Inference Load Testing (M2-L15)** — Benchmark concurrent live streaming with active neural model execution, not just transport sockets.

---

## 8. Month 2 Findings & Limitations Profile (M2-L1 to M2-L15)

### 8.1 Streaming rPPG (`detectors/rppg/streaming/`)

#### M2-L1: Score Inversion Trap on Flat Signal
| Attribute | Detail |
|---|---|
| **Failure mode** | Flat or static facial ROIs produce a confident 100% synthetic verdict (`score = 1.000`). |
| **Root cause** | In `detectors/rppg/streaming/streaming.py` (`_evaluate`), when no spectral peak is detected in the cardiac frequency band or Welch power sum <= 0, the function returns `RPPGResult(True, 1.0, None, None, ..., "flat signal")`. |
| **Observed behaviour** | Static or motionless authentic faces that produce zero chrominance variation are classified as synthetic deepfakes with maximal confidence. |
| **Current mitigation** | None in streaming implementation (reintroduces the Month 1 flaw that was resolved for file-based rPPG). |
| **Residual risk** | Severe false-positive risk in live surveillance when a human subject sits completely still or lighting is static. |
| **Debate-layer / System implication** | Live pipeline must intercept `reason == "flat signal"` and map the result to `status: insufficient_signal` rather than treating `score=1.0` as genuine synthetic evidence. |
| **Evidence** | [detectors/rppg/streaming/streaming.py:L131-L132](file:///d:/Grad%20Projectt%20eccuuuuu/detectors/rppg/streaming/streaming.py#L131-L132); verified by unit test `detectors/rppg/tests/test_streaming_limitations.py::test_m2_l1_flat_signal_returns_confident_synthetic`. |

#### M2-L2: Contiguous Buffer Warmup & Gap Purge Blind Spots
| Attribute | Detail |
|---|---|
| **Failure mode** | Complete absence of physiological forensic evidence during initial warmup (first 6.0 seconds) and after minor face-tracking drops (> 1.0 second). |
| **Root cause** | `min_sec = 6.0` suppresses evaluation until 60 contiguous frames (at 10 FPS) accumulate. Any temporal discontinuity where `t - last_t > max_gap_sec (1.0s)` invokes `self.reset()`, completely emptying the FIFO buffer. |
| **Observed behaviour** | Emits `ready = False, score = None` during the first 6 seconds of a stream and immediately following transient head-turns or subject occlusion. |
| **Current mitigation** | Explicit `ready` boolean flag prevents emitting premature guesses. |
| **Residual risk** | Subjects moving in and out of surveillance frames cause persistent buffer thrashing, rendering rPPG perpetually unready and blind. |
| **Debate-layer / System implication** | Surveillance fusion must account for detector non-readiness without stalling real-time alert routing. |
| **Evidence** | [detectors/rppg/streaming/streaming.py:L74-L83](file:///d:/Grad%20Projectt%20eccuuuuu/detectors/rppg/streaming/streaming.py#L74-L83); verified by unit test `detectors/rppg/tests/test_streaming_limitations.py::test_m2_l2_no_evidence_during_warmup`. |

#### M2-L3: Unvalidated ROI & Full-Frame Background Sampling
| Attribute | Detail |
|---|---|
| **Failure mode** | Background environmental illumination variations are analyzed as physiological pulse signals. |
| **Root cause** | In `roi_mean_rgb(frame_bgr, box=None)`, when no bounding box is provided, the function averages across the entire frame without verifying facial presence, skin-tone ratio, or illumination adequacy. |
| **Observed behaviour** | Flashing monitors, room lighting shifts, or moving objects induce spurious periodic signals in the chrominance projection. |
| **Current mitigation** | Central 60% cropping applied only when a bounding box is explicitly supplied. |
| **Residual risk** | High risk of false-negative or false-positive pulse detection when face localizer fails to track. |
| **Debate-layer / System implication** | Require upstream face-tracker confidence metrics before forwarding frame ROIs to streaming rPPG. |
| **Evidence** | [detectors/rppg/streaming/streaming.py:L145-L157](file:///d:/Grad%20Projectt%20eccuuuuu/detectors/rppg/streaming/streaming.py#L145-L157); verified by unit test `detectors/rppg/tests/test_streaming_limitations.py::test_m2_l3_whole_frame_roi_when_no_box`. |

#### M2-L4: Uncalibrated Logistic SNR-to-Score Mapping
| Attribute | Detail |
|---|---|
| **Failure mode** | Synthetic probability scores are derived from heuristic, unvalidated logistic curves. |
| **Root cause** | Synthetic score is mapped via `score = 1.0 / (1.0 + exp(snr_slope * (snr_db - snr_mid)))` using arbitrary defaults (`snr_midpoint_db = 1.0`, `snr_slope = 0.6`) explicitly commented as *"heuristics to be calibrated on the /eval set"*. |
| **Observed behaviour** | Modest pulse signals (SNR ~2.5 dB) produce synthetic probabilities near 0.28 rather than confident authentic verdicts. |
| **Current mitigation** | None — parameters are static. |
| **Residual risk** | Systematic miscalibration of synthetic likelihood across diverse camera sensors. |
| **Debate-layer / System implication** | Treat raw streaming rPPG scores as uncalibrated ordinal rankings rather than calibrated Bayesian posteriors. |
| **Evidence** | [detectors/rppg/streaming/streaming.py:L45-L50, L138-L140](file:///d:/Grad%20Projectt%20eccuuuuu/detectors/rppg/streaming/streaming.py#L45-L50); verified by unit test `detectors/rppg/tests/test_streaming_limitations.py::test_m2_l4_fixed_logistic_snr_score_mapping`. |

---

### 8.2 Feed-Integrity Fusion & Live Surveillance Pipeline (`security/fusion/`, `live_pipeline/`)

#### M2-L5: Modality Disconnect — Streaming rPPG Omitted from Live Pipeline
| Attribute | Detail |
|---|---|
| **Failure mode** | Live surveillance pipeline operates strictly on single-frame 2D spatial features, lacking physiological cross-verification. |
| **Root cause** | `live_pipeline/live_pipeline.py` wires `SlidingWindowDetector` (MobileNetV3) into `FeedFusionEngine`, but does not integrate or instantiate `StreamingRPPG`. |
| **Observed behaviour** | Deepfakes preserving structural boundaries but destroying temporal cardiac continuity evade physiological detection in the live stream. |
| **Current mitigation** | Spatial MobileNetV3 edge model INT8 inference is active. |
| **Residual risk** | The live surveillance path is monomodal regarding AI detection, contradicting AEGIS's multi-modal architecture. |
| **Debate-layer / System implication** | Milestone presentations must clearly document that Month 2 surveillance AI evaluation reflects spatial CNN features only. |
| **Evidence** | [live_pipeline/live_pipeline.py:L24-L27, L123-L136](file:///d:/Grad%20Projectt%20eccuuuuu/live_pipeline/live_pipeline.py#L24-L27). |

#### M2-L6: Mathematical Degeneracy of Equal-Weighted Fusion Verdicts
| Attribute | Detail |
|---|---|
| **Failure mode** | Combined score thresholds are mathematically unreachable or degenerate when integrity is clean. |
| **Root cause** | With `w_integrity = 0.5` and `w_ai = 0.5`, under clean feed integrity (`integrity_score = 0.0`), `combined_score = 0.5 * ai_score`. Because `combined_score` cannot exceed 0.5, the condition `combined_score >= synthetic_threshold (0.65)` never triggers; the verdict is decided exclusively by `ai_score >= 0.65`. |
| **Observed behaviour** | For any `ai_score` in the interval (0.35, 0.65), the engine defaults to `UNCERTAIN` regardless of pristine feed integrity. |
| **Current mitigation** | Hardcoded secondary check `ai_score >= synthetic_threshold` catches synthetic alerts. |
| **Residual risk** | Weighted averaging dilutes the AI forensic score and obscures nuanced threat levels. |
| **Debate-layer / System implication** | Move from linear scalar combination to hierarchical multi-condition rule engines in Month 3. |
| **Evidence** | [security/fusion/feed_fusion.py:L154-L167](file:///d:/Grad%20Projectt%20eccuuuuu/security/fusion/feed_fusion.py#L154-L167); verified by unit test `security/fusion/tests/test_fusion_limitations.py::test_m2_l6_equal_weights_verdict_reduces_to_ai_threshold`. |

#### M2-L7: Synthetic & Placeholder Evidentiary Fallbacks in Incident Alerts
| Attribute | Detail |
|---|---|
| **Failure mode** | SIEM / SOC alert payloads contain hardcoded placeholder values when caller context is omitted. |
| **Root cause** | In `build_incident_alert()`, unsupplied camera metadata defaults to `192.168.10.50`, and missing forensic hashes default to `e3b0c442...` (the SHA-256 digest of an empty string). |
| **Observed behaviour** | Security logs record identical cryptographic signatures and network addresses for distinct surveillance camera nodes. |
| **Current mitigation** | Fallback prevents `AttributeError` during incident dispatch. |
| **Residual risk** | Corrupts court-admissibility under ISO/IEC 27037 by logging false evidentiary provenance. |
| **Debate-layer / System implication** | Enforce strict schema validation: reject alert creation if hardware fingerprint or frame hash is missing. |
| **Evidence** | [security/fusion/feed_fusion.py:L211-L216, L257](file:///d:/Grad%20Projectt%20eccuuuuu/security/fusion/feed_fusion.py#L211-L216); verified by unit test `security/fusion/tests/test_fusion_limitations.py::test_m2_l7_alert_uses_placeholder_evidence_when_omitted`. |

#### M2-L8: Temporal Anomaly Boundary Misattribution Across Sliding Windows
| Attribute | Detail |
|---|---|
| **Failure mode** | Stream integrity anomalies occurring in overlapping frames are attributed to only one sliding window. |
| **Root cause** | In `live_pipeline/live_pipeline.py`, `self.window_anomalies = []` clears all accumulated sequence/timestamp errors every stride (8 frames), but the window size is 16 frames. |
| **Observed behaviour** | An anomaly at frame index 12 is evaluated in Window $N$, but discarded before Window $N+1$ processes the same frame. Additionally, `prnu_pce` is passed into metadata but never thresholded against `50.0` in the fusion calculation. |
| **Current mitigation** | All anomalies are tracked globally in `self.all_anomalies`. |
| **Residual risk** | Window-level SIEM alerts have inconsistent tamper context across consecutive evaluations. |
| **Debate-layer / System implication** | Use sliding deque for anomaly tracking matching the frame buffer window size. |
| **Evidence** | [live_pipeline/live_pipeline.py:L264](file:///d:/Grad%20Projectt%20eccuuuuu/live_pipeline/live_pipeline.py#L264); verified by unit test `security/fusion/tests/test_fusion_limitations.py::test_m2_l8_prnu_pce_not_thresholded_in_fusion`. |

---

### 8.3 Judge Agent Integration & Production Bridge (`orchestrator/app/judge_bridge.py`)

#### M2-L9: Complete Audio Modality Suppression (AASIST Dropped from Adjudication)
| Attribute | Detail |
|---|---|
| **Failure mode** | Audio spoofing and synthetic voice claims are completely excluded from Judge Agent arbitration. |
| **Root cause** | `orchestrator/app/judge_bridge.py` defines `DEBATE_KNOWN_DETECTORS = {"video-classifier", "rppg", "syncnet"}`. Any detector not in this set (including `aasist`) is filtered out before calling `judge.judge_file()`. |
| **Observed behaviour** | When AASIST detects a synthetic voice attack with 100% confidence, the Judge Agent never sees the evidence and rules solely on video consensus. |
| **Current mitigation** | AASIST raw results are preserved in `OrchestrationResponse.raw_results`. |
| **Residual risk** | Complete blind spot to audio-driven deepfake attacks in final adjudicated forensic reports. |
| **Debate-layer / System implication** | High priority for Month 3: implement AASIST claim adapter in `debate/claim_wrapper.py`. |
| **Evidence** | [orchestrator/app/judge_bridge.py:L64-L73](file:///d:/Grad%20Projectt%20eccuuuuu/orchestrator/app/judge_bridge.py#L64-L73). |

#### M2-L10: Static Environmental Operating Conditions Bypass Precedence Matrix
| Attribute | Detail |
|---|---|
| **Failure mode** | Specialized precedence rules (low-light attenuation, facial occlusion discounting) cannot fire in production. |
| **Root cause** | In `build_operating_conditions()`, the bridge hardcodes `mean_luminance = None` and `face_detected = True`. |
| **Observed behaviour** | Video clips shot in pitch-dark conditions or with heavily masked faces never trigger Rule 1 (low light) or Rule 2 (face occlusion) in the Forensic Precedence Matrix. |
| **Current mitigation** | Baseline consensus and cross-examination still execute. |
| **Residual risk** | Degraded inputs receive full analytical weight rather than being discounted. |
| **Debate-layer / System implication** | Enrich `InputMetadata` with runtime luminance and face-detection ratios extracted by detector preprocessors. |
| **Evidence** | [orchestrator/app/judge_bridge.py:L108-L110](file:///d:/Grad%20Projectt%20eccuuuuu/orchestrator/app/judge_bridge.py#L108-L110). |

#### M2-L11: High Abstention Rate (65% INTEGRITY_UNKNOWN) and Single-Sample False-Synthetic P1 Failure
| Attribute | Detail |
|---|---|
| **Failure mode** | The Judge Agent abstains from rendering decisive verdicts on nearly two-thirds of contested cases, and misclassifies one authentic case as high-severity synthetic. |
| **Root cause** | Guard 1 (Polarity Inversion Anti-Default) aggressively forces `INTEGRITY_UNKNOWN` whenever conflicting detectors disagree across the 0.5 boundary. On sample `067.mp4` (`m1-case-010`), authentic video was misjudged as `SYNTHETIC (0.78)` with a `P1_CRITICAL` alert. |
| **Observed behaviour** | Across 20 Month 1 audit cases: 13 cases (65.0%) result in `INTEGRITY_UNKNOWN`; 7 cases produce decisive verdicts, of which 6 are correct (85.7% decisive precision) and 1 is a false-synthetic. Overall strict accuracy is 30.0% (6/20). |
| **Current mitigation** | Completely eliminates catastrophic false-authentics (0 fakes certified as authentic). |
| **Residual risk** | Operational alert fatigue from excessive `INTEGRITY_UNKNOWN` escalations requiring human review. |
| **Debate-layer / System implication** | Refine consensus thresholds and corroboration weights in Month 3 to narrow the abstention band. |
| **Evidence** | [eval/reports/month2_vs_month1_full_benchmark_raw.csv:L21-L40](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/month2_vs_month1_full_benchmark_raw.csv#L21-L40); audited by `eval/scripts/month2_metrics_audit.py`. |

---

### 8.4 Evaluation, Latency & Benchmarking Methodology (`eval/`)

#### M2-L12: Historical Fixture Provenance Poisoning (Random-Weight Checkpoints)
| Attribute | Detail |
|---|---|
| **Failure mode** | Judge Agent evaluation cases were constructed from detector outputs that were generated while the video-classifier was broken. |
| **Root cause** | 15 of the 20 cases in `eval/fixtures/judge/month1_judge_cases.json` were extracted from Month 1 benchmark runs (`eval/reports/week_benchmark_raw.csv`), during which the video-classifier was silently evaluating uninitialized random network weights (see `eval/reports/video_classifier_refinement.md`). |
| **Observed behaviour** | The judge was evaluated on resolving arbitrary mathematical noise rather than genuine forensic classifier discordance. |
| **Current mitigation** | Benchmarking verified the arbitration logic's mathematical stability under conflict. |
| **Residual risk** | Reported accuracy metrics do not reflect the judge's performance on real, calibrated EfficientNet-B0 detector outputs. |
| **Debate-layer / System implication** | Re-run full judge benchmark against fixtures generated with the fine-tuned, weight-loaded detector. |
| **Evidence** | [eval/scripts/build_judge_cases.py:L18-L20](file:///d:/Grad%20Projectt%20eccuuuuu/eval/scripts/build_judge_cases.py#L18-L20); [eval/reports/video_classifier_refinement.md:L14-L20](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/video_classifier_refinement.md#L14-L20). |

#### M2-L13: Benchmark Circularity & Missing Ground-Truth Stream Fixtures
| Attribute | Detail |
|---|---|
| **Failure mode** | 100% tamper detection in the surveillance benchmark is guaranteed by synthetic flag injection, not measured from live raw video. |
| **Root cause** | In `eval/scripts/benchmark_month2_vs_month1.py`, `hash_ok` and `prnu_ok` booleans are assigned directly based on whether `"clean"` or `"splice"` appears in the scenario name string. Furthermore, the dataset folder `security/fixtures/tampered_streams/` is omitted from the git repository. |
| **Observed behaviour** | Live pipeline benchmark passes 8/8 active scenarios, but verifies only downstream fusion branching, not upstream PRNU wavelet extraction or hash-chain reconstruction. |
| **Current mitigation** | Separate unit and harness tests exist in `security/fusion/tests/`. |
| **Residual risk** | False sense of empirical security regarding live camera attack resilience. |
| **Debate-layer / System implication** | Commit reproducible video fixtures and wire true live validation into the benchmark suite. |
| **Evidence** | [eval/scripts/benchmark_month2_vs_month1.py:L239-L240](file:///d:/Grad%20Projectt%20eccuuuuu/eval/scripts/benchmark_month2_vs_month1.py#L239-L240). |

#### M2-L14: Unresolved LLM Planning Latency SLA Breakdown
| Attribute | Detail |
|---|---|
| **Failure mode** | LLM planner response times exceed the 3.0-second architectural latency SLA by 10× to 120×. |
| **Root cause** | Live cloud LLM queries via OpenRouter's free tier (`nvidia/nemotron-3.5-lightning:free`) encounter severe queuing delays and timeouts. Benchmark evaluation in Task 3 substituted `mock_llm=True` to avoid pipeline stalls. |
| **Observed behaviour** | Real-world planning latency ranges from 21.8 s to 365.5 s (P95 > 200 s). In Task 3, 5 of 19 sample runs fell back to the static rule-based baseline. |
| **Current mitigation** | Deterministic local fallback prevents catastrophic service failure. |
| **Residual risk** | Real-time adaptive planning is completely unusable in live or interactive media verification under free cloud routing. |
| **Debate-layer / System implication** | Month 3 priority: transition planner to local quantized model execution on dedicated edge GPU. |
| **Evidence** | [eval/reports/planner_v1_evaluation_summary.md:L40-L56](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/planner_v1_evaluation_summary.md#L40-L56); [eval/scripts/benchmark_month2_vs_month1.py:L109](file:///d:/Grad%20Projectt%20eccuuuuu/eval/scripts/benchmark_month2_vs_month1.py#L109). |

#### M2-L15: Disconnected Load Testing (Transport Throughput vs. Model Inference)
| Attribute | Detail |
|---|---|
| **Failure mode** | "32 feeds PASS" load test validates network socket I/O but excludes neural network computational saturation. |
| **Root cause** | `eval/scripts/load_test_streaming_pipeline.py` measures client `sendall()` latency and gateway socket concurrency. The AI sliding window detector (MobileNetV3) was not instantiated in the load test loop. |
| **Observed behaviour** | Sub-millisecond latency (0.18 ms P95) is reported for 32 feeds, while actual edge model inference takes 48–55 ms per window. |
| **Current mitigation** | Validates gateway asyncio connection management and DoS resilience. |
| **Residual risk** | Live deployment assuming 32 concurrent feeds will suffer catastrophic GPU/CPU starvation once neural inference is enabled. |
| **Debate-layer / System implication** | Re-run multi-feed load tests with edge neural inference actively processing every sliding window. |
| **Evidence** | [eval/reports/streaming_load_test_report.md:L51-L54](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/streaming_load_test_report.md#L51-L54). |

---

*Last updated: Month 2 wrap-up (2026-10-27). Append new findings here after each benchmark pass — do not delete earlier entries, mark resolved items with a strikethrough.*

