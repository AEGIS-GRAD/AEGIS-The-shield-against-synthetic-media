# AEGIS — Month 3 Planning & Priorities Proposal

**Document Version:** 3.3.0-DRAFT  
**Date:** November 4, 2026 (repository evidence baseline: October 20, 2026)  
**Prepared by:** AI track  
**Supervisors:** Project Supervisors  
**Status:** Proposal for team discussion and supervisor review. All file paths, assignments, and success criteria below are proposals.

---

## 1. Context & Purpose

This document establishes an evidence-based roadmap for **Month 3** of AEGIS (deepfake verification system). Grounded in the empirical benchmarks, failure logs, and architectural bottlenecks identified in Month 2, it evaluates candidate priorities across AI and Cybersecurity tracks to provide a focused starting point for sprint planning.

---

## 2. What We Learned in Month 2

| Area | Verified Finding & Sample Size (n) | Source File |
| :--- | :--- | :--- |
| **LLM Planner** | 94.7% schema validation (18/19 passed; 1 key typo `estimated_latency_latency_s`). Min latency 21.8 s, median 155.5 s, max 365.5 s (n=19 runs). | `eval/reports/planner_v1_evaluation_summary.md:12`, `eval/reports/planner_v1_evaluation_notes.md` |
| **Planner Selection** | In the planner evaluation, planner chose `rppg` alone in 10/19 cases; `rppg` included in 15/19 cases (`eval/reports/rule_based_vs_llm_comparison_report.md:46`). 13/19 samples diverged from static rules (`eval/reports/rule_based_vs_llm_comparison_report.md:98`). | `eval/reports/rule_based_vs_llm_comparison_raw.csv`, `eval/reports/rule_based_vs_llm_comparison_report.md:46,98` |
| **Arbitration Latency** | Deterministic arbitration executes in 0.37 ms average (< 1 ms budget, n=20 cases). | `eval/reports/judge_prototype_eval.md:19` |
| **Forensic Guardrails** | 0/20 false-authentics on audit cases (~14–15% upper bound at 95% confidence by Rule of Three, on the 20-case audit set only). | `eval/reports/judge_prototype_eval_raw.csv` |
| **Streaming Ingestion** | Sustained 32 concurrent feeds at 24.5 FPS/feed (783 total FPS) with 0 socket drops, P95 network latency 0.18 ms, and 0 hash-chain breaks across 40,548 frames. **Gateway ingestion, mTLS, hash chaining, and PRNU only (excluded AI model inference).** | `eval/reports/streaming_load_test_report.md:25–48` |
| **Surveillance Attacks** | 8/8 correct verdicts on active streams (7/7 attacks flagged `INTEGRITY_UNKNOWN`; 1/1 clean verified `AUTHENTIC`). 1 network scenario (`auth_bypass`, 0 video frames) was skipped and is excluded from the 8/8 count. | `eval/reports/surveillance_benchmark_report.md:13–35` |

**Month 1 Baseline Context.** Month 1 pipeline accuracy (50.0%) was an artifact of missing `.pth` weights (random guessing) and broken center-crop face alignment (`eval/reports/video_classifier_refinement.md:14–19`). In `eval/reports/week_benchmark_raw.csv` (120 rows: 60 real, 60 fake), `orchestrator/app/aggregate.py` emitted 118 `UNCERTAIN` and 2 `AUTHENTIC` (both correct real). The 4 contested cases highlighted in `eval/reports/judge_prototype_eval.md` (`296.mp4`, `863.mp4`, `NeuralTextures_076_079.mp4`, `FaceSwap_507_418.mp4`) arose because `aggregate.py` emitted `UNCERTAIN`, which the Month 1 benchmark scoring convention counted as authentic (`eval/reports/week_benchmark_report.md:51`).

---

## 3. Known Gaps

- **G1 (Audio Severed from Debate)**: Commit `6ad7e83` hardcoded `DEBATE_KNOWN_DETECTORS = {"video-classifier", "rppg", "syncnet"}` in `orchestrator/app/judge_bridge.py:64` to suppress `ValueError: Unknown video detector(s): ['aasist']`. AASIST evidence is dropped before reaching the Judge Agent.
- **G2 (High Judge Abstention Rate)**: 65.0% (13/20) of audit cases defaulted to `INTEGRITY_UNKNOWN` (`eval/reports/judge_prototype_eval_raw.csv`). Accuracy on decided cases was 85.7% (6/7), with 1 false-synthetic on `067.mp4` (cause under investigation). **Confirmed absent from `docs/LIMITATIONS.md`.**
- **G3 (Planner Latency & Budget Gaming)**: Free-tier OpenRouter planning exhibited min 21.8 s, median 155.5 s, max 365.5 s (n=19), exceeding the <= 3 s P95 target in `docs/orchestrator_design.md:213`. In `eval/reports/planner_telemetry_slowdown_test.md:58`, the planner dropped AASIST citing the latency budget; the prompt does not weight accuracy (hypothesis, single test).
- **G4 (Unvalidated Edge Model & INT8 Slowdown)**: In `engine/benchmark/results.txt`, MobileNetV3-Small scored 50.00% accuracy and 60.00% EER across 10 videos (497 frames). Accuracy and EER are **invalid** because the classification head was randomly initialized (`engine/edge_model/build_edge_model.py:48–56`) and never trained on deepfakes; `engine/edge_model/mobilenetv3_small_ffpp.pth` exists (6.2 MB) but holds an untrained head despite its filename. Latency figures are indicative only (untrained model, 10 videos). ONNX INT8 was 1.68x slower than FP32 (2.84 ms vs 1.69 ms/frame), likely (unconfirmed) due to lack of CPU VNNI acceleration.

