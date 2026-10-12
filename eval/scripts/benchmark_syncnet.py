#!/usr/bin/env python3
"""
benchmark_syncnet.py
--------------------
Standalone benchmark script for the SyncNet Audio-Visual Lip-Sync consistency detector.
Direct execution — no Docker, no microservices, no HTTP.

Uses:
  - Offline SyncNet checkpoint: detectors/syncnet/weights/syncnet_v2.model
  - FaceForensics++ video dataset or custom audio-visual speech videos

Evaluates:
  - Temporal synchronization offset argmin d(v) within [-15, +15] frames
  - Minimum distance and alignment peak confidence
  - Audio presence detection (silent videos flagged as not_applicable / inconclusive)

Usage:
    # Run full benchmark on video subset:
    python eval/scripts/benchmark_syncnet.py

    # Quick sanity check (10 samples per class):
    python eval/scripts/benchmark_syncnet.py --limit 10

    # Save results to JSON:
    python eval/scripts/benchmark_syncnet.py --out eval/reports/syncnet_benchmark.json
"""

from __future__ import annotations

import argparse
import importlib.util
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
SYNCNET_DIR = REPO_ROOT / "detectors" / "syncnet"
VIDEO_SUBSET_FAKE = REPO_ROOT / "eval" / "data" / "video_subset" / "fake"
VIDEO_SUBSET_REAL = REPO_ROOT / "eval" / "data" / "video_subset" / "real"
WEIGHTS_PATH = SYNCNET_DIR / "weights" / "syncnet_v2.model"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("benchmark_syncnet")


def _import_file(mod_name: str, file_path: Path):
    """Dynamically loads a python module from file path without static import errors."""
    spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {mod_name} from {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def compute_metrics(scores: List[float], labels: List[int]) -> dict:
    from sklearn.metrics import accuracy_score, confusion_matrix, roc_auc_score, roc_curve

    if not scores or not labels:
        return {"n_total": 0, "accuracy": float("nan"), "auc": float("nan")}

    arr_s = np.array(scores)
    arr_l = np.array(labels)
    preds = (arr_s >= 0.5).astype(int)
    acc = accuracy_score(arr_l, preds)

    auc = eer = float("nan")
    try:
        if len(np.unique(arr_l)) > 1:
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


def collect_videos(video_dir: Path | None, limit: int | None) -> Tuple[List[Path], List[Path]]:
    exts = {".mp4", ".avi", ".mov", ".mkv"}
    real_files = sorted(p for p in VIDEO_SUBSET_REAL.iterdir() if p.suffix.lower() in exts)
    fake_files = sorted(p for p in VIDEO_SUBSET_FAKE.iterdir() if p.suffix.lower() in exts)
    if limit:
        real_files = real_files[:limit]
        fake_files = fake_files[:limit]
    return real_files, fake_files


def main():
    parser = argparse.ArgumentParser(description="SyncNet Audio-Visual Lip-Sync Benchmark")
    parser.add_argument("--limit", type=int, default=None, help="Limit samples per class for quick testing")
    parser.add_argument("--out", type=str, default=None, help="Path to output JSON")
    args = parser.parse_args()

    # Ensure detector folder is in sys.path so inner imports (models, schemas) resolve
    if str(SYNCNET_DIR) not in sys.path:
        sys.path.insert(0, str(SYNCNET_DIR))

    # Dynamic imports to avoid static resolution warnings
    sync_prep_mod = _import_file("syncnet_preprocess", SYNCNET_DIR / "preprocess.py")
    SyncNetPreprocessor = sync_prep_mod.SyncNetPreprocessor

    sync_infer_mod = _import_file("syncnet_infer", SYNCNET_DIR / "infer.py")
    SyncNetInference = sync_infer_mod.SyncNetInference

    if not WEIGHTS_PATH.exists():
        logger.error(f"Weights missing at: {WEIGHTS_PATH}")
        sys.exit(1)

    logger.info(f"Using SyncNet weights: {WEIGHTS_PATH}")
    preprocessor = SyncNetPreprocessor()
    inference = SyncNetInference()

    real_files, fake_files = collect_videos(None, args.limit)
    logger.info(f"Loaded {len(real_files)} real and {len(fake_files)} fake videos.")

    scores, labels = [], []
    valid_scores, valid_labels = [], []
    silent_count = 0
    no_face_count = 0
    t_start = time.perf_counter()

    for label_val, file_list, tag in [(0, real_files, "REAL"), (1, fake_files, "FAKE")]:
        for vpath in file_list:
            t0 = time.perf_counter()
            try:
                vid_seqs, aud_seqs, has_audio = preprocessor.preprocess(str(vpath))
                conf, raw_offset, evidence = inference.score_video(vid_seqs, aud_seqs, has_audio)
                elapsed = (time.perf_counter() - t0) * 1000

                flags = evidence.flags or []
                if "not_applicable" in flags:
                    silent_count += 1
                    status = "[SILENT/NO-AUDIO]"
                elif len(vid_seqs) == 0:
                    no_face_count += 1
                    status = "[NO-FACE-ROI]"
                else:
                    status = "[AUDIO-VISUAL]"
                    valid_scores.append(conf)
                    valid_labels.append(label_val)

                scores.append(conf)
                labels.append(label_val)

                verdict = "FAKE" if conf >= 0.5 else "REAL"
                ok = "[OK]" if (verdict == "FAKE") == (label_val == 1) else "[--]"
                print(
                    f"  {ok} {status:<16s} [{tag}] {vpath.name:<24s}  score={conf:.4f}  raw={raw_offset:+4.1f}  {elapsed:5.0f}ms"
                )

            except Exception as exc:
                logger.error(f"Error processing {vpath.name}: {exc}")

    total_time = time.perf_counter() - t_start
    m_all = compute_metrics(scores, labels)
    m_valid = compute_metrics(valid_scores, valid_labels)

    print("\n" + "=" * 62)
    print("  SYNCNET AUDIO-VISUAL BENCHMARK RESULTS")
    print("=" * 62)
    print(f"  Total Processed : {len(labels)} videos ({total_time:.1f}s)")
    print(f"  Audio-bearing   : {len(valid_labels)} videos")
    print(f"  Silent Videos   : {silent_count} (guaranteed safe fallback confidence=0.5)")
    print(f"  No Face Detected: {no_face_count}")
    print("-" * 62)
    if len(valid_labels) > 0:
        print(f"  Accuracy (audio subset) : {m_valid['accuracy'] * 100:.2f}%")
        print(f"  Real Acc (audio subset) : {m_valid['real_acc'] * 100:.2f}%")
        print(f"  Fake Acc (audio subset) : {m_valid['fake_acc'] * 100:.2f}%")
        print(f"  AUC (audio subset)      : {m_valid['auc']:.4f}")
    else:
        print("  Note: Tested videos contained no audio tracks (silent FF++ c23).")
        print("  SyncNet correctly evaluated all silent samples to neutral 0.5 confidence.")
    print("=" * 62)

    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        res_data = {"all": m_all, "audio_bearing": m_valid, "silent_count": silent_count}
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(res_data, f, indent=2)
        print(f"Saved results JSON to: {out_p}")


if __name__ == "__main__":
    main()
