# AEGIS — Month 1 AI Track: Results & Open Questions

**Audience:** Cybersecurity track, Dev/Orchestration track, Dr. Amr, TA. Ramez
**Purpose:** What the AI track *learned* this month, not just what it shipped — for the Month 1 milestone review.
**Source data:** `eval/reports/week_benchmark_report.md`, `eval/reports/week_benchmark_raw.csv` (120-sample full-pipeline run, 0 failed/skipped runs at the pipeline level).

---

## 1. Baseline Accuracy Numbers (per detector)

This is the number Month 2's orchestrator/debate logic will be measured against.

| Detector | Times Called | Individual Accuracy | Pipeline Agreement | Mean Latency | P95 Latency |
|---|---|---|---|---|---|
| **AASIST** (audio) | 120 / 120 | 0.500 | 1.000 | 235 ms | 334 ms |
| **video-classifier** | 60 / 60 | 0.467 | 0.900 | 7,029 ms | 14,961 ms |
| **rPPG** | 60 / 60 | 0.467 | 0.100 | 6,608 ms | 15,850 ms |
| **SyncNet** | 58 / 60 | 0.517 | 1.000 | 9,587 ms | 22,834 ms |

**Overall end-to-end pipeline accuracy: 0.500** (60/120 correct) — statistically no better than a coin flip.

Note: SyncNet ran on only 58 of 60 video samples — the other 2 were correctly skipped as not-applicable (silent video), confirming this is a real, recurring case in practice and not just a hypothetical the web track needs to design around.

---

## 2. Biggest Open Reliability Concerns

We're flagging these plainly rather than smoothing them over, since Month 2 will build directly on top of them.

**1. Overall pipeline accuracy (50%) is not meaningfully above chance.**
Individually, AASIST sits exactly at 0.50 and video-classifier/rPPG sit *below* 0.50. Only SyncNet (0.517) is marginally above chance. Nothing in the current pipeline is yet a reliable signal on its own.

**2. rPPG is being weighted 1.2× in aggregation despite 10% pipeline agreement.**
Individual accuracy near-random is one problem; agreeing with the final verdict only 10% of the time is a separate and bigger one — it suggests rPPG's verdicts are close to noise relative to what the other detectors + aggregation are converging on, yet the current heuristic still gives it above-baseline weight.

**3. The aggregation weights are an unvalidated placeholder.**
The weighting scheme (video-classifier ×1.5, rPPG ×1.2, SyncNet ×1.2, AASIST ×1.0) is explicitly marked as a placeholder heuristic in `orchestrator/app/aggregate.py`, not something derived from this benchmark's accuracy numbers. Right now the two *least* individually-accurate detectors (video-classifier, rPPG) carry the *most* weight.

**4. UNCERTAIN / NO_RESULTS verdicts are currently scored as "authentic."**
This is a scoring-methodology choice, not a pipeline bug, but it's worth the team's attention: in a security context, defaulting an uncertain verdict to "authentic" is the riskier failure direction (a missed deepfake vs. a false alarm). This choice also inflates the accuracy figure somewhat, since it silently resolves ambiguity in favor of one class.

**5. Latency is incompatible with the live-surveillance use case as currently designed.**
SyncNet's P95 latency (22.8s) and video-classifier's (15.0s) are far beyond what real-time frame-by-frame monitoring can tolerate. This doesn't block Month 1, but it's a hard constraint Month 2's real-time path needs to design around explicitly, not discover later.

---

## 3. Open Questions for Month 2 (Orchestration & Debate)

**Q1 — How should the debate/planner weight a detector we now know is statistically unreliable (rPPG), rather than one we merely suspect is unreliable?**
This isn't hypothetical anymore — we have the number (10% pipeline agreement). Should Month 2's aggregation logic drop the static weights in favor of confidence- or reliability-conditioned weighting, and if so, whose job is it to own that logic — orchestration or debate?

**Q2 — Should UNCERTAIN/NO_RESULTS default to "authentic" or "flag for review," and who decides that policy?**
This is currently an AI-track scoring convention, but it's really a product/security policy decision (false-negative vs. false-positive tolerance), so it shouldn't stay buried in `aggregate.py` — we'd like Cybersecurity's input before Month 2 locks in debate logic around it.

**Q3 — For the live-surveillance path specifically, should slow detectors (SyncNet, video-classifier) be excluded from real-time mode entirely, or run on a sampled/delayed basis?**
Given the ADR's real-time monitoring requirements, we don't think all four detectors can realistically run in the live path at current latency. We need a decision on which detectors are "live-eligible" before Month 2's real-time orchestration is designed, not after.

---

## Bottom line for the team

Month 1 shipped a working, schema-compliant, end-to-end pipeline (120/120 runs completed, 0 crashes) — the *infrastructure* goal is met. But the pipeline's *accuracy* is not yet above chance, and the current aggregation weighting isn't backed by this month's own data. Month 2 orchestration/debate work should treat this benchmark as the floor to beat, not a working baseline to build features on top of unquestioned.