| Gap ID | Issue | Impact & Repository Evidence |
| :--- | :--- | :--- |
| **G5** | **AASIST Input Guardrail Gap** | Lacks VAD and SNR pre-filters (`detectors/aasist/app.py`), risking false positives on non-speech audio, environmental noise, and music (`docs/LIMITATIONS.md:3.3`). |
| **G6** | **Unvalidated Detector Baselines** | No detector has a post-fix benchmark with n >= 100 per class. AASIST 100% / 0.00% EER claim in `eval/reports/video_classifier_refinement.md:58` omits n. `eval/data/audio_subset` is not currently staged on disk (generated via `eval/scripts/make_audio_subset.py`). |
| **G7** | **Orchestrator API Security Bypass** | Omitting `X-API-Key` bypasses auth (`orchestrator/app/main.py:41–47`); CORS allows wildcard with credentials (`main.py:61–67`); host port 8000 exposed (`docker-compose.yml:75`). |
| **G8** | **Incomplete MVP-IN Forensics & Web View** | `debate/judge_agent.py:442–456` emits only a SHA-256 digest (`debate_transcript_hash`). `signed_timestamp` is an unauthenticated ISO string (`debate/schemas.py:108`); no asymmetric key signature exists. `web/src/app/reports/[id]/page.tsx:2` displays mock data. |
| **G9** | **Alert Router Unwired to Orchestrator** | `security/incident_response/alert_router.py` exists but is not imported or called in `orchestrator/app/main.py`, leaving file-based `siem_alert_tier` dispatch to Wazuh unwired. |

---

## 4. Assessment of Candidate Priorities

MVP scope boundaries (`CLAUDE.md:26–29`):
> - **IN**: video deepfake detection with explainability, real-time alerting, frame hash-chaining with tamper detection, signed chain-of-evidence report.  
> - **SECONDARY**: audio, basic fusion.  
> - **DEFERRED**: full multi-agent orchestration, learned fusion, production deployment.  
> - **NON-NEGOTIABLE** (supervisor priority): hash-chaining, digital forensics, chain of evidence.

1. **Candidate A: Alignment & Specification-Gaming Study**  
   *Assessment*: High academic thesis value analyzing budget-induced coverage degradation. Cost is high (~26 h for 600 sequential free-tier calls); full multi-agent orchestration is DEFERRED (`CLAUDE.md:28`). Gated by Decisions D1 (compute) and D2 (scope).
2. **Candidate B: Model Context Protocol (MCP) Integration**  
   *Assessment*: Moderate developer utility exposing verification tools to external agents. `mcp/` is an empty stub (1-paragraph `README.md`) and unlisted in MVP scope. Exposing tools before internal contracts and API security stabilize surfaces an incomplete system. Gated by Decision D3.
3. **Candidate C: Audio Modality Re-Integration & Hardening**  
   *Assessment*: Critical multi-modal completion resolving Gap G1. Requires claim adapter in `debate/claim_wrapper.py`, bridge update, and Silero VAD in `detectors/aasist/preprocessing.py`. Blocked by eligibility conflicts (`capability_manifests/aasist.json` lists only `"audio"`, conflicting with `orchestrator/app/rules.py` on video inputs).

---

## 5. Recommendation & Priority Order

To adhere to `CLAUDE.md:26–29`, **NON-NEGOTIABLE supervisor priorities and MVP-IN completions (Tier 1a) are ranked alongside core pipeline audio re-integration (Tier 1b)**. Tier 0 is prerequisite housekeeping, not one of the three candidates. All track allocations below are proposed, to be confirmed at the review meeting.

| Tier | Focus Area | Proposed Owner |
| :--- | :--- | :--- |
| **Tier 0** (Weeks 1–2) | Baseline Validation & Limitations Update | Proposed: AI Track |
| **Tier 1a** (Must Ship) | MVP-IN Forensics & Security Completion | Proposed: Cybersecurity & AI/Dev (D6 open) |
| **Tier 1b** (Must Ship) | Audio Modality Re-Integration & Hardening | Proposed: AI Audio Pod |
| **Tier 2** (Academic Milestone) | AI Safety & Specification-Gaming Study | Proposed: AI Track (conditional on D1, D2) |
| **Tier 3** (Targeted) | Interoperability & Runtime Optimization | Proposed: Cross-Track (conditional on D1, D3) |

