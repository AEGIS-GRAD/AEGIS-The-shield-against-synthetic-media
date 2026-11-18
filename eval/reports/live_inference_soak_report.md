# AEGIS Live Path Soak Test — 60 minutes with real inference

**Task:** Week 10 Task 6 (Cybersecurity) — soak test for leaks under sustained live load
**Date:** 2026-11-16 20:03 UTC
**Script:** `eval/scripts/load_test_live_inference.py --soak --soak-feeds 2 --soak-minutes 60`
**Configuration:** 2 feeds x 25 FPS, prod security profile, full live path (mTLS, hash chain,
sequence validation, PRNU, face tracking, MobileNetV3 INT8, streaming rPPG, fusion). Each camera disconnects and
reconnects every ~300s (staggered) so per-connection state is allocated and freed
**24 times** over the run. Gateway sampled every 15s; trends are fitted after a
5-minute settle period.

## Verdict: **PASS on the pre-registered criterion, status WATCH** (slow baseline growth, see analysis)

> **Analysis (added after review).** The fitted trend passed the threshold only narrowly (+45.8 MB/h vs 50 MB/h).
> RSS swings ±40 MB inside each window (allocator / GC churn), so a fit over raw samples is noisy. The **low-water mark**,
> which is insensitive to that churn, rises steadily: 5-minute minima go 360 → 368 → 374 → 382 → 394 → 382 → 391 → 406 →
> 386 → 393 → 413 → 420 MB, a slope of **+53 MB/h**. Threads (47) and OS handles (505 → 509) are flat, so connections
> are cleaned up; the growth is heap memory. One hour cannot tell slow allocator fragmentation from a small per-frame
> leak, but at this rate a 24-hour run would add about 1.3 GB.
> **Next step:** a 4-hour soak with `tracemalloc` snapshots (5 min vs 4 h) to locate the allocation site. Candidates:
> ONNX Runtime arena growth, per-connection OpenCV cascade objects, PRNU bootstrap buffers. Until then, schedule a gateway
> restart every 24 h. Latency stayed flat for the whole hour (p95 77–89 ms), so throughput is not degrading.

| Resource | After settle | End of run | Fitted trend | Leak threshold | Leak? |
|---|:-:|:-:|:-:|:-:|:-:|
| Gateway RSS (MB) | 367.7 | 438.5 | +45.8 MB/h (+19.3%) | > 50 MB/h and > 10% | no |
| Threads | 47 | 47 | +1.0 /h | > 2/h and > +4 | no |
| OS handles | 505 | 509 | +5.7 /h | > 50/h and > +100 | no |

Severed connections: **0** · client errors: **0** · gateway process alive at end: **True**

## Stability over time

| Window | Frames / feed / s | E2E p50 (ms) | E2E p95 (ms) | Peak RSS (MB) |
|---|:-:|:-:|:-:|:-:|
| 0-10 min | 24.96 | 11.9 | 81.1 | 401.4 |
| 10-20 min | 25.13 | 12.4 | 86.2 | 433.6 |
| 20-30 min | 24.99 | 14.5 | 89.3 | 441.1 |
| 30-40 min | 24.98 | 12.8 | 79.8 | 439.2 |
| 40-50 min | 24.93 | 13.3 | 76.7 | 434.1 |
| 50-60 min | 24.76 | 13.3 | 78.1 | 454.0 |

End-to-end p95 moved from 81.1 ms in the first window to 78.1 ms in the last.
Raw samples: `eval/reports/live_inference_soak_samples.csv`.
