# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AEGIS is a monorepo for a deepfake/synthetic-media detection system, built as a set of independently containerized microservices coordinated by a central orchestrator:

1. **`orchestrator/`** — rule-based planning agent (FastAPI). Decides which detectors to invoke for a given input (modality, has_audio), dispatches to them concurrently, aggregates their scores into a verdict, and logs everything to SQLite. Will eventually be replaced by an LLM-driven agent (see `debate/`), but the rule-based version is the current baseline all future work is measured against.
2. **`detectors/`** — one FastAPI microservice per model: `video-classifier` (EfficientNet-B0 on FF++), `rppg` (CHROM heartbeat-consistency), `aasist` (audio voice-spoofing), `syncnet` (audio-visual lip sync). `dire/` and `binoculars/` exist as unimplemented stub containers (image/text modalities) in `docker-compose.yml`.
3. **`debate/`**, **`engine/`** — planned Month 2 layers (multi-agent arbitration/explainability, hardware-aware quantization/export). Currently stub containers with no code.
4. **`security/`** — the ingestion gateway (`nginx` + `gateway_validator` FastAPI sidecar) that sits in front of the orchestrator, plus the Wazuh SIEM agent and Prometheus/Grafana telemetry config.
5. **`web/`** — Next.js frontend for uploading media and viewing detector results.
6. **`shared/`** — cross-service API contracts, threat model, and docs that are the source of truth for inter-service behavior (see below).
7. **`eval/`** — benchmarking scripts, dataset staging, and edge-case fixture generation.
8. **`capability_manifests/`** — per-detector JSON manifests (input constraints, performance, known failure modes) validated against `capability_manifests/Schema.py`.

Every microservice directory is self-contained: its own `Dockerfile`, `requirements.txt`, and `tests/`. **Never add a microservice-specific dependency (torch, fastapi, etc.) to the root `requirements.txt`** — that file is only for host-machine tooling shared across the team (wandb, jsonschema). Each service's `requirements.txt` must pin a minimum version (`package>=x.x.x`, never bare `package`).

## Source-of-truth docs (read before changing cross-service behavior)

