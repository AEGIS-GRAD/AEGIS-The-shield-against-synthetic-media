# AEGIS — Early Failure Notes

Running log of misclassifications observed while benchmarking detectors. Updated after each benchmark pass (Week 2, Week 3, Week 4, ...) as more detectors come online. Goal: surface real, per-detector failure modes early so the Month 2 debate-layer design doesn't assume uniform reliability across detectors.

## How to use this doc
- After each benchmark run, pull the 10–15 worst misclassifications per detector (highest-confidence wrong predictions, plus any false negatives on known-hard samples).
- For each case, fill one row in the relevant detector's table below.
- At the end of each week's pass, add a short "Patterns observed" summary — this is the part that actually feeds the debate-layer design, not the raw rows.
- Don't delete old entries when a detector improves — strike them through or move them to the "Resolved" subsection so the history of what got fixed is preserved.

---

## Week 2 Benchmark

### Detector: Video Frame-Level Classifier (EfficientNet-B0, FF++ c23)

| # | Sample ID / path | True label | Predicted | Confidence | Notes on visible pattern |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

**Patterns observed:**
-

### Detector: AASIST (Audio Voice Spoofing)

| # | Sample ID / path | True label | Predicted | Confidence | Notes on visible pattern |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

**Patterns observed:**
-

### Detector: rPPG (Heartbeat Consistency, CHROM)

Note: rPPG has no trained decision boundary, so "misclassification" here means
cases where the signal-quality heuristic gave an implausible or clearly wrong
verdict — not a labeled accuracy failure. Also log cases where the estimated
BPM was wildly implausible (e.g. outside 40–180) even if the final verdict
happened to be correct, since that signals the extraction itself is unreliable
on that sample.

| # | Sample ID / path | True label | Predicted | Estimated BPM | Notes on visible pattern |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

**Patterns observed:**
-

### Cross-detector observations
-

---

## Week 3 Benchmark

### Detector: rPPG (Heartbeat Consistency, CHROM) — Edge-Case Validation

Stress tested against 4 deliberately tricky inputs + 1 clean baseline:

| # | Sample ID / path | Scenario | Pre-Guardrail Behavior | Post-Guardrail Verdict | Confidence | Evidence Flags & Notes |
|---|---|---|---|---|---|---|
| 1 | `eval/fixtures/edge_cases/short_clip.mp4` | Short clip (<2s, 24 frames) | **Crashed**: `ValueError: length of input vector must be greater than padlen (27)` in `sosfiltfilt` | `inconclusive` (score: 0.5) | 0.0 | `insufficient_duration`, `insufficient_signal`. Gracefully caught before filtering. |
| 2 | `eval/fixtures/edge_cases/poorly_lit.mp4` | Dark / underexposed (<8 mean px) | **False Alarm**: Zero spectral quality resulted in `1.0 - 0 = 1.000` (100% synthetic confidence) | `inconclusive` (score: 0.5) | 0.0 | `insufficient_lighting`, `insufficient_signal`. Low luminance guardrail triggered (mean lum 4.0/255). |
| 3 | `eval/fixtures/edge_cases/occluded_face.mp4` | Face partially occluded by black mask | **Misleading Authentic**: Center crop computed false periodic noise claiming 140 BPM with authentic verdict | `inconclusive` (score: 0.5) | 0.0 | `face_occluded`, `insufficient_signal`. Skin coverage heuristic (10.5% < 12%) detected occlusion. |
| 4 | `eval/fixtures/edge_cases/silent_video.mp4` | Silent video (no audio track) | Normal BVP extraction (rPPG is video-only) | `synthetic` (score: 0.703) | 0.405 | Normal inference; rPPG is unhindered by absence of audio track. |
| 5 | `eval/fixtures/edge_cases/clean_baseline.mp4` | Clean baseline reference | Normal BVP extraction | `synthetic` (score: 0.703) | 0.405 | Normal inference; sinusoidal skin fluctuation measured. |

**Patterns observed:**
- **Zero-signal inversion trap**: When rPPG cannot extract a periodic wave (e.g. pitch dark frames), raw spectral purity drops to `0.0`. Using `score = 1.0 - quality` naively mapped darkness to a 100% confident deepfake. Guardrails must intercept unextractable signal conditions before scoring.
- **Short-signal filter instability**: Classical Butterworth bandpass filtering with order 4 requires at least 27 samples for padlen. Any clip < 1.0s crashes scipy unless padded or short-circuited. Enforcing a 2.0s (30+ frames) minimum duration prevents numerical faults.
- **Occlusion spoofing**: A center-crop fallback in the absence of verified facial landmarks produces arbitrary RGB variance that can easily mimic cardiac pulse or random high-frequency noise.

---

### Detector: SyncNet (Audio-Visual Lip Sync) — Edge-Case Validation

| # | Sample ID / path | Scenario | Handling Behavior | Confidence | Evidence Flags | Forensic Claim |
|---|---|---|---|---|---|---|
| 1 | `silent_video.mp4` | Video with no audio track | Graceful skip | 0.5 (Neutral) | `['not_applicable']` | *"No audio track detected in submitted file — lip-sync analysis skipped."* |
| 2 | `clean_baseline.mp4` | Video with no audio track | Graceful skip | 0.5 (Neutral) | `['not_applicable']` | *"No audio track detected in submitted file — lip-sync analysis skipped."* |
| 3 | `short_clip.mp4` | Clip < 2s duration (24 frames) | Sliding window guardrail | 0.5 (Neutral) | `['not_applicable']` | Handled cleanly; 20 windows extracted without shape mismatch. |
| 4 | `poorly_lit.mp4` | Severely underexposed video | Luminance guardrail | 0.5 (Neutral) | `['not_applicable']` | Zero lip sequences extracted due to underexposure check. |
| 5 | `occluded_face.mp4` | Lower face occluded | Audio-absent / mouth check | 0.5 (Neutral) | `['not_applicable']` | Lip sync skipped gracefully. |

**Patterns observed:**
- SyncNet already incorporated an early audio absence check, correctly returning `not_applicable` instead of a 500 error or arbitrary desync score when audio is missing.
- When video frames are completely dark, preventing the sliding window generator from extracting fabricated mouth crops prevents false desync embeddings.

---

## Week 4 Benchmark
*(append here)*

---

## Resolved / Improved
Cases from earlier weeks that a later fix (preprocessing change, retraining, threshold tuning) resolved. Keep a one-line reference back to the original entry.

| Week found | Detector | Sample ID | Fix applied |
|---|---|---|---|
| Week 3 | rPPG | `short_clip.mp4` | Added duration guardrail (< 2.0s / 30 frames) in `preprocess.py` and safe `padlen` guard in `rppg_extract.py`. |
| Week 3 | rPPG | `poorly_lit.mp4` | Added luminance threshold guardrail (`mean_lum < 18.0`) returning neutral score (0.5) and `insufficient_lighting` flag. |
| Week 3 | rPPG | `occluded_face.mp4` | Added YCrCb skin-tone coverage heuristic (`skin_ratio < 0.12`) returning `face_occluded` flag. |
| Week 3 | SyncNet | `poorly_lit.mp4` | Added frame luminance guard in `extract_lip_sequences` to ignore dark non-facial frames. |
