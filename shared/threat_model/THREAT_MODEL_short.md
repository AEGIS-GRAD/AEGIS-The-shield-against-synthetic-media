# AEGIS — Threat Model (Month 2 Final)

**Status:** Living document — updated and finalized for Month 2 closure.  
**Scope:** Dual-Path Architecture (File-Based Offline Verification + Live Surveillance Streaming Ingestion).  
**Full Reference:** Comprehensive research-backed threat model (21 scenarios, CVE references, MITRE ATLAS/ATT&CK mappings) is maintained at [`shared/threat_model/THREAT_MODEL_full.md`](file:///g:/College/Graduation%20Project/AEGIS-The-shield-against-synthetic-media/shared/threat_model/THREAT_MODEL_full.md).  
**Penetration Testing Verification:** Validated by automated red-team test suite [`security/tests/run_prod_pentest.py`](file:///g:/College/Graduation%20Project/AEGIS-The-shield-against-synthetic-media/security/tests/run_prod_pentest.py) and documented in [`security/docs/month2_pentest_log.md`](file:///g:/College/Graduation%20Project/AEGIS-The-shield-against-synthetic-media/security/docs/month2_pentest_log.md).

---

## 1. What We're Protecting

- **Media & Stream Integrity:** Uploaded files and live RTSP/mTLS surveillance camera streams must not be silently intercepted, spliced, modified, or forged before or during detection.
- **Physical Sensor Provenance:** Streams must originate from verified physical camera hardware, authenticating unique sensor photo-response non-uniformity (PRNU) noise patterns.
- **Detector & Judge Outputs:** Confidence scores, debate transcripts, evidence justifications, and fused verdicts must remain tamper-evident and traceable.
- **Forensic Chain-of-Custody:** Security incidents and alert evidence must be stored in an immutable, append-only hash-chained ledger complying with ISO/IEC 27037 and FRE Rule 902.
- **Internal Service Communication:** Microservices (`orchestrator`, `engine`, `detectors`, `fusion`, `incident_response`, `evidence_vault`) must authenticate mutually under Zero Trust (NIST SP 800-207).

---

## 2. Who We're Defending Against

- **Deepfake Splicer:** Adversary intercepting live camera feeds to splice synthetic faces, altered frames, or synthetic audio segments in real-time.
- **Sensor Impersonator:** Attacker attempting to forge camera identity or replay pre-recorded authentic footage using rogue network devices.
- **API & Protocol Prober:** External or internal attacker sending malformed, oversized, or malicious requests to API endpoints (`/orchestrate`, `/detect`) or streaming sockets (port 8443).
- **Denial-of-Service (DoS) Adversary:** Attacker attempting to exhaust gateway CPU, memory, or network file descriptors via high-frequency frame floods (> 2,000 FPS), Slowloris idle socket holds, or connection pool monopolization.
- **Compromised Container:** An internal service container attempting to forge authenticity scores or inject unauthorized alerts without credentials.

---

## 3. Dual-Profile Architectural Defense Model

To balance security rigor with developer velocity, AEGIS implements a **Dual-Profile Architecture**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        AEGIS DUAL-PROFILE SYSTEM                       │
├───────────────────────────┬────────────────────────────────────────────┤
│   DEV MODE (Default)      │   PROD MODE (Strict Zero Trust)            │
│   AEGIS_SECURITY_PROFILE=dev  │   AEGIS_SECURITY_PROFILE=prod              │
├───────────────────────────┼────────────────────────────────────────────┤
│ • Zero dev friction       │ • Strict Zero Trust (NIST SP 800-207)      │
│ • Unauthenticated pass    │ • Mandatory X-API-Key (HTTP 403)           │
│ • Relaxed file types      │ • Strict media allowlist (HTTP 415)        │
│ • Permissive mTLS check   │ • Mutual TLS required (CERT_REQUIRED)      │
│ • Audit warnings logged   │ • Sockets severed on integrity compromise  │
│ • Teammates develop freely│ • Automated vaulting & SIEM alert dispatch │
└───────────────────────────┴────────────────────────────────────────────┘
```

---

## 4. Month 2 Implemented & Verified Security Controls

| Control ID | Threat Category | Implemented Mechanism | Verification Evidence | Status |
|:---|:---|:---|:---|:---:|
| **SR-01** | Rogue Device Spoofing | Mutual TLS (mTLS 1.3) with internal Root CA; rejects connections without valid client certs. | `PT-S01` in `run_prod_pentest.py` | `[MITIGATED]` |
| **SR-02** | Deepfake Splicing | Rolling SHA-256 frame hash chain; mathematical mismatch immediately halts ingestion and vaults incident. | `PT-S02` in `run_prod_pentest.py` | `[MITIGATED]` |
| **SR-03** | Temporal Replay Attacks | Monotonic sequence counters and $\Delta t$ timestamp window validation in `StreamValidator`. | `PT-S03` in `run_prod_pentest.py` | `[MITIGATED]` |
| **SR-04** | Physical Sensor Spoofing | Continuous 2D DWT PRNU wavelet extraction matching enrolled camera PCE fingerprint thresholds ($PCE \ge 50.0$). | `PT-S04` in `run_prod_pentest.py` | `[MITIGATED]` |
| **SR-05** | Frame-Flood DoS | Token-bucket rate limiter enforcing 60 FPS cap with burst absorption; sheds connections exceeding limits. | `PT-S05` in `run_prod_pentest.py` | `[MITIGATED]` |
| **SR-06** | Connection Pool DoS | Global concurrency cap (20 streams) and per-IP connection limit (5 streams/IP) in `StreamConnectionManager`. | `PT-S06` in `run_prod_pentest.py` | `[MITIGATED]` |
| **SR-07** | Slowloris Socket Hold | Anti-Slowloris idle timeout (10.0s prod, 2.0s test) automatically severing inactive streams. | `PT-S07` in `run_prod_pentest.py` | `[MITIGATED]` |
| **SR-08** | Oversized Payload DoS | Hard 10MB line buffer ceiling on socket reads and 100MB file upload ceiling on HTTP endpoints. | `PT-S08` / `main.py` | `[MITIGATED]` |
| **SR-09** | Unauthorized API Access | Dual-profile API key header validation (`X-API-Key`) against dynamic environment secrets in production. | `PT-F02`, `PT-F03` in `run_prod_pentest.py` | `[MITIGATED]` |
| **SR-10** | Executable Upload Exploitation | Boundary media extension filtering in prod mode rejecting `.exe`, `.sh`, `.bin` with HTTP 415. | `PT-F04` in `run_prod_pentest.py` | `[MITIGATED]` |
| **SR-11** | Directory Traversal | Filename perimeter sanitization using `os.path.basename()` preventing path escape. | `PT-F05` in `run_prod_pentest.py` | `[MITIGATED]` |
| **SR-12** | Evidence Tampering | ISO/IEC 27037 Content-Addressed Storage (CAS) and append-only hash-chained forensic incident vault. | `security/tests/test_evidence_vault.py` | `[MITIGATED]` |
| **SR-13** | Alert Loss & SIEM Outage | Dual-mode incident routing with deduplication, HMAC webhook signatures, and dead-letter NDJSON logging. | `security/tests/test_alert_routing.py` | `[MITIGATED]` |

---

## 5. Residual Risks & Month 3 Tracking

1. **LLM Orchestrator & Multi-Agent Debate Surface:** Maliciously crafted input media designed to induce hallucination or manipulate the LLM planner's detector selection. Scheduled for Month 3 adversarial robustness hardening.
2. **Distributed Inter-Service mTLS Mesh:** Extending mutual TLS from ingestion edge to internal fusion-to-alerting hops (Task 6).
