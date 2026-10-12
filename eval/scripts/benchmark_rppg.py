#!/usr/bin/env python3
"""
benchmark_rppg.py
-----------------
Standalone benchmark script for the classical rPPG (Remote Photoplethysmography) detector.
Direct execution — no Docker, no microservices, no HTTP.

Evaluates against the FaceForensics++ video subset:
  - eval/data/video_subset/real/ (150 genuine face videos)
  - eval/data/video_subset/fake/ (150 manipulated face videos)

Usage:
    # Run full balanced benchmark (150 real / 150 fake):
    python eval/scripts/benchmark_rppg.py

    # Quick sanity check (10 samples per class):
    python eval/scripts/benchmark_rppg.py --limit 10

    # Save results to JSON:
    python eval/scripts/benchmark_rppg.py --out eval/reports/rppg_benchmark.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

# Repo paths
REPO_ROOT = Path(__file__).resolve().parents[2]
RPPG_DIR = REPO_ROOT / "detectors" / "rppg"
VIDEO_SUBSET_FAKE = REPO_ROOT / "eval" / "data" / "video_subset" / "fake"
VIDEO_SUBSET_REAL = REPO_ROOT / "eval" / "data" / "video_subset" / "real"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("benchmark_rppg")


def compute_metrics(scores: List[float], labels: List[int]) -> dict:
    from sklearn.metrics import accuracy_score, confusion_matrix, roc_auc_score, roc_curve

    arr_s = np.array(scores)
    arr_l = np.array(labels)
    preds = (arr_s >= 0.5).astype(int)
    acc = accuracy_score(arr_l, preds)

    auc = eer = float("nan")
    try:
        auc = roc_auc_score(arr_l, arr_s)
        fpr, tpr, _ = roc_curve(arr_l, arr_s)
        fnr = 1 - tpr
        idx = np.nanargmin(np.abs(fnr - fpr))
        eer = (fpr[idx] + fnr[idx]) / 2.0
    except Exception:
        pass

    cm = confusion_matrix(arr_l, preds, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0, 0, 0, 0)

    fake_mask = arr_l == 1
    real_mask = arr_l == 0
    fake_acc = accuracy_score(arr_l[fake_mask], preds[fake_mask]) if fake_mask.any() else float("nan")
    real_acc = accuracy_score(arr_l[real_mask], preds[real_mask]) if real_mask.any() else float("nan")

    return {
        "n_total": len(labels),
        "n_real": int(real_mask.sum()),
        "n_fake": int(fake_mask.sum()),
        "accuracy": float(acc),
        "auc": float(auc),
        "eer": float(eer),
        "real_acc": float(real_acc),
        "fake_acc": float(fake_acc),
        "confusion_matrix": {"TN": int(tn), "FP": int(fp), "FN": int(fn), "TP": int(tp)},
    }


def collect_videos(limit: int | None) -> Tuple[List[Path], List[Path]]:
    exts = {".mp4", ".avi", ".mov", ".mkv"}
    real_files = sorted(p for p in VIDEO_SUBSET_REAL.iterdir() if p.suffix.lower() in exts)
    fake_files = sorted(p for p in VIDEO_SUBSET_FAKE.iterdir() if p.suffix.lower() in exts)
    if limit:
        real_files = real_files[:limit]
        fake_files = fake_files[:limit]
    return real_files, fake_files


def main():
    parser = argparse.ArgumentParser(description="rPPG Pulse-Consistency Benchmark")
    parser.add_argument("--limit", type=int, default=None, help="Limit samples per class for quick testing")
    parser.add_argument("--out", type=str, default=None, help="Path to output JSON")
    args = parser.parse_args()

    # Import rPPG detector pipeline directly
    sys.path.insert(0, str(RPPG_DIR))
    from preprocess import RppgPreprocessor
    from rppg_extract import estimate_heart_rate, extract_pulse_signal, signal_quality_score

    preprocessor = RppgPreprocessor()
    real_files, fake_files = collect_videos(args.limit)

    logger.info(f"Loaded dataset: {len(real_files)} real and {len(fake_files)} fake videos.")

    scores, labels = [], []
    bpm_list = []
    guardrail_count = 0
    t_start = time.perf_counter()

    for label_val, file_list, tag in [(0, real_files, "REAL"), (1, fake_files, "FAKE")]:
        for vpath in file_list:
            t0 = time.perf_counter()
            try:
                rgb_signals, fps, meta = preprocessor.preprocess_video(str(vpath))
                if meta.get("guardrail_triggered", False):
                    guardrail_count += 1
                    # Inconclusive/fallback score
                    score = 0.5
                    bpm = 0.0
                else:
                    lum_factor = meta.get("luminance_confidence_factor", 1.0)
                    pulse = extract_pulse_signal(rgb_signals, fps, denoise=(lum_factor < 1.0))
                    try:
                        bpm = estimate_heart_rate(pulse, fps)
                    except Exception:
                        bpm = 60.0
                    quality = signal_quality_score(pulse, fps=fps)
                    score = float(np.clip(1.0 - quality, 0.0, 1.0))
                    bpm_list.append(bpm)

                elapsed = (time.perf_counter() - t0) * 1000
                verdict = "FAKE" if score >= 0.5 else "REAL"
                ok = "[OK]" if (verdict == "FAKE") == (label_val == 1) else "[FAIL]"
                print(
                    f"  {ok} [{tag}] {vpath.name:<24s}  score={score:.4f}  bpm={bpm:5.1f}  {elapsed:5.0f}ms"
                )

                scores.append(score)
                labels.append(label_val)
            except Exception as exc:
                logger.error(f"Error processing {vpath.name}: {exc}")

    total_time = time.perf_counter() - t_start
    m = compute_metrics(scores, labels)

    print("\n" + "=" * 62)
    print("  rPPG CHROM DETECTOR BENCHMARK RESULTS")
    print("=" * 62)
    print(f"  Total Evaluated : {m['n_total']} videos ({total_time:.1f}s, {total_time/max(m['n_total'],1):.2f}s/video)")
    print(f"  Guardrails Trig.: {guardrail_count}")
    if bpm_list:
        print(f"  Mean Pulse BPM  : {np.mean(bpm_list):.1f} BPM (min={np.min(bpm_list):.1f}, max={np.max(bpm_list):.1f})")
    print(f"  Accuracy        : {m['accuracy'] * 100:.2f}%")
    print(f"  Real Accuracy   : {m['real_acc'] * 100:.2f}%  (TN={m['confusion_matrix']['TN']}, FP={m['confusion_matrix']['FP']})")
    print(f"  Fake Accuracy   : {m['fake_acc'] * 100:.2f}%  (TP={m['confusion_matrix']['TP']}, FN={m['confusion_matrix']['FN']})")
    print(f"  AUC Score       : {m['auc']:.4f}")
    print("=" * 62)

    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2)
        print(f"Saved results JSON to: {out_p}")


if __name__ == "__main__":
    main()
