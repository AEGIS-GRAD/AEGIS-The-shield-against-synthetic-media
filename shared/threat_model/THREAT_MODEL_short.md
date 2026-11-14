# AEGIS — Threat Model (Executive Summary)

> **Notice:** This document is an executive summary of the canonical threat model maintained in [THREAT_MODEL_full.md](THREAT_MODEL_full.md).

**Status:** Living document — updated and synchronized for Month 3 Multi-Modal & Observability Expansion.  
**Scope:** Dual-Path Architecture (File-Based Offline Verification + Live Surveillance Streaming Ingestion + Image/Text/Model/MCP Extensions).  
**Full Reference:** Comprehensive research-backed threat model (27 STRIDE scenarios, CVE references, MITRE ATLAS/ATT&CK mappings, Mitigation Statuses) is maintained at [`shared/threat_model/THREAT_MODEL_full.md`](THREAT_MODEL_full.md).  
**Penetration Testing Verification:** Validated by automated red-team test suite [`security/tests/run_prod_pentest.py`](../../security/tests/run_prod_pentest.py).

---

## 1. What We're Protecting

- **Media & Stream Integrity:** Uploaded files (video, audio, image, text) and live RTSP/mTLS surveillance camera streams must not be silently intercepted, spliced, modified, or forged before or during detection.
- **Physical Sensor Provenance:** Streams must originate from verified physical camera hardware, authenticating unique sensor photo-response non-uniformity (PRNU) noise patterns ($PCE \ge 50.0$).
- **Multi-Modal Detectors:** Video (CNN artifacts), Audio (AASIST raw waveform), Physiological (rPPG pulse), Cross-Modal (SyncNet lip-sync), Image (MIRROR DINOv3 + FFT frequency grid), and Text (DeskLib fine-tuned + Binoculars cross-perplexity).
- **AI Supply Chain & Model Checkpoints:** Pretrained neural network weights (`.pth`, `.pt`, `safetensors`) and LoRA adapters must be cryptographically verified against hash manifests before deserialization to prevent pickle RCE.
- **Detector & Judge Outputs:** Confidence scores, multi-agent debate transcripts, evidence justifications, and fused verdicts must remain tamper-evident and traceable.
- **Forensic Chain-of-Custody:** Security incidents and alert evidence must be stored in an immutable, append-only hash-chained ledger complying with ISO/IEC 27037 and FRE Rule 902.
- **Internal Service Communication & MCP Tools:** Microservices (`orchestrator`, `engine`, `detectors`, `fusion`, `incident_response`, `evidence_vault`, `mcp`) must authenticate mutually under Zero Trust (NIST SP 800-207).

---

## 2. Who We're Defending Against

- **Deepfake Splicer:** Adversary intercepting live camera feeds to splice synthetic faces, altered frames, or synthetic audio segments in real-time.
- **Sensor Impersonator:** Attacker attempting to forge camera identity or replay pre-recorded authentic footage using rogue network devices.
- **Adversarial Media Crafter:** Attacker generating gradient-based perturbations, frequency-domain grid masks, or Unicode homoglyph/paraphrase text variations to fool AI classifiers.
- **Prompt Injection Adversary:** Attacker embedding hostile system prompt instructions inside analyzed text or image metadata to jailbreak LLM planners or Judge debate agents.
- **Supply-Chain / Checkpoint Poisoner:** Malicious entity attempting to supply backdoored weights or trojaned model checkpoints containing pickle execution payloads.
- **MCP Tool Exploiter:** Adversary crafting malicious tool parameters to achieve unauthorized file access (SSRF/path traversal) or poisoning tool outputs.
- **Denial-of-Service (DoS) Adversary:** Attacker attempting to exhaust gateway CPU, memory, or network file descriptors via high-frequency frame floods (> 2,000 FPS), Slowloris idle socket holds, or connection pool monopolization.

---

## 3. Dual-Profile Architectural Defense Model

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

## 4. Architectural Security Controls & Mitigation Status Summary

