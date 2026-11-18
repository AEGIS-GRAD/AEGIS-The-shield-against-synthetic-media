# Poisoning Red-Team Log — Judge and Planner

**Task:** Week 11 Cybersecurity Task 2 · **Date:** 2026-11-16
**Harness:** `security/redteam/poisoning_redteam.py` (raw results `security/docs/poisoning_redteam_results.json`)
**Targets:** `debate.judge_agent.JudgeAgent` (deterministic mode, the production default) and `orchestrator/app/planner.py`
(LLM mode with the reference plan, i.e. what the planner does when the LLM agrees with its own heuristic)
**Mitigations:** `debate/poisoning_guards.py` (judge), `orchestrator/app/planner_guards.py` (planner); on by default,
`AEGIS_POISONING_GUARDS=0` restores Week 10 behaviour
**Feeds:** AI-team alignment study B (scenario set, categories and guard trade-offs below)

## 1. Threat model for this exercise

The attacker controls **one input channel**, not the whole system: one detector's output (compromised container or model),
the claim wrapper, the operating-conditions metadata, the Prometheus series the planner reads, or the media's
container metadata. Success means the final verdict reaches the attacker's goal: *hide* (a deepfake judged AUTHENTIC) or
*frame* (a genuine clip judged SYNTHETIC), or the planner drops the primary visual detector. UNCERTAIN and
INTEGRITY_UNKNOWN count as failures for the attacker, because both escalate to a human with a P2 SIEM alert.

## 2. Judge results

Honest evidence for the deepfake: video-classifier SYN 0.86, syncnet SYN 0.74, rPPG SYN 0.68, AASIST AUTH 0.22 (donor's real
voice). Honest evidence for the genuine clip: all four AUTHENTIC.

| ID | Category | Attack | Goal | Week 10 judge | With guards | Guard |
|---|---|---|---|---|---|---|
| J0a/b | control | honest evidence | — | SYNTHETIC / AUTHENTIC | SYNTHETIC / AUTHENTIC | — |
| J1 | single compromised detector | video-classifier says AUTHENTIC 0.01 | hide | **AUTHENTIC** | UNCERTAIN | QG1 dissent veto |
| J2 | single compromised detector | video-classifier says SYNTHETIC 0.99 on a genuine clip | frame | **SYNTHETIC** | **SYNTHETIC** | residual (§4) |
| J3 | two colluding detectors | video-classifier + syncnet say AUTHENTIC | hide | INTEGRITY_UNKNOWN | INTEGRITY_UNKNOWN | existing G1 |
| J4 | miscalibration | AASIST says SYNTHETIC 0.999 on a genuine clip | frame | **SYNTHETIC** | **SYNTHETIC** | residual (§4); confidence capped to 0.97 (PG4) |
| J5 | polarity/confidence inconsistency | video-classifier: AUTHENTIC with P(synthetic)=0.97 | hide | SYNTHETIC | UNCERTAIN | PG3 neutralises the contradictory claim |
| J6 | self-serving flags | rPPG self-flags `low_light`, syncnet self-flags `silent_video` (+ J1) | hide | **AUTHENTIC** | UNCERTAIN | PG6 flags not corroborated + QG1 |
| J7 | spoofed operating conditions | conditions say dark, no face, no audio, 1.5 s (+ J1) | hide | **AUTHENTIC** | UNCERTAIN | PG7 conditions contradicted by confident face/audio evidence → ignored, then QG1 |
| J8 | domain spoofing | video-classifier speaks in the physiological domain (+ J1) | hide | **AUTHENTIC** | UNCERTAIN | PG2 domain rebinding + QG1 |
| J9 | Sybil / duplicates | five AUTHENTIC claims from one detector | hide | **AUTHENTIC** | UNCERTAIN | PG1 one vote per detector + QG1 |
| J10 | self-reported attenuation | honest claims carry attenuation 0.0, one compromised SYNTHETIC | frame | **SYNTHETIC** | **SYNTHETIC** | PG5 resets the attenuation; the remaining effect is J2 framing |
| J11 | abstention | compromised video-classifier abstains; rPPG fooled by donor pulse | hide | **AUTHENTIC** | AUTHENTIC by default; **UNCERTAIN with QG2** | QG2 (opt-in, §5) |

**Success rate:** against the Week 10 judge **9/11** attacks succeed (J3 and J5 already failed). With the default guards
**4/11** succeed: the three *framing* attacks J2, J4, J10, plus J11 (abstention). With the opt-in QG2 also enabled,
**3/11** succeed, all of them framing. Of the six "hide" attacks that worked before (J1, J6, J7, J8, J9, J11), the
default guards block five and QG2 blocks the sixth. Hiding a deepfake is the error class the supervisor's anti-default
mandate treats as the costlier one.

## 3. Planner results

