# 🛡️ AEGIS Cybersecurity & DevOps Subsystem

Welcome to the **SecDevOps Subsystem** of AEGIS (The Shield Against Synthetic Media).  
This directory contains the perimeter defense, cryptographic primitives, stream integrity validators, hardware forensics, and containerized upload inspection services that secure AEGIS against injection, replay, tampering, and denial-of-service attacks.

---

## 📖 Primary Documentation & Master Specification

The complete, definitive technical specification, mathematical formulations, and system directory map are documented in:

👉 **[`secdevops_architecture_master.md`](./docs/secdevops_architecture_master.md)**

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

To run the automated 8-vector penetration test suite against the live streaming gateway:

```bash
pytest security/tests/run_surveillance_pentest.py -v
```

---

## 📁 Subsystem Directory Map

| Directory | Subsystem | Responsibility |
| :--- | :--- | :--- |
| **[`docs/`](./docs/)** | Security Documentation | Master architecture manual, penetration test reports, incident response SOPs, PKI design, and flight recorder queries. |
| **[`gateway/`](./gateway/)** | Gateway & Ingestion | Asynchronous TCP streaming server (`ingestion/server.py`), reverse proxy template (`nginx.conf.template`), and deep packet upload validator microservice (`validator/`). |
| **[`stream_integrity/`](./stream_integrity/)** | Temporal Integrity | Stateful $O(W)$ bounded sliding-window validator (`stream_validator.py`) detecting gaps, replays, regressions, and jitter. |
| **[`forensics/`](./forensics/)** | Hardware Forensics | Physical camera identification via Photo-Response Non-Uniformity (`prnu.py`) using 2D DWT (`db4`), Wiener filtering, and continuous live stream monitoring (`LivePRNUValidator`). Enrolled sensor baselines stored in `forensics/baselines/`. |
| **[`transport/`](./transport/)** | PKI & Cryptography | Mutual TLS 1.3 certificates (`certs/`) signed by a custom Certificate Authority, and key generation automation (`generate_certs.py`). |
| **[`attacks/`](./attacks/)** | Red-Team Attack Simulation | Canonical adversary generator (`generate_attack_streams.py`) producing FFV1 tamper streams (PRNU mismatch, auth bypass, splicing, replay). |
| **[`fixtures/`](./fixtures/)** | Test Fixtures | Pre-synthesized video and manifest attack fixtures (`tampered_streams/`) for local regression and integration testing. |
| **[`telemetry/`](./telemetry/)** | Observability | Prometheus metrics scraping configurations (`prometheus.yml`) polling health and latency every 5s. |
| **[`tests/`](./tests/)** | Integration Test Suite | Automated end-to-end integration tests, multi-attack harness verifications, DoS load shedding simulations, and 8-vector penetration test runner. |

---

## 📄 Dedicated Security Documentation Catalog (`security/docs/`)

All security documentation is consolidated under **`security/docs/`**:

| Document | Category | Role & Purpose |
| :--- | :--- | :--- |
| **[`secdevops_architecture_master.md`](./docs/secdevops_architecture_master.md)** | Core Architecture | Complete system manual, mathematical proofs, and engineering specification. |
| **[`pen_test_surveillance_pipeline.md`](./docs/pen_test_surveillance_pipeline.md)** | Pen-Test Audit | NIST SP 800-115 dynamic penetration test report across 8 real-time exploit vectors. |
| **[`incident_response_workflow.md`](./docs/incident_response_workflow.md)** | SecOps SOP | NIST SP 800-61 Rev. 2 incident response lifecycle, Wazuh SIEM rules (`100201`–`100204`), and JSON alert contracts. |
| **[`device_authentication_design.md`](./docs/device_authentication_design.md)** | PKI Specification | Hardware root-of-trust, private CA issuance, and zero-trust mTLS 1.3 enrollment. |
| **[`pen_test_log.md`](./docs/pen_test_log.md)** | Historical Audit | Initial REST API penetration testing evidence (API key auth, payload size caps, path safety). |
| **[`flight_recorder_cookbook.sql`](./docs/flight_recorder_cookbook.sql)** | Forensic Queries | SQL recipes for querying the immutable SQLite flight recorder audit database. |

---

## 🔗 External Infrastructure & CI/CD Integrations

| External Path | Asset Type | Role & Ownership |
| :--- | :--- | :--- |
| **[`docker-compose.yml`](../docker-compose.yml)** | Infrastructure as Code | Multi-container isolation, `aegis_net` bridge network, cgroup RAM limits (1–4GB), `wazuh_agent`, and `api_gateway`. |
| **[`eval/scripts/generate_attack_streams.py`](../eval/scripts/generate_attack_streams.py)** | Legacy Proxy | Backward-compatible shim redirecting legacy callers to `security/attacks/generate_attack_streams.py`. |
| **[`.github/workflows/ci-gateway.yml`](../.github/workflows/ci-gateway.yml)** | CI/CD Pipeline | Automated GitHub Actions workflow testing the gateway validator on pull requests. |
| **[`.github/workflows/ci-docker-check.yml`](../.github/workflows/ci-docker-check.yml)** | CI/CD Pipeline | Automated GitHub Actions workflow testing Docker Compose spin-up and E2E orchestrator health. |