| Control ID | Threat Category | STRIDE | Implemented Mechanism | Mitigation Status |
|:---|:---|:---:|:---|:---:|
| **SR-01** | Rogue Device Spoofing | Spoofing | Mutual TLS (mTLS 1.3) with internal Root CA; rejects connections without valid client certs. | **Solved** |
| **SR-02** | Deepfake Splicing | Tampering | Rolling SHA-256 frame hash chain; mathematical mismatch immediately halts ingestion and vaults incident. | **Solved** |
| **SR-03** | Temporal Replay Attacks | Tampering | Monotonic sequence counters and $\Delta t$ timestamp window validation in `StreamValidator`. | **Solved** |
| **SR-04** | Physical Sensor Spoofing | Spoofing | Continuous 2D DWT PRNU wavelet extraction matching enrolled camera PCE fingerprint thresholds ($PCE \ge 50.0$). | **Solved** |
| **SR-05** | Frame-Flood DoS | DoS | Token-bucket rate limiter enforcing 60 FPS cap with burst absorption; sheds connections exceeding limits. | **Solved** |
| **SR-06** | Connection Pool DoS | DoS | Global concurrency cap (20 streams) and per-IP connection limit (5 streams/IP) in `StreamConnectionManager`. | **Solved** |
| **SR-07** | Slowloris Socket Hold | DoS | Anti-Slowloris idle timeout (10.0s prod, 2.0s test) automatically severing inactive streams. | **Solved** |
| **SR-08** | Oversized Payload DoS | DoS | Hard 10MB line buffer ceiling on socket reads and 100MB file upload ceiling on HTTP endpoints. | **Solved** |
| **SR-09** | Unauthorized API Access | Elevation | Dual-profile API key header validation (`X-API-Key`) against dynamic environment secrets in production. | **Solved** |
| **SR-10** | Executable Upload Exploitation | Elevation | Boundary media extension filtering in prod mode rejecting `.exe`, `.sh`, `.bin` with HTTP 415. | **Solved** |
| **SR-11** | Directory Traversal | Tampering | Filename perimeter sanitization using `os.path.basename()` preventing path escape. | **Solved** |
| **SR-12** | Evidence Tampering | Tampering | ISO/IEC 27037 Content-Addressed Storage (CAS) and append-only hash-chained forensic incident vault. | **Solved** |
| **SR-13** | Alert Loss & SIEM Outage | Repudiation | Dual-mode incident routing with deduplication, HMAC webhook signatures, and dead-letter NDJSON logging. | **Solved** |
| **SR-14** | SIEM / Wazuh Alert Injection | Tampering | Pydantic JSON contract validation preventing NDJSON line-injection or malformed field escaping. | **Solved** |
| **SR-15** | Internal Service Impersonation | Spoofing | `INTERNAL_API_KEY` header verification across all microservice boundaries + strict mTLS service mesh. | **Solved** |
| **SR-16** | Untrusted Media Parsing RCE | Tampering | Deep magic-byte verification in `gateway_validator` restricting parsing to validated formats. | **Solved** |
| **SR-17** | Text & Image Evasion | Spoofing | Unicode NFKC normalization + zero-width strip; FFT/DCT frequency grid anomaly detection in MIRROR. | **Solved / Partial** |
| **SR-18** | Poisoned / Malicious Weights | Tampering | SHA-256 weight hash pinning in manifests + `weights_only=True` PyTorch deserialization (safetensors). | **Solved** |
| **SR-19** | MCP Tool Exploitation | Elevation | Strict Pydantic parameter schemas, unprivileged container isolation, read-only mounts (`:ro`). | **Partial** |

---

## 5. Residual Risks & Ongoing Tracking

1. **Open-Domain Adversarial Perturbations (AML.T0015):** While multi-modal corroboration (audio + video + rPPG + text) prevents single-model evasion, white-box adaptive perturbations remain an active research challenge tracked as Partial/Residual.
2. **C2PA Root Private Key Compromise:** Addressed via standard PKI key management practices; production deployment requires Hardware Security Modules (HSM) and automated certificate revocation (CRL/OCSP).
3. **Edge Quantization Robustness Transferability:** Quantized INT8/FP16 models on edge devices (NVIDIA Jetson) will undergo Quantization-Aware Training (QAT) robustness benchmarks during Month 3 edge deployment.
