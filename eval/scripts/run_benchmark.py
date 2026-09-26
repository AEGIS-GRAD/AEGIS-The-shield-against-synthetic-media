"""
Full-Pipeline Benchmark Runner — AEGIS Month 1 Baseline
========================================================
Calls the orchestrator's /orchestrate endpoint for every sample in
eval/data/eval_manifest.csv, records results, and writes:
  - eval/reports/week_benchmark_raw.csv     (one row per sample run)
  - eval/reports/week_benchmark_report.md   (aggregated metric report)

Usage:
    python eval/scripts/run_benchmark.py [--orchestrator-url URL] [--manifest PATH]

Defaults:
    --orchestrator-url  http://localhost:8000   (orchestrator service in docker-compose)
    --manifest          eval/data/eval_manifest.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


# ─── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = BASE_DIR / "eval"
DATA_DIR = EVAL_DIR / "data"
REPORTS_DIR = EVAL_DIR / "reports"
DEFAULT_MANIFEST = DATA_DIR / "eval_manifest.csv"
RAW_CSV_PATH = REPORTS_DIR / "week_benchmark_raw.csv"
REPORT_MD_PATH = REPORTS_DIR / "week_benchmark_report.md"


# ─── Schema ─────────────────────────────────────────────────────────────────
RAW_FIELDNAMES = [
    "sample_path",
    "modality",
    "true_label",
    "final_verdict",
    "final_score",
    "correct",
    "detectors_called",
    "e2e_latency_ms",
    # per-detector columns (filled in if that detector ran)
    "det_video_classifier_confidence",
    "det_video_classifier_verdict",
    "det_video_classifier_latency_ms",
    "det_rppg_confidence",
    "det_rppg_verdict",
    "det_rppg_latency_ms",
    "det_aasist_confidence",
    "det_aasist_verdict",
    "det_aasist_latency_ms",
    "det_syncnet_confidence",
    "det_syncnet_verdict",
    "det_syncnet_latency_ms",
    "error",
]


# ─── Helpers ────────────────────────────────────────────────────────────────

def verdict_to_label(verdict: str) -> str:
    """Map orchestrator verdict strings to 'fake' or 'real'."""
    v = (verdict or "").upper()
    if v == "SYNTHETIC":
        return "fake"
    if v == "AUTHENTIC":
        return "real"
    # UNCERTAIN / NO_RESULTS treated as 'real' for recall purposes
    return "real"


def call_orchestrate(
    orchestrator_url: str,
    sample_path: Path,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """POST /orchestrate with a media file upload. Returns parsed JSON."""
    with open(sample_path, "rb") as fh:
        resp = requests.post(
            f"{orchestrator_url}/orchestrate",
            files={"file": (sample_path.name, fh)},
            timeout=timeout,
        )
    resp.raise_for_status()
    return resp.json()


def extract_per_detector(raw_results: List[Dict], detector_name: str) -> Dict[str, Any]:
    """Extract confidence, verdict, latency from a named detector's result entry."""
    for r in raw_results:
        if r.get("detector") == detector_name and r.get("status") == "ok":
            conf = r.get("confidence")
            # map to label
            verdict_label = "fake" if (conf is not None and conf > 0.5) else "real"
            return {
                "confidence": conf,
                "verdict": verdict_label,
                "latency_ms": r.get("latency_ms"),
            }
    return {"confidence": None, "verdict": None, "latency_ms": None}


# ─── Main benchmark loop ─────────────────────────────────────────────────────