- **`shared/json-api-contracts-schema/SCHEMA.md`** — the strict request/response JSON contract between orchestrator and detectors. The orchestrator rejects any detector response missing a required field (`job_id`, `confidence`, `raw_score`, `latency_ms`, `model_version`, `evidence`). Also defines the security constraints (auth header, payload size, extension/magic-byte allowlist, path-traversal confinement) — don't redefine these elsewhere.
- **`docs/LIMITATIONS.md`** — per-detector systematic failure modes discovered during benchmarking (e.g., rPPG on low-light/short-clip/occluded-face inputs, SyncNet on silent video). This directly informs `orchestrator/app/rules.py` eligibility logic and the eventual debate-layer confidence weighting — check it before changing detector dispatch or aggregation logic.
- **`docs/failure_notes.md`** — running log of individual misclassifications (complements LIMITATIONS.md's pattern-level view).
- **`shared/docs/model_scope.md`** — the 6 finalized detector models and their source datasets/checkpoints.
- **`shared/threat_model/THREAT_MODEL_full.md`** / **`_short.md`** — threat model for the security layer.
- **`security/gateway/README.md`** — how the two-layer gateway (nginx auth/rate-limit + `gateway_validator` deep inspection) enforces the SCHEMA.md security section.
- **`capability_manifests/*.json`** (validated by `capability_manifests/validate_manifests.py` against `Schema.py`) — machine-readable per-detector constraints (`min_duration_seconds`, `requires_audio`, `known_failure_modes`, etc.).

## Architecture flow

```
web (Next.js) → api_gateway (nginx, auth + rate-limit)
             → gateway_validator (magic-byte/allowlist/path-traversal check)
             → orchestrator (/orchestrate)
                 1. metadata.py: ffprobe → InputMetadata (modality, has_audio, duration, resolution)
                 2. rules.py: decide_detectors_to_call(metadata) → list of detector names
                 3. dispatch.py: call_all_detectors() — concurrent httpx calls, one CircuitBreaker per detector
                 4. aggregate.py: weighted-average confidence across detectors → (score, verdict)
                 5. db.py: log_decision() persists request/decisions/telemetry to SQLite (flight_recorder.db)
             → detector_{video-classifier,rppg,aasist,syncnet} (each: POST /detect, GET /health, /metrics)
```

Key orchestrator internals (`orchestrator/app/`):
- **`rules.py`** — the only place detector-selection logic lives; purely a function of `InputMetadata`. video/image → video-classifier; video → rppg; has_audio → aasist (+ syncnet if also video).
- **`circuit_breaker.py`** — per-detector `CircuitBreaker` (3 failures → OPEN, 5s recovery, latency-based tripping too). Failure thresholds are currently hardcoded (see TODO in file) and are meant to become telemetry-driven in Month 2.
- **`aggregate.py`** — weighted average of per-detector confidence (weights are heuristic placeholders, explicitly marked to be replaced by the debate layer). Thresholds: `>= 0.65` SYNTHETIC, `<= 0.35` AUTHENTIC, else UNCERTAIN. No usable results → `NO_RESULTS`.
- **`dispatch.py`** resolves each detector's URL via `DETECTOR_{NAME}_URL` env var, falling back to `http://detector_{name}:8000`.

Each detector service follows the same shape (see `detectors/aasist/app.py` as the reference implementation): FastAPI app with `lifespan` model loading, `GET /health`, `POST /detect` (validates `X-Internal-Token` against `INTERNAL_API_KEY`, accepts either an absolute file path or base64 payload), Prometheus metrics mounted at `/metrics`, and a `telemetry.py` decorator (`@track_inference`) wrapping inference calls.

## Running the stack

```bash
cp .env.example .env   # set INTERNAL_API_KEY
docker compose up -d   # spins up aegis_net: gateway, orchestrator, all detectors, prometheus/grafana
docker compose ps
docker compose down
```

Detector ports are also exposed directly on the host for local AI-team testing (bypasses the gateway — explicitly marked `[DEVSECOPS EXCEPTION]` in `docker-compose.yml`, must not ship this way to production): video-classifier `8001`, aasist `8002`, rppg `8003`, syncnet `8004`. Orchestrator: `8000`. Gateway: `8081`. Prometheus: `9090`, Grafana: `3001`.

## Tests

Each Python service has its own isolated test suite; there is no single repo-wide test command.

```bash
# A detector microservice (pattern repeats for aasist, rppg, syncnet, video-classifier)
cd detectors/aasist && pip install -r requirements.txt && pytest tests/ -v
pytest detectors/aasist/tests/test_api.py -v          # single file
pytest detectors/aasist/tests/test_api.py::test_name  # single test

# Orchestrator
cd orchestrator && pip install -r requirements.txt
python app/test_circuit_breaker.py   # standalone async script, not pytest — run directly

# Gateway validator (deep upload inspection)
cd security/gateway/validator && pip install -r requirements.txt && pytest tests/ -v

# Full-stack E2E (spins up docker compose, exercises orchestrator end-to-end)
python security/tests/test_orchestrator_e2e.py

# Gateway smoke test against a live stack (docker compose up -d first)
./security/gateway/test_gateway.sh     # Linux/Mac
./security/gateway/test_gateway.ps1    # Windows

# Web frontend
cd web && npm install
npm run lint
npm run build
npm run dev   # local dev server
```

CI (`.github/workflows/`) runs these per path-filtered PR: `ci-docker-check.yml` (docker compose config validation + full stack spin-up + `security/tests/test_orchestrator_e2e.py`), `ci-gateway.yml` (validator pytest suite, triggered on `security/gateway/**` changes), `ci-web.yml` (lint + build + docker build, only when `web/**` changes).

## Conventions specific to this repo

- Pydantic v2 is used throughout orchestrator/detector models — use `.model_dump()`, not `.dict()`.
- Detector `/detect` responses must satisfy the full required-field list in SCHEMA.md or the orchestrator returns a `status: "failed"` `DetectorResult` for that detector rather than raising.
- `confidence` is always normalized `0.0` (authentic) to `1.0` (synthetic) — this convention is load-bearing across aggregation, weights, and thresholds; don't invert it in a new detector.
- Direct pushes to `main` are blocked (per root README): changes go through a PR, must pass `validate-docker` CI, and need peer review.
- New/changed detector behavior that affects reliability should be reflected in the matching `capability_manifests/*.json` (schema in `capability_manifests/Schema.py`) and cross-referenced in `docs/LIMITATIONS.md` if it's a systematic failure mode, not a one-off bug (which goes in `docs/failure_notes.md` instead).
