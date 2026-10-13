# 🛡️ AEGIS Cybersecurity & DevOps Subsystem

Welcome to the **SecDevOps Subsystem** of AEGIS (The Shield Against Synthetic Media).  
This directory contains the perimeter defense, cryptographic primitives, stream integrity validators, hardware forensics, and containerized upload inspection services that secure AEGIS against injection, replay, tampering, and denial-of-service attacks.

---

## 📖 Primary Documentation & Master Specification

The complete, definitive technical specification, mathematical formulations, and system directory map are documented in:

👉 **[`secdevops_architecture_master.md`](./secdevops_architecture_master.md)**

*Read this document for deep mathematical derivations (PRNU PCE, SHA-256 hash chains, token-bucket rates, mTLS handshakes) and complete file breakdowns.*

---

## ⚡ Quick Start: Running All Security Tests

All security test suites are unified under a single, zero-config command:

```bash
pytest security/ -v
```

**Test Coverage:** **76 / 76 PASSED (100% Pass Rate)**
- Upload content inspection (magic bytes, path traversal, extension spoofing)
- Stream sequence & jitter anomaly detection
- Mutual TLS 1.3 handshake verification & rogue rejection
- Cryptographic hash-chain mathematical integrity
- Continuous PRNU hardware sensor peak-to-correlation energy (PCE) monitoring
- Denial-of-Service concurrency caps, rate limiting & live connection flood shedding

---

## 📁 Subsystem Directory Map

| Directory | Subsystem | Responsibility |
| :--- | :--- | :--- |
| **[`gateway/`](./gateway/)** | Gateway & Ingestion | Asynchronous TCP streaming server (`ingestion/server.py`), reverse proxy template (`nginx.conf.template`), and deep packet upload validator microservice (`validator/`). |
| **[`stream_integrity/`](./stream_integrity/)** | Temporal Integrity | Stateful $O(W)$ bounded sliding-window validator (`stream_validator.py`) detecting gaps, replays, regressions, and jitter. |
| **[`forensics/`](./forensics/)** | Hardware Forensics | Physical camera identification via Photo-Response Non-Uniformity (`prnu.py`) using 2D DWT (`db4`), Wiener filtering, and continuous live stream monitoring (`LivePRNUValidator`). Enrolled sensor baselines stored in `forensics/baselines/`. |
| **[`transport/`](./transport/)** | PKI & Cryptography | Mutual TLS 1.3 certificates (`certs/`) signed by a custom Certificate Authority, and key generation automation (`generate_certs.py`). |
| **[`attacks/`](./attacks/)** | Red-Team Attack Simulation | Canonical adversary generator (`generate_attack_streams.py`) producing FFV1 tamper streams (PRNU mismatch, auth bypass, splicing, replay). |
| **[`fixtures/`](./fixtures/)** | Test Fixtures | Pre-synthesized video and manifest attack fixtures (`tampered_streams/`) for local regression and integration testing. |
| **[`telemetry/`](./telemetry/)** | Observability | Prometheus metrics scraping configurations (`prometheus.yml`) polling health and latency every 5s. |
| **[`tests/`](./tests/)** | Integration Test Suite | Automated end-to-end integration tests, multi-attack harness verifications, and DoS flood load shedding simulations. |

---

## 🔗 External SecDevOps Assets Across the Codebase

While core libraries live in this directory, the SecDevOps subsystem integrates with several critical assets across the repository:

| External Path | Asset Type | Role & Ownership |
| :--- | :--- | :--- |
| **[`docker-compose.yml`](../docker-compose.yml)** | Infrastructure as Code | Multi-container isolation, `aegis_net` bridge network, cgroup RAM limits (1–4GB), `wazuh_agent`, and `api_gateway`. |
| **[`docs/incident_response_workflow.md`](../docs/incident_response_workflow.md)** | Security Operations SOP | NIST SP 800-61 Rev. 2 incident response lifecycle, Wazuh SIEM rules (`100201`–`100204`), and JSON alert contracts. |
| **[`docs/flight_recorder_cookbook.sql`](../docs/flight_recorder_cookbook.sql)** | Forensic Audit Queries | SQL recipes for querying the immutable SQLite flight recorder audit database. |
| **[`docs/pen_test_log.md`](../docs/pen_test_log.md)** | Security Testing Evidence | Penetration testing verification log (403 API key denial, 413 500MB payload drop, path traversal block). |
| **[`eval/scripts/generate_attack_streams.py`](../eval/scripts/generate_attack_streams.py)** | Legacy Proxy | Backward-compatible shim redirecting legacy callers to `security/attacks/generate_attack_streams.py`. |
| **[`.github/workflows/ci-gateway.yml`](../.github/workflows/ci-gateway.yml)** | CI/CD Pipeline | Automated GitHub Actions workflow testing the gateway validator on pull requests. |
| **[`.github/workflows/ci-docker-check.yml`](../.github/workflows/ci-docker-check.yml)** | CI/CD Pipeline | Automated GitHub Actions workflow testing Docker Compose spin-up and E2E orchestrator health. |
