# AEGIS Live Path Load Test — Real Model Inference in the Loop

**Task:** Week 10 Task 6 (Cybersecurity) — closes Month 2 limitation **M2-L15**
**Date:** 2026-11-16 19:02 UTC
**Script:** `eval/scripts/load_test_live_inference.py`
**Host:** Windows 10, 10 physical / 16 logical cores (Intel64 Family 6 Model 154 Stepping 3, GenuineIntel), 16 GB RAM, CPU only (no GPU)

## 1. What changed versus the Month 2 test

The Month 2 report (`streaming_load_test_report.md`) claimed 32 feeds PASS, but it timed only the client's
`sendall()` call, never ran a model, and (because its fixture path no longer existed) streamed a single
160x120 uniform grey PNG. This test closes those gaps:

| | Month 2 test | This test |
|---|---|---|
| Frames | 160x120 synthetic grey PNG | 640-wide JPEG (q90) from looping real face videos |
| Camera identity | one shared client cert | one CA-signed cert per camera (`cam-01`...), so PRNU baselines are per camera |
| Security profile | dev (audit only) | **prod** (any integrity false positive severs the feed) |
| AI in the loop | none (`ai_score=0.10` placeholder) | face tracking + MobileNetV3-Small INT8 sliding window (16/8) + streaming CHROM rPPG on every frame |
| Fusion | placeholder score | `FeedFusionEngine` with the real AI score |
| Latency measured | client socket write | **frame sent -> fused verdict ready** (`sent_at` vs gateway completion time) |

Gateway settings: PRNU check every 10 frames (bootstrap 8), face re-detection every 5 frames,
ONNX Runtime intra-op threads = 1 per call, inference offloaded with `asyncio.to_thread`.
Each tier ran 60 s at 25 FPS per feed; the first 10 s are excluded as warm-up.

**Pass criteria (all must hold):** every feed keeps >= 90% of its frames through the full path;
p95 end-to-end latency <= 500 ms; no latency backlog (late-window p50 <= 2x early-window p50
unless under 150 ms); zero severed connections.

## 2. Results

| Feeds | FPS / feed | Min retention | Aggregate FPS | E2E p50 (ms) | E2E p95 (ms) | E2E p99 (ms) | Inference / frame p50 (ms) | Model window p50 / p95 (ms) | Gateway CPU (% of 1 core) | Peak RSS (MB) | Severed | Verdict |
|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 2 | 25.01 | 100% | 50.0 | 15.2 | 103.7 | 121.6 | 3.1 | 82.0 / 102.8 | 123.3 | 407.9 | 0 | **PASS** |
| 4 | 25.3 | 99% | 101.2 | 374.8 | 4509.9 | 4895.7 | 4.6 | 123.5 / 240.6 | 332.7 | 611.5 | 0 | **FAIL** |
| 8 | 19.91 | 76% | 159.3 | 6175.5 | 9321.7 | 10016.1 | 6.4 | 214.2 / 257.8 | 649.6 | 1025.8 | 0 | **FAIL** |
| 12 | 12.59 | 49% | 151.0 | 11281.0 | 16134.2 | 17283.6 | 10.0 | 337.5 / 398.9 | 795.2 | 1443.9 | 0 | **FAIL** |
| 16 | 9.78 | 33% | 156.5 | 15360.8 | 21164.9 | 22567.9 | 12.1 | 416.0 / 515.9 | 843.3 | 1813.5 | 0 | **FAIL** |

### Failure reasons
- **4 feeds:** p95 e2e 4509.9 ms > 500 ms
- **8 feeds:** min retention 76% < 90%; p95 e2e 9321.7 ms > 500 ms
- **12 feeds:** min retention 49% < 90%; p95 e2e 16134.2 ms > 500 ms
- **16 feeds:** min retention 33% < 90%; p95 e2e 21164.9 ms > 500 ms

**Real concurrent-feed limit on this host: 2 feeds** (first failing tier: 4 feeds).

## 3. Inference sanity check (is the model really running?)

Offline pass of the same inference stage over the first 200 frames of each source:

| Source | Frames | Face found | Mean MobileNetV3 P(fake) |
|---|:-:|:-:|:-:|
| `authentic_feed` | 200 | 100% | 0.876 |
| `deepfake_feed` | 200 | 100% | 0.838 |

## 4. Interpretation

- **The Month 2 headline of 32 feeds does not survive real inference.** On this 16-thread laptop CPU the live path holds
  **2 feeds at 25 FPS**. At 4 feeds every frame still arrives (99% retention) but end-to-end latency backs up to a p95 of
  4.5 s. From 8 feeds upward frames are lost (76% → 33% retention) and latency reaches 9–21 s. Aggregate throughput
  plateaus at about 155 frames/s whatever the feed count.
- **The bottleneck is contention inside one gateway process, not raw compute.** At 16 feeds the gateway used only about
  8.4 of 16 logical cores, yet the same 16-frame MobileNetV3 batch slowed from 82 ms to 416 ms p50 and the per-frame stage
  from 3.1 ms to 12.1 ms. Each camera's frames are processed sequentially, and JSON/hex parsing, hashing and
  stream validation all run on the single asyncio thread under the GIL. mTLS and hash chaining are cheap.
- **Inference is genuinely in the loop, but it does not separate these two sample feeds:** mean P(fake) is 0.88 on
  `authentic_feed` and 0.84 on `deepfake_feed`, with a tight face crop matching training. Widening the crop does not fix it
  (0.69–0.93 for both). This is an edge-model generalisation issue for the AI team, not a load-test artefact, and it does
  not affect the capacity numbers.
- **Soak (2 feeds, 60 min, 24 reconnect cycles):** no severed connections, flat latency (p95 77–89 ms) and flat
  threads/handles. RSS shows slow baseline growth (+53 MB/h in the 5-minute minima), marked **WATCH**. See
  `live_inference_soak_report.md`.
- **Scaling options, cheapest first:** run the spatial model on every 2nd frame (the 16/8 window already smooths); move
  decode + inference to a `ProcessPoolExecutor` or separate worker processes, which removes GIL contention; shard cameras
  across several gateway processes behind the same CA; add a GPU execution provider. Re-run this script after each change.

## 5. Reproduce

```bash
python eval/scripts/load_test_live_inference.py --tiers 4 8 16 --duration 60
python eval/scripts/load_test_live_inference.py --soak --soak-feeds <limit> --soak-minutes 60
```
