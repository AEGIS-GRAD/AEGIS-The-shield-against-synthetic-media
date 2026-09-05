# AEGIS — Threat Model (Week 1 Draft)

**Status:** Living document — this is a short, initial draft to inform this
week's API design and later hardening work (Week 4). It will be extended as
the architecture matures. A fuller, research-backed threat analysis (21
scenarios, CVE references, MITRE ATLAS mappings) already exists and is kept
at `/docs/threat_model_full.md` for later use in the formal Chapter 1
deliverable.

## What we're protecting

- **Media integrity** — uploaded files and live camera streams must not be
  silently tampered with before or during detection.
- **Detector outputs** — confidence scores, evidence, and verdicts must be
  trustworthy and traceable to who/what produced them.
- **User-uploaded content** — files coming into the system are untrusted by
  default until proven otherwise.
- **Internal service communication** — the orchestrator, engine, detectors,
  debate, eval, and mcp services must trust each other only through an
  authenticated channel, not by default network access.

## Who we're defending against

- **Someone trying to fool a detector** — feeding in adversarial or
  manipulated media crafted to be misclassified as authentic.
- **Someone trying to tamper with a report or evidence** — altering a
  verdict, score, or stored evidence after the fact.
- **Someone probing the API** — an external or internal actor sending
  malformed, oversized, or malicious requests to any service endpoint.
- **A compromised internal service** — a container on our own network
  (e.g. a detector) sending forged results to another service.

## Immediate security requirements this implies

1. **Input validation on all uploads** — reject malformed or unexpected
   input before it reaches any detection logic.
2. **No arbitrary file execution** — media-parsing services must never
   execute, interpret, or de-serialize untrusted file content as code.
   File types are allowed by explicit allowlist, not blocked by exception.
3. **Authenticated API access, including internally** — every service
   (`orchestrator`, `engine`, `detectors`, `debate`, `eval`, `mcp`) requires
   the shared `INTERNAL_API_KEY` on every request, even service-to-service
   calls on our own network. See `docker-compose.yml`.
4. **Payload limits** — every ingestion endpoint enforces a maximum file
   size to reduce denial-of-service risk from oversized uploads.

## Next steps

This document will grow to cover camera-feed integrity, evidence
chain-of-custody, and adversarial robustness in detail as those pieces of
the architecture are built.