def run_benchmark(
    orchestrator_url: str,
    manifest_path: Path,
) -> None:
    print(f"Loading manifest from: {manifest_path}")
    manifest_rows: List[Dict[str, str]] = []
    with open(manifest_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            manifest_rows.append(row)

    total = len(manifest_rows)
    print(f"Manifest contains {total} samples — calling {orchestrator_url}/orchestrate for each.")

    os.makedirs(REPORTS_DIR, exist_ok=True)
    raw_rows: List[Dict] = []

    # ── per-call loop ────────────────────────────────────────────────────────
    for idx, row in enumerate(manifest_rows, start=1):
        rel_path = row["sample_path"]
        modality = row["modality"]
        true_label = row["true_label"]

        abs_path = BASE_DIR / rel_path
        if not abs_path.exists():
            print(f"  [{idx}/{total}] SKIP (file not found): {rel_path}")
            raw_rows.append({
                "sample_path": rel_path,
                "modality": modality,
                "true_label": true_label,
                "error": "file_not_found",
                **{f: None for f in RAW_FIELDNAMES if f not in ("sample_path", "modality", "true_label", "error")},
            })
            continue

        t0 = time.perf_counter()
        try:
            resp_json = call_orchestrate(orchestrator_url, abs_path)
            e2e_latency_ms = int((time.perf_counter() - t0) * 1000)
        except Exception as exc:
            e2e_latency_ms = int((time.perf_counter() - t0) * 1000)
            print(f"  [{idx}/{total}] ERROR on {rel_path}: {exc}")
            raw_rows.append({
                "sample_path": rel_path,
                "modality": modality,
                "true_label": true_label,
                "e2e_latency_ms": e2e_latency_ms,
                "error": str(exc)[:120],
                **{f: None for f in RAW_FIELDNAMES if f not in (
                    "sample_path", "modality", "true_label", "e2e_latency_ms", "error"
                )},
            })
            continue

        # parse response
        final_verdict = resp_json.get("aggregated_verdict", "UNKNOWN")
        final_score = resp_json.get("aggregated_score")
        detectors_called = ",".join(resp_json.get("detectors_called", []))
        raw_results = resp_json.get("raw_results", [])

        predicted_label = verdict_to_label(final_verdict)
        correct = int(predicted_label == true_label)

        # per-detector breakdown
        det_vc = extract_per_detector(raw_results, "video-classifier")
        det_rp = extract_per_detector(raw_results, "rppg")
        det_aa = extract_per_detector(raw_results, "aasist")
        det_sn = extract_per_detector(raw_results, "syncnet")

        raw_rows.append({
            "sample_path": rel_path,
            "modality": modality,
            "true_label": true_label,
            "final_verdict": final_verdict,
            "final_score": final_score,
            "correct": correct,
            "detectors_called": detectors_called,
            "e2e_latency_ms": e2e_latency_ms,
            "det_video_classifier_confidence": det_vc["confidence"],
            "det_video_classifier_verdict": det_vc["verdict"],
            "det_video_classifier_latency_ms": det_vc["latency_ms"],
            "det_rppg_confidence": det_rp["confidence"],
            "det_rppg_verdict": det_rp["verdict"],
            "det_rppg_latency_ms": det_rp["latency_ms"],
            "det_aasist_confidence": det_aa["confidence"],
            "det_aasist_verdict": det_aa["verdict"],
            "det_aasist_latency_ms": det_aa["latency_ms"],
            "det_syncnet_confidence": det_sn["confidence"],
            "det_syncnet_verdict": det_sn["verdict"],
            "det_syncnet_latency_ms": det_sn["latency_ms"],
            "error": None,
        })

        status_icon = "[OK]" if correct else "[FAIL]"
        print(f"  [{idx}/{total}] {status_icon} {Path(rel_path).name} -> {final_verdict} "
              f"(true={true_label}) [{e2e_latency_ms}ms]")

    # ── Write raw CSV ────────────────────────────────────────────────────────
    with open(RAW_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(raw_rows)
    print(f"\n[OK] Raw results written to {RAW_CSV_PATH}")

    # ── Compute metrics & write report ───────────────────────────────────────
    generate_report(raw_rows)


# ─── Metrics + Report generation ────────────────────────────────────────────

def _safe_div(n: float, d: float, default: float = 0.0) -> float:
    return n / d if d else default


def compute_accuracy_for_rows(rows: List[Dict]) -> Dict[str, Any]:
    """Returns accuracy metrics for a set of result rows (only completed calls)."""
    done = [r for r in rows if not r.get("error") and r.get("correct") is not None]
    if not done:
        return {"n": 0, "correct": 0, "accuracy": None}
    n_correct = sum(int(r["correct"]) for r in done)
    return {"n": len(done), "correct": n_correct, "accuracy": round(n_correct / len(done), 4)}


def compute_latency_stats(values: List[Optional[float]]) -> Dict[str, Optional[float]]:
    """Mean, median, p95 from a list of latency values (ms), ignoring None."""
    import statistics
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return {"mean": None, "median": None, "p95": None}
    p95_idx = max(0, int(len(vals) * 0.95) - 1)
    return {
        "mean": round(statistics.mean(vals), 1),
        "median": round(statistics.median(vals), 1),
        "p95": round(vals[p95_idx], 1),
    }


def generate_report(raw_rows: List[Dict]) -> None:
    """Compute all metrics and write the Markdown report."""

    # Separate completed vs failed rows
    done_rows = [r for r in raw_rows if not r.get("error") and r.get("correct") is not None]
    failed_rows = [r for r in raw_rows if bool(r.get("error"))]
    total = len(raw_rows)
    n_done = len(done_rows)
    n_failed = len(failed_rows)

    # ── Overall accuracy ─────────────────────────────────────────────────────
    overall = compute_accuracy_for_rows(done_rows)

    # ── E2E latency ──────────────────────────────────────────────────────────
    e2e_latencies = [r.get("e2e_latency_ms") for r in done_rows]
    e2e_stats = compute_latency_stats(e2e_latencies)

    # ── Per-detector stats ───────────────────────────────────────────────────
    detector_map = {
        "video-classifier": ("det_video_classifier_confidence", "det_video_classifier_verdict", "det_video_classifier_latency_ms"),
        "rppg": ("det_rppg_confidence", "det_rppg_verdict", "det_rppg_latency_ms"),
        "aasist": ("det_aasist_confidence", "det_aasist_verdict", "det_aasist_latency_ms"),
        "syncnet": ("det_syncnet_confidence", "det_syncnet_verdict", "det_syncnet_latency_ms"),
    }

    det_stats: Dict[str, Dict] = {}
    for det_name, (conf_col, verd_col, lat_col) in detector_map.items():
        # Rows where this detector was actually called (has a confidence value)
        called_rows = [r for r in done_rows if r.get(conf_col) is not None]
        if not called_rows:
            det_stats[det_name] = {"called": 0, "accuracy": None, "mean_latency_ms": None,
                                   "pipeline_agree_rate": None, "latency_stats": {}}
            continue

        # Per-detector individual accuracy
        det_correct = sum(
            1 for r in called_rows
            if r.get(verd_col) == r.get("true_label")
        )
        det_accuracy = round(det_correct / len(called_rows), 4)

        # How often detector verdict agreed with final pipeline verdict
        pipeline_map = {"SYNTHETIC": "fake", "AUTHENTIC": "real", "UNCERTAIN": "real", "NO_RESULTS": "real"}
        agree = sum(
            1 for r in called_rows
            if r.get(verd_col) == pipeline_map.get((r.get("final_verdict") or "").upper(), "real")
        )
        agree_rate = round(agree / len(called_rows), 4)

        latencies = [r.get(lat_col) for r in called_rows]
        det_stats[det_name] = {
            "called": len(called_rows),
            "accuracy": det_accuracy,
            "pipeline_agree_rate": agree_rate,
            "latency_stats": compute_latency_stats(latencies),
        }

    # ── Build Markdown ────────────────────────────────────────────────────────
    lines: List[str] = []
    lines += [
        "# AEGIS Week 1 Full-Pipeline Benchmark Report",
        "",
        "> **This is the Month 1 baseline that Month 2's agentic orchestrator must be compared against.**",
        "",
        "---",
        "",
        "## Overview",
        "",
        f"| Parameter | Value |",
        f"|---|---|",
        f"| Total samples in manifest | {total} |",
        f"| Completed runs | {n_done} |",
        f"| Failed / skipped runs | {n_failed} |",
        f"| Target (≥ 100 runs) | {'✅ Met' if n_done >= 100 else '❌ Not met'} |",
        "",
    ]

    # Overall accuracy
    acc_str = f"{overall['accuracy']:.4f}" if overall['accuracy'] is not None else "N/A"
    lines += [
        "## Overall End-to-End Accuracy",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Samples evaluated | {overall['n']} |",
        f"| Correct verdicts | {overall['correct']} |",
        f"| **Overall accuracy** | **{acc_str}** |",
        "",
    ]

    # E2E latency
    lines += [
        "## End-to-End Latency (per sample)",
        "",
        "| Statistic | Latency (ms) |",
        "|---|---|",
        f"| Mean | {e2e_stats['mean'] or 'N/A'} |",
        f"| Median | {e2e_stats['median'] or 'N/A'} |",
        f"| P95 | {e2e_stats['p95'] or 'N/A'} |",
        "",
    ]

    # Per-detector table
    lines += [
        "## Per-Detector Contribution",
        "",
        "Individual accuracy = fraction of samples *where that detector ran* where its own verdict matched `true_label`.",
        "Pipeline agreement = fraction of those samples where the detector's verdict matched the final pipeline verdict.",
        "",
        "| Detector | Times Called | Individual Accuracy | Pipeline Agreement | Mean Latency (ms) | Median Latency (ms) | P95 Latency (ms) |",
        "|---|---|---|---|---|---|---|",
    ]
    for det_name, s in det_stats.items():
        ia = f"{s['accuracy']:.4f}" if s["accuracy"] is not None else "—"
        pa = f"{s['pipeline_agree_rate']:.4f}" if s["pipeline_agree_rate"] is not None else "—"
        ls = s.get("latency_stats", {})
        lmean = ls.get("mean") or "—"
        lmed = ls.get("median") or "—"
        lp95 = ls.get("p95") or "—"
        lines.append(f"| {det_name} | {s['called']} | {ia} | {pa} | {lmean} | {lmed} | {lp95} |")

    lines += [
        "",
        "---",
        "",
        "## Notes",
        "",
        "- Aggregation method: **weighted average** (video-classifier ×1.5, rppg ×1.2, syncnet ×1.2, aasist ×1.0).",
        "  This is a placeholder heuristic — see `orchestrator/app/aggregate.py` for detail.",
        "- Verdict thresholds: score ≥ 0.65 → SYNTHETIC, score ≤ 0.35 → AUTHENTIC, between → UNCERTAIN.",
        "- UNCERTAIN and NO_RESULTS verdicts are treated as 'real' (authentic) for accuracy calculation purposes.",
        "- Raw per-sample data: `eval/reports/week_benchmark_raw.csv`.",
        "- Manifest: `eval/data/eval_manifest.csv`.",
        "",
    ]

    report_text = "\n".join(lines) + "\n"

    with open(REPORT_MD_PATH, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"[OK] Report written to {REPORT_MD_PATH}")
    print(f"\n{'='*60}")
    print(f"  BENCHMARK COMPLETE")
    print(f"  Completed: {n_done}/{total}  Failed: {n_failed}")
    print(f"  Overall accuracy: {acc_str}")
    if e2e_stats['median']:
        print(f"  Median E2E latency: {e2e_stats['median']} ms")
    print(f"{'='*60}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AEGIS full-pipeline benchmark runner.")
    parser.add_argument(
        "--orchestrator-url",
        default=os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000"),
        help="Base URL of the orchestrator service (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help=f"Path to eval_manifest.csv (default: {DEFAULT_MANIFEST}).",
    )
    args = parser.parse_args()

    run_benchmark(
        orchestrator_url=args.orchestrator_url.rstrip("/"),
        manifest_path=Path(args.manifest),
    )