| ID | Category | Attack | Week 10 planner | With guards | Guard |
|---|---|---|---|---|---|
| P0 | control | healthy telemetry | fusion, streaming-rppg, video-classifier | same | — |
| P1 | telemetry spoofing | Prometheus series says video-classifier `up=0` | **video-classifier dropped** | kept | PL1 primary needs first-hand (circuit-breaker) evidence |
| P2 | telemetry spoofing | everything but rPPG marked down | **only rPPG-based detectors** | video-classifier kept | PL2 mass-exclusion sanity + PL1 |
| P3 | cache poisoning | plan made under spoofed telemetry, then telemetry recovers | **poisoned plan served from cache** | fresh plan | PL3 exclusions in cache key, telemetry-shaped plans not cached |
| P4 | metadata spoofing | audio track hidden from ffprobe | no change, **because audio detectors are never scheduled** | no change | finding F-P4 below |
| P5 | telemetry spoofing | spoofed 60 s p95 latency for video-classifier | **video-classifier dropped to save budget** | kept | PL4 mandatory primary |

**Finding F-P4 (for the AI team):** with the default 3 s compute budget the planner schedules
`fusion, streaming-rppg, video-classifier` for a video *with* audio, so AASIST and SyncNet never run. Voice cloning and lip-sync
evidence are therefore absent by default, and an attacker gains nothing by hiding the audio track, because the coverage is
already missing. Either raise the budget for videos with audio or make one audio detector mandatory for `has_audio=True`.

## 4. Residual: framing by one compromised primary detector

J2, J4 and J10 share one root cause. The precedence matrix lets one *primary* detector certify manipulation in its own
domain: video-classifier for face swaps (rule 3, because pulse, voice and lip sync survive a face swap) and AASIST for voice
clones (rule 5). A compromised primary detector produces exactly the claim pattern of a real face swap or voice clone, so
no claim-level rule can separate them without also refusing real detections. We measured that: a dissent veto on
SYNTHETIC turns the existing face-swap and voice-clone regression tests into UNCERTAIN.

Proposed controls, in order of cost:

1. **Detector integrity (now possible):** pin model fingerprints (`security/forensics/model_provenance.py`) and record them in every
   verdict (Week 11 Task 4). A swapped model is then visible in the evidence.
2. **Redundant primary witness:** require a second, independently trained spatial model (e.g. the MobileNetV3 edge model or the
   Community Forensics image detector on keyframes) to agree before a *single-domain* SYNTHETIC is certified. When it does not,
   the verdict becomes UNCERTAIN. Cost: more human reviews on real face swaps that only one model catches; needs AI-team
   measurement in alignment study B.
3. **Calibration monitoring:** the QG3 outlier report flags any detector that sits more than 0.45 from the consensus median.
   Tracking the per-detector outlier rate over time exposes a detector that has started lying.

## 5. Mitigations implemented

| Guard | Where | What it does | Default |
|---|---|---|---|
| PG1 | judge, pre | one claim per detector | on |
| PG2 | judge, pre | detector bound to its registered evidence domain | on |
| PG3 | judge, pre | polarity contradicting the probability → INCONCLUSIVE | on |
| PG4 | judge, pre | confidence capped to [0.03, 0.97] | on |
| PG5 | judge, pre | self-reported attenuation honoured only if measured conditions corroborate it | on |
| PG6 | judge, pre | `low_light` / `short_clip` / `silent_video` flags honoured only if measured conditions corroborate them | on |
| PG7 | judge, pre | operating conditions contradicted by confident face/audio evidence are ignored | on |
| QG1 | judge, post | no AUTHENTIC while an un-discounted detector credibly says SYNTHETIC | on |
| QG2 | judge, post | no AUTHENTIC for video without an active spatial witness | **opt-in** (`AEGIS_REQUIRE_SPATIAL_WITNESS=1`): it changes one existing AI-team expectation (`test_arbitrate_unanimous_authentic` certifies a video from rPPG + SyncNet alone), so it needs their sign-off |
| QG3 | judge, post | outlier report in `coverage_warnings` | on (informational) |
| PL1–PL4 | planner | see `planner_guards.py` | on |

Claim-hygiene notes and outlier reports go to `verdict.coverage_warnings`. Only real downgrades go to
`guards_applied`, so existing invariants ("a guard implies not AUTHENTIC") still hold.

**Regression impact:** debate + MCP suites 201/201 pass with the default guards (200/201 with QG2, the one expected change).
The orchestrator suite has 93 passing and 5 failing tests in `test_planner_pipeline.py` **both with and without** the planner
guards. Those 5 failures are pre-existing on `main`.

## 6. Adversarial media

Adversarial *media* (inputs crafted so a detector itself is fooled) are measured by the Week 10 robustness harness
(`eval/robustness/`, report `eval/reports/robustness/robustness_matrix_v1.md`). A detector fooled that way behaves exactly like
the "single compromised detector" rows above: J1-style misses are caught by QG1 only when another domain still sees the
manipulation. Image and text inputs have a single domain, so they get no cross-domain protection.

## 7. Reproduce

```bash
python security/redteam/poisoning_redteam.py
AEGIS_POISONING_GUARDS=0 python -m pytest debate/tests mcp/tests     # Week 10 behaviour
AEGIS_REQUIRE_SPATIAL_WITNESS=1 python security/redteam/poisoning_redteam.py
```
