# AEGIS LLM-Layer Prompt-Injection Defense & Red-Team Report

- **Deliverable:** Month 3 / Week 10 Task 5
- **Source Spec:** [`docs/security_review_orchestrator_debate_layer.md`](../../docs/security_review_orchestrator_debate_layer.md)
- **Implementation Modules:**
  - `debate/prompt_security.py`
  - `orchestrator/app/media_metadata.py`, `orchestrator/app/models.py`, `orchestrator/app/prompt_builder.py`, `orchestrator/app/planner.py`
  - `debate/claim_wrapper.py`, `debate/judge_prompt.py`, `debate/llm_client.py`, `debate/judge_agent.py`
- **Red-Team Suite:** [`security/tests/test_llm_prompt_defenses.py`](../tests/test_llm_prompt_defenses.py)

---

## 1. Mitigations Implemented

| Mitigation Control | Target Risk | Files Updated | Behavior Enforced |
| :--- | :--- | :--- | :--- |
| **Input Allowlisting & Sanitization** | EXIF / container / filename / claim injections, zero-width & bidi spoofing | `debate/prompt_security.py`, `orchestrator/app/media_metadata.py`, `debate/claim_wrapper.py` | Applies NFKC normalization, strips Unicode `Cc`/`Cf` controls and RLO overrides, drops non-allowlisted EXIF tag keys, neutralizes delimiter/role tokens (`SYSTEM:`, `<\|im_start\|>`, `[INST]`, `---`, `#`), and redacts matched coercion directives (`[REDACTED_DIRECTIVE]`). |
| **Strict Length Caps** | Context bloat, DoS & hidden tail-payload injection | `debate/prompt_security.py`, `debate/claim_wrapper.py` | Caps filenames (`<= 100` chars), EXIF tag values (`<= 100` chars, max `12` tags), raw detector claims (`<= 256` chars), wrapped forensic claims (`<= 512` chars), and diagnostic flags (`<= 64` chars, regex allowlisted). |
| **Instruction / Evidence Separation** | Indirect prompt injection across section boundaries | `orchestrator/app/prompt_builder.py`, `orchestrator/app/planner.py`, `debate/judge_prompt.py`, `debate/llm_client.py` | Splits trusted `role: "system"` policy from `role: "user"` evidence messages and encloses untrusted evidence in per-invocation `<UNTRUSTED_EVIDENCE_DATA boundary="<nonce>">` blocks (pre-escaping internal closing tags). |
| **Canary Protection** | System-prompt extraction / echo attacks | `debate/prompt_security.py`, `orchestrator/app/planner.py`, `debate/llm_client.py` | Injects an unpredictable `AEGIS-CANARY-<hex>` token into the system prompt and immediately drops any model output that leaks the canary prefix or token. |
| **Strict Structured-Output & Narrative Validation** | Malformed schemas, detector hallucination, & coerced `'authentic'` narratives (Security Review §4 Concern 2) | `orchestrator/app/planner.py`, `debate/llm_client.py`, `debate/judge_agent.py` | Enforces exact key allowlists (zero extra properties), rejects booleans disguised as latencies and over-budget estimates, rejects Judge narratives contradicting locked `SYNTHETIC` / `INTEGRITY_UNKNOWN` rulings or omitting active detectors, and falls back to `JudgeArbitrator`. |
| **SIEM Anomaly Tracking** | Repeated adversarial injection / fallback abuse (Security Review §4 Concern 4) | `debate/prompt_security.py` (`SECURITY_ANOMALIES`) | Emits structured `P2_ELEVATED` security events on input injections, canary leaks, planner schema tampering, and verdict narrative contradictions. |

---

## 2. Red-Team Test Suite Results

- **Command:** `pytest security/tests/test_llm_prompt_defenses.py -v`
- **Result:** **46 / 46 passed** (covering 39 adversarial payloads + end-to-end mocked compromised LLM verification + 7 pipeline/benign canary checks):
  - **10 EXIF / Container Injection Payloads:** Neutralized & truncated `<= 100` chars (**10/10 passed**).
  - **10 Malicious Upload Filenames:** Path traversal, CRLF/header breaks, ChatML/XML tags, underscore-smuggled directives, fullwidth homoglyphs, bidi RLO, and 500-char strings neutralized `<= 100` chars (**10/10 passed**).
  - **10 Detector Claim & Text Payloads:** `rppg`/`syncnet` claim hijacks, `</UNTRUSTED_EVIDENCE_DATA>` boundary escapes, zero-width & homoglyph smuggling, 15 KB bloat DoS, and canary probes sanitized & capped `<= 512` chars (**10/10 passed**).
  - **Flag Injection & Boundary Isolation:** Injected strings in `flags` stripped cleanly; planner and judge prompts isolate all evidence strictly within unique nonce tags (**3/3 passed**).
  - **Compromised LLM / Semantic Subversion & Output Validation:** Simulated compromised LLM tricked into declaring `"unaltered authentic"` under locked `SYNTHETIC` verdict was intercepted and replaced with deterministic `SYNTHETIC` justification; extra JSON keys, bool latency, over-budget plans, hallucinated detectors, and canary leaks all rejected (**11/11 passed**).
  - **Benign Control Canary Tests:** Normal media filenames, legitimate camera EXIF (`Sony`, `Alpha 7S III`), and valid synthetic narratives passed with zero false positives (**2/2 passed**).

---

## 3. Residual Risk Assessment

1. **Subtle Paraphrased Narrative Drift:** The semantic consistency guard enforces explicit contradiction phrases and synthetic-affirming vocabulary for `SYNTHETIC`/`INTEGRITY_UNKNOWN` verdicts. Highly subtle, poetic, or euphemistic hedging by an LLM that avoids standard contradiction keywords remains a low residual risk, though mathematically locked verdicts (`calibrated_score`, `final_verdict`, `JudgeGuard` G1/G2) can never be altered by the LLM.
2. **External API Volumetric Availability Risk:** Under sustained DDoS floods targeting OpenRouter or external LLM endpoints, requests fail safely into the deterministic baseline planner (`rules.py`) and `JudgeArbitrator` without crashing or misclassifying media, incurring temporary degradation to deterministic justifications until LLM bridge capacity recovers.
3. **Novel Detector Text Evasion:** Newly integrated AI Week 1 text/image detectors (`detector_image`, `detector_text`) should inherit `prompt_security.sanitize_claim_text` and `sanitize_flags` automatically as their debate claim adapters are registered in `debate/claim_wrapper.py`.

