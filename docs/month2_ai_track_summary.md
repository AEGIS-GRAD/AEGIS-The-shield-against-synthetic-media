# AEGIS — Month 2 AI Track: Results, Lessons & Open Questions

**Audience:** Cybersecurity track, Dev/Orchestration track, Web/UX track, Dr. Amr Megahed, Eng. Ramez Yousri, Eng. Nada Medhat  
**Author:** Mohand Mohsen (AI Track Lead)  
**Status:** Complete Deliverable (Month 2 — Task 6 Deliverable)  
**Purpose:** What the AI track *learned* this month, not just what it shipped — for the Month 2 milestone review.  
**Source Data:**
- Full Unified Benchmark: [eval/reports/month2_vs_month1_full_benchmark_raw.csv](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/month2_vs_month1_full_benchmark_raw.csv), [eval/reports/month2_vs_month1_full_benchmark_report.md](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/month2_vs_month1_full_benchmark_report.md)
- Recomputed Audit Record: [eval/reports/month2_metrics_audit.json](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/month2_metrics_audit.json) via [eval/scripts/month2_metrics_audit.py](file:///d:/Grad%20Projectt%20eccuuuuu/eval/scripts/month2_metrics_audit.py)
- Subsystem Evaluations: [eval/reports/judge_prototype_eval.md](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/judge_prototype_eval.md), [eval/reports/surveillance_benchmark_report.md](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/surveillance_benchmark_report.md), [eval/reports/streaming_load_test_report.md](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/streaming_load_test_report.md), [eval/reports/planner_v1_evaluation_summary.md](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/planner_v1_evaluation_summary.md)
- Grounded Limitations & Planning: [docs/LIMITATIONS.md](file:///d:/Grad%20Projectt%20eccuuuuu/docs/LIMITATIONS.md) (Section 8: M2-L1 to M2-L15), [docs/month3_planning.md](file:///d:/Grad%20Projectt%20eccuuuuu/docs/month3_planning.md)

---

## 10-Minute Milestone Walkthrough Agenda
1. **00:00 – 02:00:** What Month 2 Shipped (The 5 New System Layers) — *Section 1*
2. **02:00 – 04:30:** Audited Benchmark Results & As-Reported vs. Audited Ground Truth — *Section 2*
3. **04:30 – 06:30:** Core Findings: The Safety vs. Coverage Trade-Off & Injected Invariants — *Section 3*
4. **06:30 – 08:30:** Reliability, Latency & Architecture Deficits (M2-L1 to M2-L15) — *Section 4*
5. **08:30 – 10:00:** Key Decisions & Proposed Month 3 Priorities (C1 to C5) — *Sections 5 & 6*

---

## 1. What Month 2 Shipped

In Month 2, the AI track moved AEGIS from isolated, static heuristics into a closed-loop multi-agent verification system:
- **Telemetry-Grounded LLM Planner (`orchestrator/app/planner.py`, `telemetry_client.py`)**: Gathers live Prometheus metrics (P95 latency, error rates, RAM) and capability manifests to dynamically assemble budget-aware detector execution plans.
- **Multi-Round Judge Agent (`debate/judge_agent.py`)**: Operates a 3-round structured forensic debate protocol with Digital Forensics Guardrails (G1 & G2) and a Forensic Precedence Matrix, generating court-admissible justification narratives under ISO/IEC 27037.
- **Judge-Orchestrator Bridge (`orchestrator/app/judge_bridge.py`, `main.py`)**: Replaced Month 1's naive mathematical averaging (`aggregate.py`) with end-to-end judge arbitration for every media submission.
- **Feed-Integrity Fusion Engine (`security/fusion/feed_fusion.py`)**: Fuses hardware PRNU noise, rolling SHA-256 hash chains, and sequence jitter with deepfake content anomaly scores into unified incident alerts with SIEM escalation tiers.
- **Edge Model Quantization & Streaming Pipeline (`engine/edge_model/`, `live_pipeline/`)**: Deployed fine-tuned MobileNetV3-Small INT8 ONNX models processing live video streams at 48–55 ms per 16-frame window.

---

## 2. Benchmark Results: Both Paths (Audited Evaluation)

The table below reflects the mathematically verified metrics recomputed directly from [eval/reports/month2_vs_month1_full_benchmark_raw.csv](file:///d:/Grad%20Projectt%20eccuuuuu/eval/reports/month2_vs_month1_full_benchmark_raw.csv) using [eval/scripts/month2_metrics_audit.py](file:///d:/Grad%20Projectt%20eccuuuuu/eval/scripts/month2_metrics_audit.py).

<!-- AUDIT:BEGIN -->
| Path / Subsystem | Metric Dimension | Month 1 Baseline | Month 2 Reported | Month 2 Audited Value | Forensic / Operational Reality |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **File Path: Judge Agent** | **Strict Accuracy** | 55.0% (11/20) | 85.00% | **30.0% (6/20)** | Only decisive verdicts (AUTHENTIC/SYNTHETIC) count as correct. |
| **File Path: Judge Agent** | **Decisive Precision** | n/a | n/a | **85.7% (6/7)** | True source of "85%": 6 of 7 decisive verdicts were correct. |
| **File Path: Judge Agent** | **Coverage / Abstention** | 100% | 100% | **35.0% coverage / 65.0% abstention** | 13/20 cases yielded `INTEGRITY_UNKNOWN` (P2 Elevated Alert). |
| **File Path: Judge Agent** | **False-Authentics** | 9 cases | 0 cases | **0 cases (0/20)** | Hard Guard 1 successfully prevented all fake media certifications. |
| **File Path: Judge Agent** | **False-Synthetics** | 0 cases | 0 cases | **1 case (1/20)** | Sample `067.mp4` (REAL) classified as `SYNTHETIC (0.78)` (P1 Alert). |
| **File Path: Planner** | **Divergence Rate** | 0.0% (static) | 68.4% | **68.4% (13/19)** | Derived under `mock_llm=True`; unverified against live LLM SLA. |
| **File Path: Planner** | **Fallback Rate** | 0.0% | n/a | **26.3% (5/19)** | 5 cases triggered automatic fallback to deterministic baseline. |
| **Surveillance: Fusion** | **Tamper Detection** | 0.0% (blind) | 100.0% | **100.0% (8/8)** | Validates branching logic, but flags were injected from scenario names. |
| **Surveillance: Edge** | **Real-Time Ratio** | ~1.35 (FP32) | 0.22–0.25 | **0.156 – 0.177** | INT8 edge model window inference runs well within 33.3ms budget. |
<!-- AUDIT:END -->

### 2.1 Side-by-Side: "As Reported" vs. "Audited" Reality

To ensure complete transparency across engineering tracks, the AI track presents the documented differences between the initial Task 3 deliverable report and the recomputed data:

| Metric Target | As Reported in Task 3 | Audited Reality | Why the Numbers Differ |
| :--- | :---: | :---: | :--- |
| **Judge Accuracy** | **85.00%** | **30.0%** (Strict) / **85.7%** (Decisive) | The Task 3 report hardcoded `"85.00%"` into the Markdown template. In the raw data, 13 of 20 cases (65.0%) produced `INTEGRITY_UNKNOWN` (abstention). Of the 7 cases where the judge rendered a decisive verdict, 6 were correct ($6/7 = 85.7\%$). The scoring script erroneously marked `INTEGRITY_UNKNOWN` rows as `"CORRECT"`. |
| **Month 1 Baseline** | **50.00%** | **55.0%** (11/20) | On the 20 specific contested audit cases, Month 1's heuristic convention (treating `UNCERTAIN` as authentic) scored 11 correct, with 9 catastrophic false-authentics. |
| **False-Authentic Certifications** | **0 cases** | **0 cases** ✅ | **Confirmed.** Guard 1 (Polarity Inversion Anti-Default) and Guard 2 (Corroboration Requirement) successfully prevented all 9 Month 1 false-authentics. |
| **False-Synthetic Certifications** | **0 cases** | **1 case** | On sample `067.mp4` (`m1-case-010`), authentic video was misclassified as `SYNTHETIC (0.78)` and routed as a `P1_CRITICAL` alert. |
| **Surveillance Tamper Detection** | **100.0%** (8/8) | **100.0%** (by construction) | In `benchmark_month2_vs_month1.py` ([L239–240](file:///d:/Grad%20Projectt%20eccuuuuu/eval/scripts/benchmark_month2_vs_month1.py#L239-L240)), `hash_ok` and `prnu_ok` were set based on whether `"clean"` appeared in the scenario name string. This proves downstream fusion branching works, but does not benchmark live PRNU wavelet extraction. |
| **Surveillance Real-Time Ratio** | **0.22 – 0.25** | **0.156 – 0.177** | The template hardcoded 0.22–0.25. The actual measured INT8 edge model execution was even faster (15.6%–17.7% of budget). |
| **Planner Divergence** | **68.4%** (13/19) | **68.4%** (Mock LLM) | The divergence from static rules is mathematically confirmed, but was executed with `mock_llm=True`. Live cloud LLM queries failed the ≤3.0s latency budget. |

*Recommendation to Task 3 Author:* Update `eval/scripts/benchmark_month2_vs_month1.py` to dynamically compute strict accuracy, decisive precision, and coverage rate from `judge_results` rather than using static f-string constants.

---

## 3. What the AI Track Actually Learned

We highlight five core engineering and forensic lessons learned this month:

### Finding 1: The Judge Agent Trades Coverage for Safety
Month 1 suffered from a dangerous failure mode: whenever conflicting detectors averaged near 0.40, the system classified media as `UNCERTAIN` and silently defaulted it to authentic (9 false-authentics out of 20 cases). Month 2's Guard 1 completely eliminated this risk (0 false-authentics). However, it did so by **abstaining on 65.0% of cases** (`INTEGRITY_UNKNOWN`). Operationally, a system that refuses to rule on two-thirds of contested media pushes heavy review burdens onto human SOC analysts.

### Finding 2: Decisive Precision is High (85.7%), but False-Synthetic Risk Remains
When the Judge Agent does render a firm verdict, its precision is high (85.7%). However, single-sample vulnerabilities persist: authentic video `067.mp4` triggered a false `SYNTHETIC (0.78)` verdict with a `P1_CRITICAL` alert. In forensic and legal contexts, a false synthetic accusation against authentic media is as damaging as a missed deepfake.

### Finding 3: Surveillance Alerting is Driven by Cryptographic Integrity, Not AI Anomaly Scores
In the live surveillance benchmark, every active tamper scenario was caught because the cryptographic hash chain broke or the PRNU baseline was mismatched. In every scenario, the AI content anomaly score remained in the borderline zone ($0.35 < \text{ai} < 0.65$). The AI detection branch did not independently catch any forged streams; it acted as a passive secondary signal.

### Finding 4: Cloud LLM Planning Latency Breaks Real-Time SLAs
While the LLM planner demonstrates intelligent context-aware pruning (diverging from static rules in 68.4% of cases and pruning unneeded detectors under tight budgets), live OpenRouter free-tier queries take between 21.8 s and 365.5 s (P95 > 200 s). This exceeds our ≤3.0s target by up to 120×. A deepfake verification pipeline cannot spend 3 minutes deciding which detector to call.

### Finding 5: Production Wiring Dropped Audio and Hardcoded Environmental Context
Unit tests and evaluation fixtures masked two production integration gaps:
1. `orchestrator/app/judge_bridge.py` dropped AASIST audio claims before invoking the judge because no audio debate adapter existed.
2. Operating conditions (`mean_luminance`, `face_detected`) were hardcoded to static constants, preventing the Forensic Precedence Matrix's low-light and occlusion rules from firing on real file uploads.

---

## 4. Biggest Open Reliability & Latency Concerns

The following 15 limitation profiles (documented in full in [docs/LIMITATIONS.md Section 8](file:///d:/Grad%20Projectt%20eccuuuuu/docs/LIMITATIONS.md#8-month-2-findings--limitations-profile-m2-l1-to-m2-l15)) represent our primary operational risks:

1. **[M2-L1] Score-Inversion Trap in Streaming rPPG:** Flat or motionless facial ROIs emit `score = 1.000` (100% synthetic), reintroducing Month 1's false-alarm flaw.
2. **[M2-L2] Buffer Warmup & Gap Purge Blind Spots:** Streaming rPPG produces no evidence for the first 6 seconds, and any face-tracking drop > 1s purges the buffer, causing repeated blind spots.
3. **[M2-L3] Unvalidated Streaming ROI Sampling:** `roi_mean_rgb` averages the full frame when no box is provided, sampling room lighting noise as cardiac pulses.
4. **[M2-L4] Uncalibrated SNR-to-Score Logistic Mapping:** Heuristic sigmoid parameters (`midpoint=1.0, slope=0.6`) produce uncalibrated probability scores.
5. **[M2-L5] Streaming rPPG Omitted from Live Pipeline:** `live_pipeline/` instantiates only MobileNetV3; the live surveillance AI path is completely monomodal.
6. **[M2-L6] Mathematical Degeneracy of Equal-Weighted Fusion:** With clean integrity, combined score cannot exceed 0.5; any AI anomaly score between 0.35 and 0.65 trivially defaults to `UNCERTAIN`.
7. **[M2-L7] Placeholder Evidentiary Defaults in Incident Alerts:** Missing alert context defaults to `192.168.10.50` and the SHA-256 hash of an empty string, corrupting ISO 27037 audit logs.
8. **[M2-L8] Anomaly Boundary Discard Across Sliding Windows:** Window anomalies are cleared every stride (8 frames) while window length is 16 frames; `prnu_pce` is passed but never thresholded.
9. **[M2-L9] Complete Audio Modality Suppression:** The Judge Agent bridge filters out AASIST; synthetic voice deepfakes are never adjudicated in final forensic reports.
10. **[M2-L10] Static Environmental Operating Conditions in Bridge:** `mean_luminance=None, face_detected=True` hardcoded in `judge_bridge.py`, disabling precedence discounting.
11. **[M2-L11] 65% Judge Abstention & Single-Sample False-Synthetic:** Excessive `INTEGRITY_UNKNOWN` escalations and sample `067.mp4` misclassified as `SYNTHETIC (0.78)`.
12. **[M2-L12] Fixture Provenance Poisoning (Random-Weight Checkpoints):** 15 of 20 Month 1 audit fixtures evaluated random network weights from the uninitialized video-classifier.
13. **[M2-L13] Benchmark Circularity & Missing Stream Fixtures:** 100% surveillance pass rate was achieved via scenario name string parsing; stream video fixtures are not committed in git.
14. **[M2-L14] Unresolved LLM Planning Latency SLA Breakdown:** Cloud LLM planning latency of 21.8s–365s prevents real-time interactive usage.
15. **[M2-L15] Disconnected Load Testing:** 32-feed load test measured socket network transport only; edge neural model inference was excluded from the test loop.

---

## 5. Open Questions for Month 3 (Orchestration, Debate & Security)

These strategic questions link directly to our proposed Month 3 priorities in [docs/month3_planning.md](file:///d:/Grad%20Projectt%20eccuuuuu/docs/month3_planning.md):

### Q1 (Debate Track & Cyber Track): What is the acceptable operational threshold for Judge Agent abstention?
*Context:* Guard 1 eliminates false-authentics by forcing `INTEGRITY_UNKNOWN` on 65% of contested cases. Does the SOC team prefer high abstention with zero false-authentics, or should Month 3 tune consensus thresholds to achieve >= 60% coverage, even if borderline ambiguity increases?  
*Mapped Candidate:* **C2 (Alignment & Specification Gaming Study)**.

### Q2 (AI Track & Dev Track): How do we hit the ≤3.0s planner latency SLA?
*Context:* Free cloud routing takes 21.8s–365s. Should the team fund dedicated paid API capacity (e.g., Groq Llama-3-70B with latency SLA), or should we execute the local quantization roadmap (Llama-3-8B INT4 via vLLM directly on the GPU host)?  
*Mapped Candidate:* **C1 (Evaluation Integrity) & C5 (Production Hardening)**.

### Q3 (AI Track): How quickly can we reconnect AASIST into the Judge Agent?
*Context:* Audio claims are currently discarded. Building an AASIST claim adapter in `debate/claim_wrapper.py` and expanding the Precedence Matrix with VAD pre-filtering is a necessary condition for true multimodal verification.  
*Mapped Candidate:* **C4 (Return to Audio Modality)**.

### Q4 (Cyber Track & AI Track): Should live surveillance require multi-modal rPPG in production?
*Context:* Streaming rPPG is unintegrated in `live_pipeline/`. Wiring it adds physiological anti-spoofing, but introduces buffer warmup delays (6s) and increased compute. Should surveillance remain spatial-only (MobileNetV3 INT8) or require fused rPPG?  
*Mapped Candidate:* **C5 (Production Pipeline Hardening)**.

### Q5 (Architecture Track): What tools should be exposed via the Model Context Protocol (MCP)?
*Context:* The `mcp/` container is an empty stub. Should the MCP server expose top-level arbitration (`judge_file`) and planning tools only, or allow external agents to call individual detector microservices directly?  
*Mapped Candidate:* **C3 (MCP Server Integration)**.

---

## 6. Bottom Line for the Team

Month 2 delivered working, verifiable infrastructure: the 3-round Judge Agent operates mathematically without crashes, the INT8 edge model processes live frames at 16% of the real-time latency budget, and zero false-authentics slipped through the arbitration layer.

However, **Month 2's benchmark numbers must be understood in their true context**:
- The Judge Agent's 0 false-authentics came through a **65% abstention rate**, not 85% decisive accuracy.
- The surveillance pipeline's 100% tamper detection validated **downstream fusion logic**, not raw PRNU extraction.
- The planner's 68.4% divergence was demonstrated on a **mock LLM**, while live cloud models exceed latency budgets by up to 120×.

Month 3 must not build further speculative layers on unvalidated assumptions. Our priority should be **ground-truth integrity**: unpoisoned benchmark fixtures, local low-latency planning, dynamic metadata binding, and reconnecting the audio modality into the debate protocol.
