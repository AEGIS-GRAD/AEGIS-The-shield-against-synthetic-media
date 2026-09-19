# AEGIS Orchestrator v2 — Design Proposal (Month 2)

**Status:** Draft for team review before Month 1 closes
**Component:** `orchestrator/` (planning agent)
**Supersedes:** Rule-based baseline orchestrator (Month 1)
**Related docs:** `shared/docs/model_scope.md`, `docs/failure_notes.md`, `shared/json-api-contracts-schema/`

> Items marked **[confirm]** describe details I could not verify from the code and should be checked by the person who built that part before review.

---

## 1. Purpose

The orchestrator decides **which detectors to invoke** for a given input, based on:

- **Modality** of the input (video, audio, image, text, or a mix)
- **Risk profile** requested by the caller (how costly a missed fake is)
- **Compute budget** (latency ceiling, GPU/CPU availability)

Month 1 delivered a rule-based baseline. This document proposes how the **LLM-driven planner** in Month 2 will differ from it, what each detector must expose so a planner can reason about it, what the planning prompt should look like, and what counts as a minimal first success.

## 2. What the rule-based baseline does today

| Aspect | Current behaviour |
|---|---|
| Framework | FastAPI service, served by uvicorn on port 8000, `/health` used by the compose healthcheck |
| Input analysis | `metadata.py` calls `ffprobe` (from ffmpeg) to detect modality, presence of audio, and resolution |
| Selection | Hard-coded rules map modality (+ risk / budget) → a fixed list of detectors |
| Calling detectors | HTTP calls (`httpx`) to detector microservices on the `aegis_net` network |
| Audit | Decisions written to a SQLite decision log |

### Where rules stop scaling

1. **Rules encode assumptions about detectors, not facts from detectors.** If the rPPG detector needs a stable face for ≥ N seconds, that knowledge lives in `if` statements in the orchestrator instead of with the detector.
2. **Combinatorial growth.** Six detectors × modality × audio/no-audio × risk × budget × input quality produces a rule table that is hard to read and easy to get wrong.
3. **No reasoning about trade-offs.** A rule cannot say "the budget is tight, so run the cheap frame-level detector first and escalate only if the score is ambiguous."
4. **Edge cases are handled after the fact.** The Task 4 cases (silent video, clip under 2 s, partially occluded face, poorly lit clip) show that eligibility depends on input *quality*, not just modality.
5. **Adding a detector means editing orchestrator code.** It should mean registering a manifest.

### Lessons from Month 1 to carry forward **[confirm and extend]**

- Eligibility (can this detector run on this input at all?) is a different question from priority (should it run given risk and budget?). Keep them separate.
- Detectors must be able to say "insufficient signal" instead of returning a confident-looking score.
- Every decision needs a recorded reason, otherwise debugging the decision log is guesswork.

## 3. Proposed architecture

The LLM does **planning**, not **enforcement**. Hard constraints stay in deterministic code so a bad model output can never trigger an impossible or unsafe call.

```
 input + request (risk, budget)
        │
        ▼
 1. Metadata extraction        (ffprobe, existing metadata.py; adds duration, face/audio checks)
        │
        ▼
 2. Eligibility filter         (deterministic; uses capability manifests)
        │   eligible detectors + reasons for excluded ones
        ▼
 3. LLM planner                (chooses from ELIGIBLE detectors only; returns structured plan)
        │
        ▼
 4. Plan validator             (schema check, budget check, eligibility re-check)
        │   invalid / timeout / model error ──► fallback to rule-based baseline
        ▼
 5. Executor                   (parallel / sequential calls per plan, timeouts)
        │
        ▼
 6. Decision log               (input summary, manifest versions, plan, rationale, outcome)
```

Key differences from the baseline:

| | Rule-based (Month 1) | LLM planner (Month 2) |
|---|---|---|
| Source of detector knowledge | Hard-coded in orchestrator | Capability manifest from each detector |
| Eligibility | Modality only | Modality + duration + resolution + audio + face + quality signals |
| Selection logic | Fixed mapping | Reasoning over eligible set, risk, and budget |
| Ordering | Fixed | Can propose staged execution (cheap first, escalate if ambiguous) |
| Explanation | Rule name | Natural-language rationale stored with the plan |
| Failure mode | Wrong rule | Invalid or hallucinated plan, caught by validator, then fallback |
| Extensibility | Code change | Register a new manifest |

The rule-based orchestrator is **kept** as the fallback path and as the reference for evaluating the planner.

## 4. Capability manifest

