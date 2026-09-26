# AEGIS LLM Orchestration Spike — Findings & Prompt Design Notes

> **Spike Summary & Prototype Evaluation**  
> *This document summarizes the findings from the exploratory LLM-driven detector-selection spike (`eval/scripts/llm_orchestration_spike.py` and `eval/notebooks/llm_orchestration_spike.ipynb`). This prototype is explicitly a spike and is NOT integrated into the production pipeline or `docker-compose.yml`.*

---

## 1. Goal of the Spike

The Month 1 baseline orchestrator uses hardcoded deterministic rules (`orchestrator/app/rules.py`) to select which detectors (`video-classifier`, `aasist`, `rppg`, `syncnet`) to invoke based on modality and audio presence.

This spike prototypes an **LLM-driven detector-selection planner** by:
1. Defining a static **Capability Manifest** describing detector capabilities, modalities, latencies, and constraints.
2. Passing sample metadata (modality, duration, resolution, audio track presence, file size) to an LLM via OpenRouter API.
3. Comparing LLM choices and stated reasoning side-by-side against the deterministic rule-based orchestrator across 10 evaluation samples.

---

## 2. Static Capability Manifest

| Detector Name | Modality | Expected Input | Approx Latency (ms) | Description |
|---|---|---|---|---|
| `video-classifier` | `video` | Video frames / MP4 | 5,142 ms | Frame-level EfficientNet-B0 visual spatial deepfake classifier. |
| `aasist` | `audio` | FLAC / WAV / MP4 audio track | 212 ms | Raw-waveform spectral audio spoofing & voice clone detector. |
| `rppg` | `video` | MP4 facial video ($\ge 2.0$s) | 4,507 ms | Physiological rPPG heartbeat-consistency detector (CHROM). |
| `syncnet` | `video+audio` | MP4 video + active audio track | 6,505 ms | Audio-visual lip-sync correlation detector evaluating mouth ROI. |

---

## 3. Side-by-Side Comparison Results

Evaluated across 10 representative samples from `eval/data/eval_manifest.csv` using OpenRouter models (`nvidia/nemotron-3-ultra-550b-a55b:free` & `inclusionai/ling-3.0-flash-fin:free`).

| # | Sample Name | Modality | Rule-Based Choice | LLM Choice | LLM Stated Reasoning Summary |
|---|---|---|---|---|---|
| 1 | `FaceShifter_761_766.mp4` | video | `video-classifier,rppg` | `video-classifier,rppg` | Sample is video with no audio (`has_audio: false`). Excluded `aasist` and `syncnet` due to missing audio. |
| 2 | `FaceSwap_507_418.mp4` | video | `video-classifier,rppg` | `video-classifier,rppg` | Selected `video-classifier` and `rppg` (duration 10s $\ge 2$s). Excluded `aasist` & `syncnet` due to missing audio. |
| 3 | `FaceShifter_817_827.mp4` | video | `video-classifier,rppg` | `video-classifier,rppg` | Selected video-only detectors; excluded audio-dependent detectors as `has_audio` is false. |
| 4 | `146.mp4` | video | `video-classifier,rppg` | `video-classifier,rppg` | Video MP4 without audio. `aasist` and `syncnet` excluded due to unsatisfied audio requirements. |
| 5 | `159.mp4` | video | `video-classifier,rppg` | `video-classifier,rppg` | Selected frame classifier and rPPG; excluded audio detectors. |
| 6 | `LA_E_6067252.flac` | audio | `aasist` | `aasist` | Audio-only FLAC file. Only `aasist` accepts audio input. Video detectors excluded due to modality mismatch. |
| 7 | `LA_E_5690036.flac` | audio | `aasist` | `aasist` | Audio-only FLAC file. `aasist` selected; video-based detectors excluded. |
| 8 | `LA_E_6340011.flac` | audio | `aasist` | `aasist` | FLAC audio input. Selected `aasist`; excluded video detectors. |
| 9 | `LA_E_5131937.flac` | audio | `aasist` | `aasist` | Audio-only FLAC input. `aasist` selected; modality mismatch for video detectors. |
| 10 | `LA_E_1354185.flac` | audio | `aasist` | `aasist` | Audio-only input. Selected `aasist`; excluded video and audio-visual detectors. |

---

## 4. Key Prompt-Design Observations & Issues

### A. Output Formatting & Code Fence Wrapping
* **Observation**: LLMs frequently wrap JSON responses in Markdown code blocks (e.g. ` ```json ... ``` `) or append conversational preamble/postamble.
* **Risk**: Passing raw LLM responses directly to `json.loads()` will throw `JSONDecodeError` unless stringently sanitized in code.
* **Mitigation**: Month 2 must enforce JSON mode (via API parameters or Instructor/Pydantic schemas) or strip markdown delimiters in code.

### B. Input Constraint Adherence
* **Observation**: When capability constraints were explicitly detailed in the prompt (`has_audio: false` $\rightarrow$ exclude `syncnet`/`aasist`), both Nemotron-3 Ultra and Ling-3.0 Flash Fin accurately respected the constraints.
* **Risk**: In complex or multi-turn prompts, smaller models may ignore constraints or hallucinate detector compatibility (e.g. selecting `syncnet` on silent video).
* **Mitigation**: Deterministic eligibility filters MUST run in code *before* passing candidate lists to the LLM. The LLM should only choose among candidate detectors pre-filtered by hard system constraints.

### C. Risk of Detector Name Hallucination
* **Observation**: Without explicit negative constraints, LLMs may invent plausible but non-existent detector names (such as `audio-classifier`, `facial-deepfake-v2`, or `lip-sync-detector`).
* **Mitigation**: Implement a strict post-selection validation filter against valid detector identifiers (`['video-classifier', 'aasist', 'rppg', 'syncnet']`).

### D. Latency & Compute Overhead
* **Observation**: Calling an LLM for detector selection adds 1.5–4.0 seconds of latency to the planning phase.
* **Impact**: For ultra-fast detectors like `aasist` (which runs in ~212ms), using an LLM for planning increases end-to-end processing time by **$10\times$**.
* **Mitigation**: Simple single-modality requests should use fast rule-based routing. LLM planning should be reserved for high-risk, ambiguous, or multi-stage debate workflows.

---

## 5. Architectural Recommendations for Month 2

1. **Hybrid Planning Pipeline**: Keep hard constraint enforcement (modality matching, file availability, duration requirements) in deterministic Python code. Use the LLM only to optimize detector combinations or sequence execution stages.
2. **Deterministic Fallback**: Always maintain the Task 1 rule-based orchestrator as a zero-latency fallback if the LLM times out (> 2.0s), fails JSON parsing, or encounters rate limits.
3. **Structured Response Contracts**: Require strict JSON schema validation for all model decisions before dispatching tasks.
