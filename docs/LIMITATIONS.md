# AEGIS — Detector Limitations Discovered During Benchmarking

**Author:** Role 3 — Benchmarking & Limitations
**Status:** Week 4 baseline — updated after each benchmark pass
**Feeds:** Month 2 debate-layer design & `orchestrator/app/rules.py` eligibility logic
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
| Score inversion (0 quality → 1.0 synthetic) | rPPG (resolved), others (at risk) | Mandate `status` field in all detector responses |
| Frame score variance | Video-classifier | Surface distribution (mean, max, std, % > 0.5) to debate layer |
| Non-speech audio | AASIST | Require VAD pre-filter or flag `low_confidence` |

---

## 7. Open Gaps and Month 2 Tasks

- [ ] **Quantified FPR/FNR tables per condition** — limitations above are qualitative; Task 1 benchmark report must fill in per-detector accuracy numbers for each failure condition.
- [ ] **Demographic bias benchmark** — disaggregated accuracy by skin tone, age, gender for the video-classifier.
- [ ] **Dubbed-content test set** — at least 20 authentic dubbed clips from public film/TV sources to quantify SyncNet's false-positive rate on legitimate dubbing.
- [ ] **AASIST and video-classifier input guardrails** — runtime `insufficient_signal` path matching rPPG's implementation.
- [ ] **Night-vision / IR footage handling** — current luminance guardrail is not calibrated for IR (which has high luminance values but is monochromatic).
- [ ] **Compression-level metadata enrichment** — `ffprobe` bitrate and codec history added to orchestrator `metadata.py` as an eligibility signal.
- [ ] **Per-frame score distribution surfaced to debate layer** — not just aggregated mean from the video-classifier.
- [ ] **VAD pre-filter for AASIST** — to isolate speech segments before scoring.

---

*Last updated: Week 4 baseline (2026-09-26). Append new findings here after each benchmark pass — do not delete earlier entries, mark resolved items with a strikethrough.*