Each detector microservice exposes `GET /capabilities` (proposed), returning a versioned manifest. The orchestrator caches manifests and refreshes on startup and when `/health` reports a new version.

### 4.1 Required fields

| Field | Type | Purpose |
|---|---|---|
| `id` | string | Stable identifier, e.g. `video_rppg` |
| `version` | string | Detector/model version, logged with every decision |
| `description` | string | One or two sentences, written for the planner to read |
| `modalities` | list | `video`, `audio`, `image`, `text` |
| `endpoint` | URL | Where the orchestrator calls the detector |
| `input_requirements` | object | See 4.2 |
| `output` | object | Score meaning, confidence, and the `insufficient_signal` status (see 4.3) |
| `cost` | object | Expected latency (p50 / p95), device (`cpu` / `gpu`), memory |
| `known_limitations` | list of strings | Plain-language failure modes; feeds directly from `docs/failure_notes.md` |
| `complements` | list | Detector ids whose evidence combines well with this one (e.g. sync + voice spoofing) |
| `status` | enum | `ready`, `degraded`, `unavailable` (fed by `/health`) |

### 4.2 `input_requirements`

| Field | Example | Motivated by |
|---|---|---|
| `min_duration_s` | `2.0` (rPPG needs a stable signal) | Very short clip case |
| `max_duration_s` | `120` | Compute budget |
| `min_resolution` | `[224, 224]` | Poor-quality inputs |
| `requires_audio` | `true` (SyncNet, AASIST) | Silent video case |
| `requires_face` | `true` (rPPG, SyncNet) | Occluded / no-face case |
| `min_face_visibility` | `0.6` (fraction of frames with a usable face) | Partially occluded face case |
| `min_luminance` | `0.15` (normalized) | Poorly lit clip case |
| `accepted_formats` | `["mp4", "wav"]` | Preprocessing errors |

### 4.3 Output contract addition

Every detector response includes a `status` of `ok`, `insufficient_signal`, or `error`, plus a `confidence` value separate from the score. This is the guard-rail behaviour Task 4 tests for, made part of the API contract. The debate layer can then treat "could not judge" differently from "judged real."

### 4.4 Example manifest (illustrative, values to be confirmed by detector owners)

```json
{
  "id": "video_rppg",
  "version": "0.1.0",
  "description": "Detects synthetic faces by checking for a physiological pulse signal (rPPG) in facial video.",
  "modalities": ["video"],
  "endpoint": "http://detector-rppg:8000/analyze",
  "input_requirements": {
    "min_duration_s": 2.0,
    "requires_face": true,
    "min_face_visibility": 0.6,
    "min_luminance": 0.15,
    "requires_audio": false
  },
  "output": {
    "score": "probability the video is synthetic (0-1)",
    "statuses": ["ok", "insufficient_signal", "error"]
  },
  "cost": { "latency_p50_s": 4.0, "latency_p95_s": 9.0, "device": "cpu" },
  "known_limitations": [
    "Unreliable under heavy compression",
    "Unreliable in low light or with occluded faces"
  ],
  "complements": ["video_frame", "audio_visual_sync"],
  "status": "ready"
}
```

## 5. Planning prompt structure

The prompt has fixed sections in a fixed order so behaviour is predictable and testable. Only **structured, validated fields** are inserted into it; raw filenames or embedded metadata strings are never passed through as free text, because they are untrusted input and a prompt-injection path.

1. **Role and objective** — "You are the planning component of a deepfake verification system. Choose which detectors to run."
2. **Hard rules** — only choose from the provided eligible list; never invent detector ids; stay within budget; if nothing is eligible, say so.
3. **Input summary** — structured metadata: modality, duration, resolution, has_audio, face_visibility, luminance.
4. **Request constraints** — risk profile (`low` / `standard` / `high`), latency ceiling, device availability.
5. **Eligible detectors** — compact table generated from manifests (id, description, cost, limitations, complements).
6. **Excluded detectors** — id plus the reason (e.g. "requires audio; input has none"), so the plan can acknowledge coverage gaps.
7. **Selection guidance** — high risk favors coverage over cost; tight budget favors staged execution; prefer complementary detectors over redundant ones.
8. **Output schema** — JSON only, matching the plan schema below.
9. **Few-shot examples** — 3 to 5 worked examples, including the Task 4 edge cases.

### Plan output schema

