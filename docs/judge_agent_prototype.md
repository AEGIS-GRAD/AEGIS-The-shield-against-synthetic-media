# AEGIS Judge Agent Prototype — Architecture, Guardrails & Month 1 Evaluation

**Version:** 1.0.0  
**Status:** Approved & Implemented Deliverable (Month 2 Core Deliverable — Task 3)  
**Author:** Mohand Mohsen — AI Track  
**Supervisors:** Dr. Amr Megahed, Eng. Ramez Yousri  
**Target Modules:** `debate/judge_agent.py`, `debate/schemas.py`, `debate/judge_prompt.py`, `debate/llm_client.py`  
**Evaluation Artifacts:** `eval/reports/judge_prototype_eval.md`, `eval/reports/judge_prototype_eval_raw.csv`  

---

## 1. Executive Summary & Problem Addressed

Month 1 of AEGIS deployed three video detection microservices:
1. `video-classifier` (EfficientNet-B0 on FaceForensics++ C23)
2. `rppg` (CHROM pulse extraction)
3. `syncnet` (Lip-phoneme audiovisual desynchronization)

In Month 1, inter-service aggregation relied on an unvalidated heuristic weighted average (`orchestrator/app/aggregate.py`):
$$\text{Score} = \frac{1.5 \cdot c_{\text{classifier}} + 0.8 \cdot c_{\text{rppg}} + 1.2 \cdot c_{\text{syncnet}}}{1.5 + 0.8 + 1.2}$$

This simple weighted average suffered from two catastrophic vulnerabilities in security and forensic contexts:
1. **The Score Inversion Trap**: When environmental degradation occurred (e.g. low light $< 40/255$ or short clip $< 2.0$s), rPPG suffered chromatic collapse, asserting false high synthetic confidence on authentic footage.
2. **The Unresolved Conflict Trap**: When detectors directly contradicted each other (e.g. Classifier asserting 0.05 Authentic while rPPG asserted 0.90 Synthetic), mathematical averaging smoothed the conflict into ~0.35, falsely certifying the file as **`AUTHENTIC`** without ever investigating *why* the physical signals disagreed.

The **Judge Agent Prototype** eliminates these vulnerabilities by replacing static arithmetic with an auditable **3-round Structured Debate Protocol** governed by the **Forensic Precedence Matrix** and **Digital Forensics Guardrails (G1 & G2)**.

---

## 2. The 3-Round Structured Debate Protocol

```mermaid
flowchart TD
    Raw[Raw Detector Responses] --> R1[Round 1: Claim Submissions<br/>claim_wrapper adapts to ForensicClaims]
    R1 --> R2[Round 2: Cross-Examination<br/>Manifest constraints, LIMITATIONS.md, Gaps]
    R2 --> R3[Round 3: Adjudication<br/>Forensic Precedence Matrix Rules 1-4]
    R3 --> Guards{Judge Guards G1 & G2<br/>Unresolved conflict? Single witness?}
    Guards -- Conflict Unresolved --> Downgrade[Downgrade to INTEGRITY_UNKNOWN P2]
    Guards -- Clean Corroboration --> Ruling[Confirm Verdict Class & Score]
    Downgrade --> Hash[Compute SHA-256 Transcript Hash]
    Ruling --> Hash
    Hash --> Report[Court-Admissible JudgeReport]
```

### Round 1: Claim Submissions
- Raw `/detect` JSON payloads are parsed via `debate/claim_wrapper.py`.
- Formatted into typed `ForensicClaim` objects featuring explicit polarity, calibrated effective confidence, diagnostic flags, and human-readable assertions.

### Round 2: Cross-Examination & Context Injection
- Ingested claims are cross-examined against:
  1. `capability_manifests/*.json` input constraints (minimum duration, audio presence).
  2. `docs/LIMITATIONS.md` systematic failure boundaries (low luminance chromatic collapse, atypical heart rates, facial occlusion).
  3. Borderline scores in $[0.35, 0.65]$: Isolated as non-voting coverage gaps to prevent noise injection.
- Emits structured `CrossExaminationFinding` objects logged in the audit trail.

### Round 3: Adjudication & Forensic Precedence Matrix
Claims are evaluated by the `JudgeArbitrator` under the 4 Forensic Precedence Rules:
* **Rule 1 (Low-Light Inversion Trap)**: Discounts rPPG synthetic claims when `mean_luminance < 40/255` or `low_light_attenuation` flag is present.
* **Rule 2 (Short Duration Minimum)**: Discounts rPPG pulse extraction when `duration_seconds < 2.0s`.
* **Rule 3 (Face-Swap Inpainting)**: Spatial boundary anomalies override intact donor physiological cardiac pulse &rarr; **`SYNTHETIC` (P1 Critical)**.
* **Rule 4 (Audio Dubbing Desync)**: Lip-desync on authentic facial frames is ruled as foreign translation/dubbing &rarr; **`AUTHENTIC` (P4 Informational)**.

---

## 3. Digital Forensics Guardrails (Policy Enforcement)

To satisfy Dr. Amr Megahed's strict non-negotiable requirement (*"An integrity failure or unresolved contradiction must never result in authentic"*), the Judge Agent applies two authoritative guardrails:

### Guard 1 (G1): Unresolved Polarity Inversion Anti-Default
* **Condition**: Active detectors exhibit direct polarity inversion ($c_i \ge 0.65 \land c_j \le 0.35$), but no Forensic Precedence Rule (Rules 1–4) discounted the contradictory signal.
* **Action**: **Downgrades verdict from `AUTHENTIC` to `INTEGRITY_UNKNOWN` (P2 Elevated Alert)**.
* **Rationale**: Courts cannot accept media as authentic when forensic instruments testify to opposing physical realities without affirmative proof of instrument failure.

### Guard 2 (G2): Minimum Corroboration for Authentic
* **Condition**: Only a single detector was active ($N=1$), while all other video detectors experienced coverage gaps or dropouts.
* **Action**: **Downgrades verdict from `AUTHENTIC` to `INTEGRITY_UNKNOWN` (P2 Elevated Alert)**.
* **Rationale**: Cross-modal corroboration across independent evidentiary domains is mandatory before granting legal certification of authenticity.

---

## 4. Dual-Mode Architecture & Tamper Evidence

1. **Deterministic Mode (`expert_deterministic_judge`)**:
   - Zero external network dependencies.
   - Sub-millisecond latency ({avg_latency_ms} ms).
   - Generates full chain-of-evidence justification conforming to ISO/IEC 27037 standards.
2. **LLM Explainability Mode (`llm_agentic_judge`)**:
   - Invokes OpenRouter LLM (`nvidia/nemotron-3.5-lightning:free` or fallback).
   - Locks verdict and calibrated score as immutable facts; LLM synthesizes rich legal narrative.
   - Automatic fallback to deterministic justification on API timeout, schema invalidity, or offline execution.
3. **Cryptographic Chain of Custody**:
   - `evidence_manifest_hash`: SHA-256 over all ingested claims.
   - `debate_transcript_hash`: SHA-256 over entire 3-round debate transcript and applied rulings.

---

## 5. Verification Results (Task Card Compliance)

* **Test Suite**: `debate/tests/test_judge_agent.py` and `debate/tests/test_judge_month1_cases.py` (86/86 passed, 100%).
* **Evaluated Cases**: 20 cases from Month 1 file-based benchmark (including 11 hard disagreements, exceeding the $\ge 5$ requirement).
* **False Authentic Prevention**: 100% of contradictory fakes prevented from defaulting to authentic.
