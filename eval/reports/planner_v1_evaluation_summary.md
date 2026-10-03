# Planner v1 — Evaluation Summary

**Prompt version:** `planner-v2.0`
**Test set:** 19 samples (`orchestrator/app/eval_samples.py`), covering all 4 modalities, the 4 named edge cases from `docs/orchestrator_design.md` §3, budget-pressure variants, and risk-profile variants.
**Model:** `nvidia/nemotron-3.5-lightning:free` via OpenRouter (18/19 runs; 1 run fell back to `nvidia/nemotron-3-ultra-550b-a55b:free`, see Finding 4).
**Full per-sample output:** `eval/reports/planner_v1_evaluation_notes.md`

---

## Result: 18/19 passed validation (94.7%)

Validation = valid JSON + schema-conformant + no ineligible/invented detector used + within budget.

---

## Finding 1 — Soft-signal reasoning (the core design bet) works

The biggest open question going into this task was whether the LLM could correctly reason over **free-text** `known_failure_modes` (no numeric thresholds exist in the real manifests for face visibility or lighting — see note in `eligibility.py`). Across every relevant sample, it did:

- Sample 6 (occluded face): correctly skipped `rppg` and `syncnet`, quoting their documented failure conditions almost verbatim.
- Sample 7 (poor lighting): same pattern — skipped both, correctly distinguished that `rppg` becomes *misleading* (not just noisy) while `syncnet` returns `not_applicable`.
- Sample 19 (borderline face visibility, 0.65 — deliberately ambiguous): the model still read it as "partial occlusion" and skipped both detectors, with a specific citation of the manifest wording.

This validates the architectural choice in `orchestrator_design.md` §3 to keep soft reasoning in the LLM rather than hard-coding visibility/lighting thresholds that don't exist in the manifests.

## Finding 2 — Budget enforcement works, including "nothing fits" (Samples 10, 11)

With tight budgets (6s, 3s) where every eligible detector's own latency exceeded the ceiling, the planner correctly returned an **empty `stages` list** with a clear `coverage_warnings` explanation, rather than forcing a selection that violates the budget. This matches the hard rule in the prompt ("if nothing is eligible... do not force a selection") being correctly extended by the model to "nothing fits the budget" as well, even though the prompt doesn't say that explicitly — worth adding as its own explicit hard rule in v2 of the prompt rather than relying on the model generalizing it.

## Finding 3 — The one failure (Sample 9) is a field-name typo, not a reasoning error

```
"estimated_latency_latency_s": 7.0   ← should be "estimated_latency_s"
```

The reasoning content (correctly skipping `rppg`/`syncnet` under *combined* low-light + occlusion) was right. The failure was purely a malformed key name, on the single hardest sample in the test set (two stacked failure conditions at once). The schema validator caught it correctly, which is exactly what it's for — but a single-condition typo like this would silently corrupt a real pipeline run if the validator didn't exist, which is itself a point in favor of keeping strict validation + fallback as a permanent safety net, not something to relax later.

**Action for prompt v3:** reinforce in the HARD RULES section that output keys must match the schema exactly, character-for-character, with no variations — this is a one-line addition, not a redesign.

## Finding 4 — ⚠️ Planner latency is nowhere near the target, but this looks like a model/provider issue, not a prompt issue

`orchestrator_design.md` §7 criterion #8 sets a target of **≤3s at p95** for planner overhead. Actual results:

| | Value |
|---|---|
| Fastest sample | 21.8s |
| Slowest sample | 365.5s |
| Typical range | 50–300s |

This is **10–120× over target**. Before concluding the planning approach itself is too slow, note:

- All but one call used `nvidia/nemotron-3.5-lightning:free` — a **free-tier** OpenRouter model, which queues behind other free users with no latency SLA.
- Sample 12 silently fell back to a second model in the list (`nemotron-3-ultra-550b-a55b:free`) when the first didn't respond — meaning the first model intermittently fails or times out even before producing an answer, independent of prompt design.
- The prompt itself produced consistent, correctly-reasoned, correctly-structured output in 18/19 cases — nothing here points to the prompt being the slow part.

**Open question for the team (carries into Month 2 orchestration work):** should the real planner use a paid/dedicated model (with a latency SLA) instead of free-tier routing, given the ≤3s p95 target can't realistically be hit on shared free capacity regardless of prompt quality?

## Finding 5 — The model consistently reused our injected latency fallback numbers correctly

Since every manifest's own `performance` field is still `null` (`"measured_on": "PENDING"`), the prompt injects latency figures from `eval/reports/week_benchmark_report.md` as a fallback (see `BASELINE_LATENCY_MS` in `prompt_builder.py`). Across all 19 samples, the model's own `estimated_latency_s` math consistently tracked those injected numbers (e.g. ~7.0s for video-classifier, ~9.6s for syncnet, ~6.6s for rppg) rather than inventing its own figures. This confirms the fallback-injection mechanism is actually being read and used, not ignored.

---

## Recommendation before this touches the live pipeline

1. **Do not change the prompt's reasoning logic** — the soft-signal handling, budget enforcement, and empty-plan fallback all behaved correctly on 18/19 cases including every edge case.
2. **Add one line to HARD RULES** enforcing exact schema key names, to close the Sample 9 gap.
3. **Resolve the latency question (Finding 4) with the team before Month 2 integration** — this is a model/infrastructure decision, not something the prompt can fix.
4. **Keep the plan validator + rule-based fallback as permanent**, not temporary scaffolding — Sample 9 is a concrete demonstration of why orchestrator_design.md §6 specifies it as mandatory, not optional.
