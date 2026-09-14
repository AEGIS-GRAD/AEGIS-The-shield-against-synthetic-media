# AEGIS — Early Failure Notes

Running log of misclassifications observed while benchmarking detectors. Updated after each benchmark pass (Week 2, Week 3, Week 4, ...) as more detectors come online. Goal: surface real, per-detector failure modes early so the Month 2 debate-layer design doesn't assume uniform reliability across detectors.

## How to use this doc
- After each benchmark run, pull the 10–15 worst misclassifications per detector (highest-confidence wrong predictions, plus any false negatives on known-hard samples).
- For each case, fill one row in the relevant detector's table below.
- At the end of each week's pass, add a short "Patterns observed" summary — this is the part that actually feeds the debate-layer design, not the raw rows.
- Don't delete old entries when a detector improves — strike them through or move them to the "Resolved" subsection so the history of what got fixed is preserved.

---

## Week 2 Benchmark

### Detector: Video Frame-Level Classifier (EfficientNet-B0, FF++ c23)

| # | Sample ID / path | True label | Predicted | Confidence | Notes on visible pattern |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

**Patterns observed:**
-

### Detector: AASIST (Audio Voice Spoofing)

| # | Sample ID / path | True label | Predicted | Confidence | Notes on visible pattern |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

**Patterns observed:**
-

### Detector: rPPG (Heartbeat Consistency, CHROM)

Note: rPPG has no trained decision boundary, so "misclassification" here means
cases where the signal-quality heuristic gave an implausible or clearly wrong
verdict — not a labeled accuracy failure. Also log cases where the estimated
BPM was wildly implausible (e.g. outside 40–180) even if the final verdict
happened to be correct, since that signals the extraction itself is unreliable
on that sample.

| # | Sample ID / path | True label | Predicted | Estimated BPM | Notes on visible pattern |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

**Patterns observed:**
-

### Cross-detector observations
-

---

## Week 3 Benchmark
*(append new detector sections here as they come online; keep Week 2 sections above intact)*

---

## Week 4 Benchmark
*(append here)*

---

## Resolved / Improved
Cases from earlier weeks that a later fix (preprocessing change, retraining, threshold tuning) resolved. Keep a one-line reference back to the original entry.

| Week found | Detector | Sample ID | Fix applied |
|---|---|---|---|
| | | | |
