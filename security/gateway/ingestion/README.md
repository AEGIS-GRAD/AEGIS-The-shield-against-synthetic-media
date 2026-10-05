# AEGIS Live Ingestion Gateway (Tasks 1 & 3)

The Ingestion Gateway is the absolute front door for all real-time camera feeds entering the AEGIS ecosystem. It is an asynchronous, high-performance TCP server designed with a **Zero-Trust** philosophy.

## Architectural Overview

This service resolves Month 2 / Sprint 3 Cybersecurity Tasks 1 and 3 by strictly enforcing cryptographic boundaries *before* any video frame ever touches the AI analysis layer.

1.  **mTLS Device Authentication (Task 3)**: The server uses an `SSLContext` configured with `CERT_REQUIRED`. This mathematically proves the physical identity of the connecting camera. If an attacker tries to connect with a rogue device (like a laptop), the TLS handshake fails and the connection is dropped instantly at the transport layer.
2.  **Streaming Integrity Validation (Task 1)**: For every incoming frame, the Gateway enforces two real-time mathematical checks:
    *   **Timestamp & Sequence Check**: Defeats Replay Attacks by ensuring continuous, unbroken time deltas between packets.
    *   **Live Hash-Chaining**: Defeats Deepfake Splicing by recalculating the SHA-256 hash of the frame (combined with the previous frame's hash) on the fly.

If *any* frame fails validation, the gateway severs the connection immediately, protecting the downstream AI Orchestrator from adversarial input.

## Usage

Start the Gateway:
```bash
python security/gateway/ingestion/server.py
```

Run the Automated E2E Tests:
```bash
python security/tests/test_live_ingestion.py
```