```json
{
  "plan_version": "1",
  "stages": [
    { "stage": 1, "run": ["video_frame"], "mode": "parallel" },
    { "stage": 2, "run": ["video_rppg", "audio_visual_sync"], "mode": "parallel",
      "condition": "stage 1 score between 0.3 and 0.7" }
  ],
  "skipped": [
    { "id": "audio_spoofing", "reason": "input has no audio track" }
  ],
  "coverage_warnings": ["No audio-based evidence available for this input."],
  "estimated_latency_s": 12.0,
  "rationale": "Short explanation of why these detectors were chosen."
}
```

Prompt settings: temperature 0 (or lowest available), JSON-only output, a low `max_tokens`, and the prompt template version hashed and logged with each decision.

## 6. Validation and fallback

The validator rejects a plan and triggers the rule-based fallback when:

- The plan is not valid JSON or does not match the schema
- It references a detector id that is not in the manifest set
- It includes a detector that failed the eligibility filter
- Estimated latency exceeds the request budget
- The planner call times out or errors

Fallback is logged as a first-class event (`fallback=true`, with the reason), so the planner's real failure rate is measurable.

## 7. Minimal first success criterion

The first milestone is met when the LLM planner, on a fixed **planning test set**, satisfies all of the following. Thresholds are proposals for the team to adjust.

| # | Criterion | Target |
|---|---|---|
| 1 | **Test set** covers each modality, mixed inputs, and the Task 4 edge cases (silent video, clip < 2 s, occluded face, poorly lit) | ≥ 20 cases |
| 2 | **Schema validity** — plans parse and match the schema | 100% |
| 3 | **Eligibility safety** — no plan includes an ineligible or non-existent detector | 100% after validation (raw rate reported separately) |
| 4 | **Budget compliance** — estimated latency within the request budget | 100% |
| 5 | **Agreement with reference plans** written by the team for the test set | ≥ 80% (exact detector set match, or a superset that stays within budget) |
| 6 | **Edge-case handling** — every Task 4 case yields a plan with a coverage warning rather than a confident-looking selection of unusable detectors | 100% |
| 7 | **Fallback works** — with the LLM disabled or timing out, the baseline still serves the request | Verified in a test |
| 8 | **Planner overhead** — added latency from the planning call | ≤ 3 s at p95 |
| 9 | **Explainability** — every decision has a stored rationale plus manifest versions and prompt hash | 100% of log rows |

## 8. Decision log changes

Extend the SQLite decision log **[confirm current schema]** with:

`planner_type` (rule / llm), `model_id`, `prompt_version_hash`, `manifest_versions` (JSON), `input_summary` (JSON), `plan` (JSON), `rationale`, `fallback` (bool), `fallback_reason`, `latency_planning_ms`.

This log is also the raw material for evaluating the planner against the baseline and for the debate layer's chain-of-evidence reports.

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Hallucinated or ineligible detector chosen | Deterministic eligibility filter + validator; LLM only sees eligible ids |
| Non-deterministic plans across runs | Temperature 0, versioned prompt, log everything, regression test set |
| Prompt injection via filenames or embedded metadata | Only structured, validated fields enter the prompt |
| Planner latency or cost hurts the budget | Compact manifest table, small output schema, caching identical input profiles, fallback on timeout |
| Manifests drift from real detector behaviour | Manifests versioned with detectors; CI check that `/capabilities` conforms to the schema in `shared/json-api-contracts-schema/` |
| Over-reliance on the LLM for safety-critical decisions | Hard constraints stay in code; high-risk profile can force a minimum detector set |

## 10. Open questions for the team

1. Should a **high** risk profile force a minimum detector set regardless of the planner's choice?
2. Which model and hosting option will the planner use, and what is the latency/cost ceiling? (Relevant to the edge-optimized goal of the project.)
3. Should the planner support **staged/conditional execution** in the first milestone, or start with a single parallel stage?
4. Where should `/capabilities` live in the API contract, and who owns each detector's manifest?
5. Should the debate layer receive the plan and its rationale, so it can weigh evidence from detectors that were skipped or returned `insufficient_signal`?
6. Should the MCP server expose the plan (or a "dry-run plan only" tool) as its own tool?

## 11. Month 2 kickoff checklist

- [ ] Agree on the manifest schema and add it to `shared/json-api-contracts-schema/`
- [ ] Add `GET /capabilities` and the `insufficient_signal` status to each detector stub
- [ ] Build the planning test set with reference plans (include the Task 4 cases)
- [ ] Implement eligibility filter and plan validator (both testable without an LLM)
- [ ] Implement the LLM planner behind a feature flag with the rule-based fallback
- [ ] Extend the decision log and add planner-vs-baseline comparison to `eval/`
