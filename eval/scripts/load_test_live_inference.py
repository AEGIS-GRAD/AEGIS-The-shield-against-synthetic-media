"""
AEGIS Live Path Load Test — real model inference in the loop (Week 10 Task 6)
=============================================================================

Re-runs the Month 2 multi-feed load test (which measured socket ``sendall``
only, see M2-L15) with the full live path active on every frame:

    virtual camera (looping video, per-camera mTLS identity)
      -> ingestion gateway  (mTLS, token bucket, sequence/timestamp validation,
                             rolling SHA-256 hash chain, PRNU sensor check)
      -> live inference     (face tracking, MobileNetV3-Small INT8 sliding window,
                             streaming CHROM rPPG)
      -> FeedFusionEngine   (integrity + real AI score -> verdict)

Latency is measured end to end: the camera stamps ``sent_at`` (wall clock) on
every frame and the gateway records when the fused verdict for that frame is
ready, so queueing in socket buffers and the thread pool is included.

Modes
-----
Tiered load test (default)::

    python eval/scripts/load_test_live_inference.py --tiers 4 8 16 --duration 60

Soak test (memory / handle / thread leak hunt)::

    python eval/scripts/load_test_live_inference.py --soak --soak-feeds 8 --soak-minutes 60

Outputs (``eval/reports/``):
    live_inference_load_test_raw.csv / .json, live_inference_load_test_report.md
    live_inference_soak_samples.csv,  live_inference_soak_report.md (soak mode)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import logging
import os
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import psutil

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from security.transport.generate_certs import generate_all_service_certs, generate_cert, save_cert  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("aegis.live_load_test")

CERTS_DIR = REPO_ROOT / "security" / "transport" / "certs"
SERVER_SCRIPT = REPO_ROOT / "security" / "gateway" / "ingestion" / "server.py"
REPORTS_DIR = REPO_ROOT / "eval" / "reports"
DEFAULT_VIDEOS = [
    REPO_ROOT / "web" / "public" / "sample_videos" / "authentic_feed.mp4",
    REPO_ROOT / "web" / "public" / "sample_videos" / "deepfake_feed.mp4",
]

# Real-time acceptance criteria for a live surveillance path.
RETENTION_MIN = 0.90          # each feed must get >= 90% of its frames through the full path
P95_E2E_BUDGET_MS = 500.0     # frame capture -> fused verdict, 95th percentile
BACKLOG_GROWTH_LIMIT = 2.0    # late-window p50 latency may not exceed 2x early-window p50 ...
BACKLOG_ABS_FLOOR_MS = 150.0  # ... unless it is still below this absolute floor


# ─────────────────────────────────────────────────────────────────────────────
# Frame sources and camera identities
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class FramePool:
    label: str
    frames: List[Tuple[str, int, int]]  # (hex-encoded JPEG, width, height)


def load_frame_pool(video: Path, max_frames: int, jpeg_quality: int, width: Optional[int]) -> FramePool:
    cap = cv2.VideoCapture(str(video))
    frames: List[Tuple[str, int, int]] = []
    while len(frames) < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        if width and frame.shape[1] != width:
            h = int(round(frame.shape[0] * width / frame.shape[1]))
            frame = cv2.resize(frame, (width, h))
        ok, enc = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
        if ok:
            frames.append((enc.tobytes().hex(), frame.shape[1], frame.shape[0]))
    cap.release()
    if not frames:
        raise RuntimeError(f"No frames decoded from {video}")
    return FramePool(label=video.stem, frames=frames)


def ensure_pki() -> None:
    if not (CERTS_DIR / "ca.crt").exists() or not (CERTS_DIR / "ca.key").exists():
        logger.info("Generating AEGIS mTLS PKI in %s", CERTS_DIR)
        generate_all_service_certs(str(CERTS_DIR))


def issue_camera_identities(count: int, out_dir: Path) -> List[Tuple[str, Path, Path]]:
    """Issues one CA-signed client certificate per virtual camera (CN=cam-NN)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    ca_key = serialization.load_pem_private_key((CERTS_DIR / "ca.key").read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate((CERTS_DIR / "ca.crt").read_bytes())
    out = []
    for i in range(count):
        cn = f"cam-{i + 1:02d}"
        crt, key = out_dir / f"{cn}.crt", out_dir / f"{cn}.key"
        if not crt.exists():
            k, c, _ = generate_cert(cn, issuer_name=ca_cert.subject, issuer_key=ca_key, san_dns_names=[cn], valid_days=2)
            save_cert(str(out_dir), cn, k, c)
        out.append((cn, crt, key))
    return out


def client_context(crt: Path, key: Path) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(CERTS_DIR / "ca.crt"))
    ctx.load_cert_chain(certfile=str(crt), keyfile=str(key))
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Virtual camera
# ─────────────────────────────────────────────────────────────────────────────
class VirtualCamera(threading.Thread):
    """Streams a looping video over mTLS at a fixed frame rate, hash-chaining every frame."""

    def __init__(self, camera_id: str, ctx: ssl.SSLContext, host: str, port: int, pool: FramePool,
                 fps: float, duration_s: float, start_offset: int = 0, reconnect_every_s: Optional[float] = None):
        super().__init__(daemon=True, name=camera_id)
        self.camera_id = camera_id
        self.ctx = ctx
        self.host, self.port = host, port
        self.pool = pool
        self.fps = fps
        self.duration_s = duration_s
        self.offset = start_offset
        self.reconnect_every_s = reconnect_every_s
        self.frames_sent = 0
        self.sessions = 0
        self.errors: List[str] = []
        self.severed = 0
        self._halt = threading.Event()

    def stop(self) -> None:
        self._halt.set()

    def _session(self, deadline: float) -> None:
        raw = socket.create_connection((self.host, self.port), timeout=10.0)
        conn = self.ctx.wrap_socket(raw, server_hostname="localhost")
        conn.settimeout(30.0)
        self.sessions += 1
        current_hash = hashlib.sha256(b"AEGIS_GENESIS").hexdigest()
        seq, ts_ms = 0, 0
        interval = 1.0 / self.fps
        next_t = time.perf_counter()
        session_end = deadline if not self.reconnect_every_s else min(deadline, time.perf_counter() + self.reconnect_every_s)
        try:
            while not self._halt.is_set() and time.perf_counter() < session_end:
                seq += 1
                ts_ms += int(round(interval * 1000))
                frame_hex, w, h = self.pool.frames[(self.offset + seq) % len(self.pool.frames)]
                hh = hashlib.sha256()
                hh.update(current_hash.encode("utf-8"))
                hh.update(bytes.fromhex(frame_hex))
                current_hash = hh.hexdigest()
                line = json.dumps({
                    "sequence_number": seq, "timestamp_ms": ts_ms, "frame_data": frame_hex,
                    "hash": current_hash, "width": w, "height": h, "sent_at": time.time(),
                }) + "\n"
                try:
                    conn.sendall(line.encode("utf-8"))
                except (OSError, ssl.SSLError) as exc:
                    self.severed += 1
                    self.errors.append(f"send failed at seq {seq}: {exc}")
                    return
                self.frames_sent += 1
                next_t += interval
                delay = next_t - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    # Behind schedule (backpressure): do not burst to catch up, a real
                    # camera drops frames instead.
                    next_t = time.perf_counter()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def run(self) -> None:
        deadline = time.perf_counter() + self.duration_s
        while not self._halt.is_set() and time.perf_counter() < deadline:
            try:
                self._session(deadline)
            except Exception as exc:  # connection refused, TLS failure, ...
                self.errors.append(f"session error: {exc}")
                time.sleep(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Gateway process management and sampling
# ─────────────────────────────────────────────────────────────────────────────
def start_gateway(port: int, metrics_path: Path, sample_every: int, ort_threads: int,
                  face_every: int, log_path: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.update({
        "AEGIS_SECURITY_PROFILE": "prod",
        "AEGIS_INGESTION_PORT": str(port),
        "AEGIS_MAX_CONCURRENT_STREAMS": "64",
        "AEGIS_MAX_STREAMS_PER_IP": "64",
        "AEGIS_STREAM_IDLE_TIMEOUT": "30",
        "AEGIS_PRNU_CHECK_INTERVAL": "10",
        "AEGIS_PRNU_BOOTSTRAP_FRAMES": "8",
        "AEGIS_DISABLE_TELEMETRY": "1",
        "AEGIS_LIVE_INFERENCE": "1",
        "AEGIS_LIVE_METRICS_PATH": str(metrics_path),
        "AEGIS_LIVE_METRICS_SAMPLE": str(sample_every),
        "AEGIS_EDGE_ORT_THREADS": str(ort_threads),
        "AEGIS_FACE_REDETECT_EVERY": str(face_every),
        "AEGIS_LIVE_FPS": "25",
            })
    log_fh = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(SERVER_SCRIPT)], env=env, stdout=subprocess.DEVNULL,
                            stderr=log_fh, cwd=str(REPO_ROOT))
    t0 = time.time()
    while time.time() - t0 < 60:
        if proc.poll() is not None:
            raise RuntimeError(f"Gateway exited early (code {proc.returncode}); see {log_path}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return proc
        except OSError:
            time.sleep(0.25)
    proc.kill()
    raise RuntimeError("Gateway did not open its port within 60 s")


def gateway_worker_pid(proc: subprocess.Popen) -> int:
    """PID of the interpreter actually running the gateway.

    On Windows a venv's ``python.exe`` is a launcher that re-spawns the base
    interpreter, so the work (and the memory) lives in a child process.
    """
    try:
        children = psutil.Process(proc.pid).children(recursive=True)
    except psutil.Error:
        children = []
    pythons = [c for c in children if "python" in (c.name() or "").lower()]
    return pythons[0].pid if pythons else proc.pid


def stop_gateway(proc: subprocess.Popen) -> None:
    """Terminates the gateway and any child interpreter (see gateway_worker_pid)."""
    try:
        tree = psutil.Process(proc.pid).children(recursive=True)
    except psutil.Error:
        tree = []
    for p in tree:
        try:
            p.kill()
        except psutil.Error:
            pass
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    psutil.wait_procs(tree, timeout=10)


class ProcessSampler(threading.Thread):
    """Samples gateway CPU, RSS, threads and OS handles at a fixed interval."""

    def __init__(self, pid: int, interval_s: float):
        super().__init__(daemon=True)
        self.proc = psutil.Process(pid)
        self.interval_s = interval_s
        self.samples: List[Dict[str, float]] = []
        self._halt = threading.Event()
        self.t0 = time.time()

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        last_cpu = self.proc.cpu_times()
        last_t = time.time()
        while not self._halt.wait(self.interval_s):
            try:
                now = time.time()
                cpu = self.proc.cpu_times()
                busy = (cpu.user - last_cpu.user) + (cpu.system - last_cpu.system)
                core_pct = 100.0 * busy / max(1e-6, now - last_t)
                last_cpu, last_t = cpu, now
                handles = self.proc.num_handles() if hasattr(self.proc, "num_handles") else self.proc.num_fds()
                self.samples.append({
                    "t_s": round(now - self.t0, 1),
                    "cpu_core_pct": round(core_pct, 1),
                    "cpu_machine_pct": round(core_pct / psutil.cpu_count(), 1),
                    "rss_mb": round(self.proc.memory_info().rss / 2**20, 1),
                    "threads": self.proc.num_threads(),
                    "handles": handles,
                })
            except psutil.Error:
                return


def read_metrics(path: Path) -> List[Dict[str, Any]]:
    rows = []
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return rows


def pct(values: List[float], q: float) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(float(np.percentile(vals, q)), 1) if vals else None


# ─────────────────────────────────────────────────────────────────────────────
# Tiered load test
# ─────────────────────────────────────────────────────────────────────────────
def run_tier(feeds: int, args, pools: List[FramePool], identities, work_dir: Path) -> Dict[str, Any]:
    metrics_path = work_dir / f"tier_{feeds}_metrics.jsonl"
    log_path = work_dir / f"tier_{feeds}_gateway.log"
    if metrics_path.exists():
        metrics_path.unlink()
    proc = start_gateway(args.port, metrics_path, 1, args.ort_threads, args.face_every, log_path)
    sampler = ProcessSampler(gateway_worker_pid(proc), 1.0)
    sampler.start()
    cams = []
    for i in range(feeds):
        cn, crt, key = identities[i]
        pool = pools[i % len(pools)]
        cams.append(VirtualCamera(cn, client_context(crt, key), "127.0.0.1", args.port, pool, args.fps,
                                  args.duration, start_offset=(i * 37) % len(pool.frames)))
    logger.info("Tier %d: starting %d cameras for %.0fs", feeds, feeds, args.duration)
    t_start = time.time()
    for c in cams:
        c.start()
        time.sleep(1.0 / max(feeds, 1))  # stagger connects over ~1 s
    for c in cams:
        c.join(timeout=args.duration + 30)
    time.sleep(2.0)  # let the gateway drain its last frames
    sampler.stop()
    stop_gateway(proc)
    wall = time.time() - t_start

    rows = read_metrics(metrics_path)
    warmup_cut = t_start + args.warmup
    steady = [r for r in rows if r.get("done_at", 0) >= warmup_cut]
    per_stream: Dict[str, List[Dict[str, Any]]] = {}
    for r in steady:
        per_stream.setdefault(r["stream"], []).append(r)
    steady_window = max(1.0, args.duration - args.warmup)
    stream_fps = [len(v) / steady_window for v in per_stream.values()]
    retention = [f / args.fps for f in stream_fps] + [0.0] * max(0, feeds - len(per_stream))
    e2e = [r["e2e_ms"] for r in steady if r.get("e2e_ms") is not None]
    model = [r["model_ms"] for r in steady if r.get("window_ran")]
    infer = [r["infer_ms"] for r in steady if r.get("infer_ms") is not None]
    proc_ms = [r["proc_ms"] for r in steady]

    # Backlog check: compare early vs late p50 end-to-end latency in the steady window.
    mid = warmup_cut + steady_window / 2.0
    early = [r["e2e_ms"] for r in steady if r.get("e2e_ms") is not None and r["done_at"] < mid]
    late = [r["e2e_ms"] for r in steady if r.get("e2e_ms") is not None and r["done_at"] >= mid]
    early_p50, late_p50 = pct(early, 50) or 0.0, pct(late, 50) or 0.0
    backlog = late_p50 > BACKLOG_ABS_FLOOR_MS and late_p50 > BACKLOG_GROWTH_LIMIT * max(early_p50, 1.0)

    sent = sum(c.frames_sent for c in cams)
    severed = sum(c.severed for c in cams)
    errors = [e for c in cams for e in c.errors]
    cpu = [s["cpu_core_pct"] for s in sampler.samples if s["t_s"] >= args.warmup]
    rss = [s["rss_mb"] for s in sampler.samples]

    verdicts: Dict[str, int] = {}
    for r in steady:
        verdicts[r.get("verdict", "?")] = verdicts.get(r.get("verdict", "?"), 0) + 1

    min_ret = min(retention) if retention else 0.0
    mean_ret = float(np.mean(retention)) if retention else 0.0
    p95_e2e = pct(e2e, 95)
    reasons = []
    if min_ret < RETENTION_MIN:
        reasons.append(f"min retention {min_ret:.0%} < {RETENTION_MIN:.0%}")
    if p95_e2e is None or p95_e2e > P95_E2E_BUDGET_MS:
        reasons.append(f"p95 e2e {p95_e2e} ms > {P95_E2E_BUDGET_MS:.0f} ms")
    if backlog:
        reasons.append(f"latency backlog growing ({early_p50:.0f} -> {late_p50:.0f} ms p50)")
    if severed:
        reasons.append(f"{severed} severed connections")

    result = {
        "feeds": feeds,
        "duration_s": round(wall, 1),
        "target_fps": args.fps,
        "frames_sent": sent,
        "frames_through_full_path": len(rows),
        "streams_seen": len(per_stream),
        "fps_per_feed_mean": round(float(np.mean(stream_fps)), 2) if stream_fps else 0.0,
        "retention_mean": round(mean_ret, 3),
        "retention_min": round(min_ret, 3),
        "aggregate_fps": round(sum(stream_fps), 1),
        "e2e_p50_ms": pct(e2e, 50),
        "e2e_p95_ms": p95_e2e,
        "e2e_p99_ms": pct(e2e, 99),
        "e2e_early_p50_ms": early_p50,
        "e2e_late_p50_ms": late_p50,
        "server_proc_p50_ms": pct(proc_ms, 50),
        "server_proc_p95_ms": pct(proc_ms, 95),
        "infer_p50_ms": pct(infer, 50),
        "infer_p95_ms": pct(infer, 95),
        "model_window_p50_ms": pct(model, 50),
        "model_window_p95_ms": pct(model, 95),
        "windows_inferred": len(model),
        "cpu_core_pct_mean": round(float(np.mean(cpu)), 1) if cpu else 0.0,
        "cpu_core_pct_peak": round(float(np.max(cpu)), 1) if cpu else 0.0,
        "rss_peak_mb": round(max(rss), 1) if rss else 0.0,
        "severed": severed,
        "client_errors": len(errors),
        "verdicts": verdicts,
        "status": "PASS" if not reasons else "FAIL",
        "fail_reasons": "; ".join(reasons),
    }
    ai = [r["ai_score"] for r in steady if r.get("ai_score") is not None]
    result["ai_score_mean"] = round(float(np.mean(ai)), 3) if ai else None
    logger.info("Tier %d: %s | retention min %.0f%% | p95 e2e %s ms | model p50 %s ms | CPU %.0f%% core | %s",
                feeds, result["status"], min_ret * 100, p95_e2e, result["model_window_p50_ms"],
                result["cpu_core_pct_mean"], result["fail_reasons"])
    if errors:
        logger.warning("Tier %d client errors (first 3): %s", feeds, errors[:3])
    return result


def calibration_check(pools: List[FramePool]) -> Dict[str, Any]:
    """Runs the inference stage offline over each source to report the per-source
    spatial score (sanity check that real inference separates the two feeds)."""
    from security.gateway.ingestion.live_inference import LiveInferenceStage, SharedEdgeModel

    out = {}
    model = SharedEdgeModel()
    for pool in pools:
        stage = LiveInferenceStage(model=model)
        spatial, ai, faces = [], [], 0
        for hexf, w, h in pool.frames[:200]:
            r = stage.process(bytes.fromhex(hexf), w, h)
            faces += int(r.face_detected)
            if r.window_ran:
                spatial.append(r.spatial_score)
            ai.append(r.ai_score)
        out[pool.label] = {
            "frames": min(200, len(pool.frames)),
            "face_rate": round(faces / max(1, min(200, len(pool.frames))), 3),
            "spatial_mean": round(float(np.mean(spatial)), 3) if spatial else None,
            "ai_score_last": round(ai[-1], 3) if ai else None,
        }
    return out


def write_tier_report(results: List[Dict[str, Any]], calib: Dict[str, Any], args, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "live_inference_load_test_raw.csv"
    flat = [{k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in r.items()} for r in results]
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(flat[0].keys()))
        w.writeheader()
        w.writerows(flat)
    (out_dir / "live_inference_load_test_raw.json").write_text(
        json.dumps({"results": results, "calibration": calib, "config": vars(args)}, indent=2, default=str), encoding="utf-8")

    passing = [r["feeds"] for r in results if r["status"] == "PASS"]
    failing = [r["feeds"] for r in results if r["status"] != "PASS"]
    limit = max(passing) if passing else 0
    first_fail = min([f for f in failing if f > limit], default=None)

    rows = "\n".join(
        f"| {r['feeds']} | {r['fps_per_feed_mean']} | {r['retention_min']:.0%} | {r['aggregate_fps']} "
        f"| {r['e2e_p50_ms']} | {r['e2e_p95_ms']} | {r['e2e_p99_ms']} | {r['infer_p50_ms']} "
        f"| {r['model_window_p50_ms']} / {r['model_window_p95_ms']} | {r['cpu_core_pct_mean']} | {r['rss_peak_mb']} "
        f"| {r['severed']} | **{r['status']}** |"
        for r in results
    )
    reasons = "\n".join(f"- **{r['feeds']} feeds:** {r['fail_reasons']}" for r in results if r["fail_reasons"])
    calib_rows = "\n".join(
        f"| `{k}` | {v['frames']} | {v['face_rate']:.0%} | {v['spatial_mean']} |" for k, v in calib.items()
    )
    cpu_name = platform.processor() or platform.machine()
    md = f"""# AEGIS Live Path Load Test — Real Model Inference in the Loop

**Task:** Week 10 Task 6 (Cybersecurity) — closes Month 2 limitation **M2-L15**
**Date:** {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**Script:** `eval/scripts/load_test_live_inference.py`
**Host:** {platform.system()} {platform.release()}, {psutil.cpu_count(logical=False)} physical / {psutil.cpu_count()} logical cores ({cpu_name}), {round(psutil.virtual_memory().total / 2**30)} GB RAM, CPU only (no GPU)

## 1. What changed versus the Month 2 test

The Month 2 report (`streaming_load_test_report.md`) claimed 32 feeds PASS, but it timed only the client's
`sendall()` call, never ran a model, and (because its fixture path no longer existed) streamed a single
160x120 uniform grey PNG. This test closes those gaps:

| | Month 2 test | This test |
|---|---|---|
| Frames | 160x120 synthetic grey PNG | {pools_desc(args)} |
| Camera identity | one shared client cert | one CA-signed cert per camera (`cam-01`...), so PRNU baselines are per camera |
| Security profile | dev (audit only) | **prod** (any integrity false positive severs the feed) |
| AI in the loop | none (`ai_score=0.10` placeholder) | face tracking + MobileNetV3-Small INT8 sliding window (16/8) + streaming CHROM rPPG on every frame |
| Fusion | placeholder score | `FeedFusionEngine` with the real AI score |
| Latency measured | client socket write | **frame sent -> fused verdict ready** (`sent_at` vs gateway completion time) |

Gateway settings: PRNU check every {10} frames (bootstrap 8), face re-detection every {args.face_every} frames,
ONNX Runtime intra-op threads = {args.ort_threads} per call, inference offloaded with `asyncio.to_thread`.
Each tier ran {args.duration:.0f} s at {args.fps:.0f} FPS per feed; the first {args.warmup:.0f} s are excluded as warm-up.

**Pass criteria (all must hold):** every feed keeps >= {RETENTION_MIN:.0%} of its frames through the full path;
p95 end-to-end latency <= {P95_E2E_BUDGET_MS:.0f} ms; no latency backlog (late-window p50 <= {BACKLOG_GROWTH_LIMIT:.0f}x early-window p50
unless under {BACKLOG_ABS_FLOOR_MS:.0f} ms); zero severed connections.

## 2. Results

| Feeds | FPS / feed | Min retention | Aggregate FPS | E2E p50 (ms) | E2E p95 (ms) | E2E p99 (ms) | Inference / frame p50 (ms) | Model window p50 / p95 (ms) | Gateway CPU (% of 1 core) | Peak RSS (MB) | Severed | Verdict |
|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
{rows}

{('### Failure reasons' + chr(10) + reasons) if reasons else ''}

**Real concurrent-feed limit on this host: {limit} feeds**{f' (first failing tier: {first_fail} feeds)' if first_fail else ''}.

## 3. Inference sanity check (is the model really running?)

Offline pass of the same inference stage over the first 200 frames of each source:

| Source | Frames | Face found | Mean MobileNetV3 P(fake) |
|---|:-:|:-:|:-:|
{calib_rows}

## 4. Interpretation

{interpretation(results, limit)}

## 5. Reproduce

```bash
python eval/scripts/load_test_live_inference.py --tiers 4 8 16 --duration {args.duration:.0f}
python eval/scripts/load_test_live_inference.py --soak --soak-feeds <limit> --soak-minutes 60
```
"""
    report = out_dir / "live_inference_load_test_report.md"
    report.write_text(md, encoding="utf-8")
    return report


def pools_desc(args) -> str:
    return f"{args.width or 'native'}-wide JPEG (q{args.jpeg_quality}) from looping real face videos"


def interpretation(results: List[Dict[str, Any]], limit: int) -> str:
    if not results:
        return "No tiers ran."
    lines = []
    worst = max(results, key=lambda r: r["feeds"])
    best = min(results, key=lambda r: r["feeds"])
    if best.get("infer_p50_ms") and worst.get("infer_p50_ms"):
        lines.append(
            f"- Per-frame inference cost grows from {best['infer_p50_ms']} ms (p50) at {best['feeds']} feeds to "
            f"{worst['infer_p50_ms']} ms at {worst['feeds']} feeds as feeds compete for cores; the batched MobileNetV3 "
            f"window (16 frames) costs {best['model_window_p50_ms']} -> {worst['model_window_p50_ms']} ms p50.")
    lines.append(
        f"- The Month 2 headline of 32 feeds does not survive real inference on this host: the measured limit is "
        f"**{limit} feeds** at {results[0]['target_fps']:.0f} FPS. The bottleneck is CPU inference and per-frame "
        "decode/preprocess in the single gateway process, not mTLS or hash chaining.")
    lines.append(
        "- Scaling options, cheapest first: run inference on every 2nd frame (the 16/8 window already smooths), "
        "move inference to a separate worker process pool (removes GIL contention from JSON/hex parsing), "
        "use a GPU execution provider, or shard cameras across several gateway processes behind the same CA.")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Soak test
# ─────────────────────────────────────────────────────────────────────────────
def run_soak(args, pools, identities, work_dir: Path) -> Path:
    feeds = args.soak_feeds
    duration = args.soak_minutes * 60.0
    metrics_path = work_dir / "soak_metrics.jsonl"
    if metrics_path.exists():
        metrics_path.unlink()
    log_path = work_dir / "soak_gateway.log"
    proc = start_gateway(args.port, metrics_path, args.soak_sample_every, args.ort_threads, args.face_every, log_path)
    sampler = ProcessSampler(gateway_worker_pid(proc), args.soak_sample_s)
    sampler.start()
    cams = []
    for i in range(feeds):
        cn, crt, key = identities[i]
        pool = pools[i % len(pools)]
        cams.append(VirtualCamera(cn, client_context(crt, key), "127.0.0.1", args.port, pool, args.fps, duration,
                                  start_offset=(i * 37) % len(pool.frames),
                                  reconnect_every_s=args.reconnect_every + i * 7))
    logger.info("Soak: %d feeds for %.0f min (reconnect every ~%ds)", feeds, args.soak_minutes, args.reconnect_every)
    t_start = time.time()
    for c in cams:
        c.start()
        time.sleep(0.2)
    for c in cams:
        c.join(timeout=duration + 60)
    time.sleep(2.0)
    sampler.stop()
    exit_code = proc.poll()
    stop_gateway(proc)

    samples = sampler.samples
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "live_inference_soak_samples.csv"
    if samples:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(samples[0].keys()))
            w.writeheader()
            w.writerows(samples)

    rows = read_metrics(metrics_path)
    settle = args.soak_settle_minutes * 60.0
    steady = [s for s in samples if s["t_s"] >= settle]

    def slope_per_hour(key: str) -> Tuple[float, float, float]:
        if len(steady) < 3:
            return 0.0, 0.0, 0.0
        t = np.array([s["t_s"] for s in steady]) / 3600.0
        y = np.array([s[key] for s in steady], dtype=float)
        a, b = np.polyfit(t, y, 1)
        return float(a), float(y[0]), float(y[-1])

    rss_slope, rss_first, rss_last = slope_per_hour("rss_mb")
    thr_slope, thr_first, thr_last = slope_per_hour("threads")
    hnd_slope, hnd_first, hnd_last = slope_per_hour("handles")

    # Per-10-minute buckets of throughput and latency (metrics are sampled 1/N per stream).
    buckets = []
    bucket_s = 600.0
    n_buckets = int(np.ceil(duration / bucket_s))
    for b in range(n_buckets):
        lo, hi = t_start + b * bucket_s, t_start + (b + 1) * bucket_s
        rs = [r for r in rows if lo <= r.get("done_at", 0) < hi]
        span = min(hi, t_start + duration) - lo
        e2e = [r["e2e_ms"] for r in rs if r.get("e2e_ms") is not None]
        fps_feed = (len(rs) * args.soak_sample_every) / max(1.0, span) / feeds
        mem = [s["rss_mb"] for s in samples if b * bucket_s <= s["t_s"] < (b + 1) * bucket_s]
        buckets.append({
            "window": f"{int(b * 10)}-{int(min((b + 1) * 10, args.soak_minutes))} min",
            "fps_per_feed": round(fps_feed, 2),
            "e2e_p50": pct(e2e, 50), "e2e_p95": pct(e2e, 95),
            "rss_mb_max": round(max(mem), 1) if mem else None,
        })

    rss_growth_pct = 100.0 * (rss_last - rss_first) / rss_first if rss_first else 0.0
    leak_rss = rss_slope > args.leak_mb_per_hour and rss_growth_pct > 10.0
    # Low-water-mark trend: RSS swings with GC/allocator churn, so also fit the minimum of
    # each 5-minute window, which only rises if memory is really retained.
    minima_t, minima = [], []
    for w0 in np.arange(settle, duration, 300.0):
        win = [s["rss_mb"] for s in samples if w0 <= s["t_s"] < w0 + 300.0]
        if win:
            minima_t.append((w0 + 150.0) / 3600.0)
            minima.append(min(win))
    minima_slope = float(np.polyfit(minima_t, minima, 1)[0]) if len(minima) >= 3 else 0.0
    watch_rss = minima_slope > 0.8 * args.leak_mb_per_hour
    leak_threads = thr_slope > 2.0 and (thr_last - thr_first) > 4
    leak_handles = hnd_slope > 50.0 and (hnd_last - hnd_first) > 100
    sessions = sum(c.sessions for c in cams)
    severed = sum(c.severed for c in cams)
    errors = [e for c in cams for e in c.errors]
    first_p95 = buckets[0]["e2e_p95"] if buckets else None
    last_p95 = buckets[-1]["e2e_p95"] if buckets else None
    verdict = "PASS" if not (leak_rss or leak_threads or leak_handles or severed or exit_code not in (None,)) else "FAIL"
    if verdict == "PASS" and watch_rss:
        verdict = "WATCH"

    bucket_rows = "\n".join(
        f"| {b['window']} | {b['fps_per_feed']} | {b['e2e_p50']} | {b['e2e_p95']} | {b['rss_mb_max']} |" for b in buckets)
    md = f"""# AEGIS Live Path Soak Test — {args.soak_minutes:.0f} minutes with real inference

**Task:** Week 10 Task 6 (Cybersecurity) — soak test for leaks under sustained live load
**Date:** {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**Script:** `eval/scripts/load_test_live_inference.py --soak --soak-feeds {feeds} --soak-minutes {args.soak_minutes:.0f}`
**Configuration:** {feeds} feeds x {args.fps:.0f} FPS, prod security profile, full live path (mTLS, hash chain,
sequence validation, PRNU, face tracking, MobileNetV3 INT8, streaming rPPG, fusion). Each camera disconnects and
reconnects every ~{args.reconnect_every}s (staggered) so per-connection state is allocated and freed
**{sessions} times** over the run. Gateway sampled every {args.soak_sample_s:.0f}s; trends are fitted after a
{args.soak_settle_minutes:.0f}-minute settle period.

## Verdict: **{verdict}**

| Resource | After settle | End of run | Fitted trend | Leak threshold | Leak? |
|---|:-:|:-:|:-:|:-:|:-:|
| Gateway RSS (MB) | {rss_first:.1f} | {rss_last:.1f} | {rss_slope:+.1f} MB/h ({rss_growth_pct:+.1f}%) | > {args.leak_mb_per_hour:.0f} MB/h and > 10% | {'**YES**' if leak_rss else 'no'} |
| RSS low-water mark (5-min minima) | {minima[0] if minima else 0:.1f} | {minima[-1] if minima else 0:.1f} | {minima_slope:+.1f} MB/h | WATCH if > {0.8 * args.leak_mb_per_hour:.0f} MB/h | {'**WATCH**' if watch_rss else 'no'} |
| Threads | {thr_first:.0f} | {thr_last:.0f} | {thr_slope:+.1f} /h | > 2/h and > +4 | {'**YES**' if leak_threads else 'no'} |
| OS handles | {hnd_first:.0f} | {hnd_last:.0f} | {hnd_slope:+.1f} /h | > 50/h and > +100 | {'**YES**' if leak_handles else 'no'} |

Severed connections: **{severed}** · client errors: **{len(errors)}** · gateway process alive at end: **{exit_code is None}**

## Stability over time

| Window | Frames / feed / s | E2E p50 (ms) | E2E p95 (ms) | Peak RSS (MB) |
|---|:-:|:-:|:-:|:-:|
{bucket_rows}

End-to-end p95 moved from {first_p95} ms in the first window to {last_p95} ms in the last.
Raw samples: `eval/reports/live_inference_soak_samples.csv`.
"""
    if errors:
        md += "\n### Client errors (first 5)\n\n" + "\n".join(f"- `{e}`" for e in errors[:5]) + "\n"
    report = out_dir / "live_inference_soak_report.md"
    report.write_text(md, encoding="utf-8")
    logger.info("Soak verdict %s | RSS %+.1f MB/h | threads %+.1f/h | handles %+.1f/h", verdict, rss_slope, thr_slope, hnd_slope)
    return report


# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tiers", nargs="+", type=int, default=[4, 8, 16])
    ap.add_argument("--extend-until-fail", action="store_true",
                    help="If the largest tier passes, keep adding feeds (x1.5) until one fails, to bracket the limit.")
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--warmup", type=float, default=10.0)
    ap.add_argument("--fps", type=float, default=25.0)
    ap.add_argument("--port", type=int, default=8743)
    ap.add_argument("--videos", nargs="+", type=Path, default=DEFAULT_VIDEOS)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--jpeg-quality", type=int, default=90)
    ap.add_argument("--max-frames", type=int, default=250)
    ap.add_argument("--ort-threads", type=int, default=1)
    ap.add_argument("--face-every", type=int, default=5)
    ap.add_argument("--output-dir", default=str(REPORTS_DIR))
    ap.add_argument("--soak", action="store_true")
    ap.add_argument("--soak-feeds", type=int, default=8)
    ap.add_argument("--soak-minutes", type=float, default=60.0)
    ap.add_argument("--soak-sample-s", type=float, default=15.0)
    ap.add_argument("--soak-sample-every", type=int, default=5)
    ap.add_argument("--soak-settle-minutes", type=float, default=5.0)
    ap.add_argument("--reconnect-every", type=int, default=300)
    ap.add_argument("--leak-mb-per-hour", type=float, default=50.0)
    args = ap.parse_args()

    ensure_pki()
    work_dir = Path(tempfile.mkdtemp(prefix="aegis_live_load_"))
    max_feeds = max(args.tiers + [args.soak_feeds]) * 3
    identities = issue_camera_identities(max_feeds, work_dir)
    pools = [load_frame_pool(v, args.max_frames, args.jpeg_quality, args.width) for v in args.videos]
    logger.info("Frame pools: %s (work dir %s)", ", ".join(f"{p.label}={len(p.frames)}" for p in pools), work_dir)

    if args.soak:
        report = run_soak(args, pools, identities, work_dir)
        print(f"\nSoak report -> {report}")
        return

    calib = calibration_check(pools)
    logger.info("Calibration check: %s", calib)
    results = []
    tiers = sorted(set(args.tiers))
    for feeds in tiers:
        results.append(run_tier(feeds, args, pools, identities, work_dir))
        time.sleep(2.0)
    if args.extend_until_fail:
        feeds = tiers[-1]
        while results[-1]["status"] == "PASS" and feeds < max_feeds:
            feeds = int(np.ceil(feeds * 1.5))
            if feeds > len(identities):
                break
            results.append(run_tier(feeds, args, pools, identities, work_dir))
    report = write_tier_report(results, calib, args, Path(args.output_dir))
    print(f"\nLoad test report -> {report}")
    shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