---

## 6. Top Risks & Mitigations

1. **R-1 (AASIST Polarity Conflicts on Dubbed Media)**: High impact, medium likelihood. Pair Rule 4 (dubbing) and Rule 5 (cloning) with VAD language-confidence checks; require high confidence + VAD pass before `P1_CRITICAL`.
2. **R-2 (OpenRouter Rate Limits & Latency Spikes)**: High impact, high likelihood. Implement offline mock / local SLM harness; transition CI pipeline to deterministic offline tests.
3. **R-3 (Edge Model Unusable for Live Feeds)**: High impact, medium likelihood. Train/load real deepfake checkpoint in Tier 0; if hardware INT8 acceleration is absent, use FP32 backend.
4. **R-4 (Unmeasured Demographic & Compression Bias)**: Medium impact, high likelihood. FaceForensics++ lacks demographic labels (`docs/LIMITATIONS.md:4.1, 4.2`). Explicitly document limitation until a balanced dataset is acquired.

---

## 7. Open Decisions for Supervisors

- **D1 (Planner Compute & Hosting)**: Paid API key with latency SLA vs. local quantized SLM vs. deterministic rule fallback (to resolve free OpenRouter median latency of 155.5 s).
- **D2 (Alignment Study Definition & Scope)**: Confirm whether supervisors require an empirical red-teaming report on specification gaming or a theoretical safety framework, noting multi-agent orchestration is DEFERRED in `CLAUDE.md:28`.
- **D3 (MCP Scope Status)**: Confirm whether a lightweight read-only FastMCP server is approved or deferred out of MVP scope.
- **D4 (Surveillance Audio Scope)**: Confirm whether target CCTV camera streams carry audio; if not, audio hardening applies strictly to file verification.
- **D5 (Borderline Claims Resolution)**: Define intended judge behavior for detector scores in [0.35, 0.65] (currently dropped as coverage gaps by `debate/disagreement.py:59–63`).
- **D6 (API Security & Signing Ownership)**: Confirm track ownership between Cybersecurity and AI tracks for orchestrator API key enforcement, CORS restriction, and report signing.

---

## Appendix: Measurable Objectives & Pods

### A.1 Objectives & Success Criteria
- **O0 (Baselines & Edge Retraining)**: Standalone benchmarks on n >= 100/class. Retrain/load fine-tuned deepfake weights into `engine/edge_model/mobilenetv3_small_ffpp.pth` (proposed target: exceeding chance). Update `docs/LIMITATIONS.md` with 65% judge abstention.
- **O1 (Audio Re-Integration)**: End-to-end execution through `orchestrator -> judge_bridge -> JudgeAgent`. On a 20-sample cross-modal fixture set (`eval/fixtures/audio_visual/` [proposed]), proposed target: >= 9/10 on Direction A (authentic video + cloned audio) and >= 9/10 on Direction B (manipulated video + authentic audio). 0 false-synthetics on 10 clean ambient clips; proposed target <= 5.0% FPR on >= 100 noise/speech clips.
- **O2 (MVP-IN Signing, Security & Web)**: Digital signature verification via public key on exported JSON reports. Zero unauthenticated requests on orchestrator endpoints. Render real arbitration reports in web UI.
- **O3 (Alignment Study)**: Quantitative curve of detector omission rates under budgets from 1.0 s to 30.0 s. Exhaustive enumeration of guard decision table verifying Guard 1 & 2 prevent false-authentics across 100% of evaluated table states (finite decision table; not a universal claim).
- **O4 (FastMCP & Local SLM)**: MCP tool discovery verified via inspector. Local SLM planning latency <= 3.0 s P95 with >= 90% schema conformance.

### A.2 Proposed Functional Pods (Subject to Review Confirmation)
- **AI Audio & Debate Pod**: AASIST claim wrapper (`debate/claim_wrapper.py`), Rules 5 & 6 (`debate/arbitrator.py`), Silero VAD guard (`detectors/aasist/preprocessing.py`), cross-modal fixtures (`eval/fixtures/audio_visual/` [proposed]).
- **AI Baselines & Safety Pod**: Standalone baselines (n >= 100), edge model checkpoint retraining, `docs/LIMITATIONS.md` update, specification-gaming harness (`eval/scripts/benchmark_specification_gaming.py` [proposed]).
- **Cybersecurity Track**: Asymmetric report signing (`debate/judge_agent.py`), API security hardening (`orchestrator/app/main.py`), Wazuh SIEM alerting delivery, multi-feed load testing with AI inference. Proposed: Cybersecurity & AI/Dev (D6 open).
- **Cross-Track Infra Pod**: Web report UI integration (`web/src/app/reports/[id]/page.tsx`), FastMCP server (`mcp/server.py` [proposed]), local SLM benchmark (`orchestrator/app/planner_slm.py` [proposed]).
