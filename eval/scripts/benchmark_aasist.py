#!/usr/bin/env python3
"""
benchmark_aasist.py
-------------------
Standalone benchmark script for AASIST (Audio Anti-Spoofing using Integrated Spectro-Temporal Graph Attention).
Direct execution — no Docker, no microservices, no HTTP.

Evaluates against:
  1. Default: Balanced subset in eval/data/audio_subset (150 real, 150 fake from ASVspoof 2019 LA)
  2. Optional: Direct ASVspoof 2019 LA evaluation split (D:\\LA\\LA\\) using protocol file

Usage:
    # Run on balanced 300-sample subset (150 real / 150 fake):
    python eval/scripts/benchmark_aasist.py

    # Quick sanity check (limit N samples per class):
    python eval/scripts/benchmark_aasist.py --limit 10

    # Run on direct D:\\LA\\LA\\ dataset with 250 samples per class:
    python eval/scripts/benchmark_aasist.py --use-asvspoof-dir --samples-per-class 250

    # Save results to JSON:
    python eval/scripts/benchmark_aasist.py --out eval/reports/aasist_benchmark.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

# Repo paths
REPO_ROOT = Path(__file__).resolve().parents[2]
AASIST_DIR = REPO_ROOT / "detectors" / "aasist"
AUDIO_SUBSET_FAKE = REPO_ROOT / "eval" / "data" / "audio_subset" / "fake"
AUDIO_SUBSET_REAL = REPO_ROOT / "eval" / "data" / "audio_subset" / "real"

DEFAULT_ASVSPOOF_PROTOCOL = Path(r"D:\LA\LA\ASVspoof2019_LA_cm_protocols\ASVspoof2019.LA.cm.eval.trl.txt")
DEFAULT_ASVSPOOF_FLAC_DIR = Path(r"D:\LA\LA\ASVspoof2019_LA_eval\flac")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("benchmark_aasist")


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


def load_aasist_model():
    import torch
    aasist_mod = _import_file("aasist_model_arch", AASIST_DIR / "models" / "AASIST.py")
    Model = aasist_mod.Model

    weights_path = AASIST_DIR / "AASIST.pth"
    if not weights_path.exists():
        raise FileNotFoundError(f"AASIST weights not found at: {weights_path}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    config = {
        "architecture": "AASIST",
        "nb_samp": 64600,
        "first_conv": 128,
        "filts": [70, [1, 32], [32, 32], [32, 64], [64, 64]],
        "gat_dims": [64, 32],
        "pool_ratios": [0.5, 0.7, 0.5, 0.5],
        "temperatures": [2.0, 2.0, 100.0, 100.0],
    }
    logger.info(f"Loading AASIST from {weights_path} on {device}...")
    model = Model(config)
    model.load_state_dict(torch.load(str(weights_path), map_location=device))
    model.to(device)
    model.eval()
    return model, device


def collect_samples_from_subset(limit: int | None) -> Tuple[List[Path], List[Path]]:
    exts = {".flac", ".wav", ".mp3"}
    real_files = sorted(p for p in AUDIO_SUBSET_REAL.iterdir() if p.suffix.lower() in exts)
    fake_files = sorted(p for p in AUDIO_SUBSET_FAKE.iterdir() if p.suffix.lower() in exts)
    if limit:
        real_files = real_files[:limit]
        fake_files = fake_files[:limit]
    return real_files, fake_files


def collect_samples_from_protocol(
    protocol_path: Path, flac_dir: Path, n_per_class: int | None = None, all_balanced: bool = False, seed: int = 42
) -> Tuple[List[Path], List[Path]]:
    if not protocol_path.exists():
        raise FileNotFoundError(f"Protocol file missing: {protocol_path}")
    if not flac_dir.exists():
        raise FileNotFoundError(f"FLAC directory missing: {flac_dir}")

    real_ids, fake_ids = [], []
    with open(protocol_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 5:
                fid, lbl = parts[1], parts[4].lower()
                if lbl == "bonafide":
                    real_ids.append(fid)
                elif lbl == "spoof":
                    fake_ids.append(fid)

    rng = random.Random(seed)
    rng.shuffle(real_ids)
    rng.shuffle(fake_ids)

    if all_balanced:
        min_n = min(len(real_ids), len(fake_ids))
        real_ids = real_ids[:min_n]
        fake_ids = fake_ids[:min_n]
    elif n_per_class is not None:
        real_ids = real_ids[:n_per_class]
        fake_ids = fake_ids[:n_per_class]

    real_files = [flac_dir / f"{fid}.flac" for fid in real_ids]
    fake_files = [flac_dir / f"{fid}.flac" for fid in fake_ids]
    return real_files, fake_files


def main():
    parser = argparse.ArgumentParser(description="AASIST Benchmark")
    parser.add_argument("--limit", type=int, default=None, help="Limit samples per class for quick testing")
    parser.add_argument("--use-asvspoof-dir", action="store_true", help="Sample directly from D:\\LA\\LA\\ evaluation set")
    parser.add_argument("--samples-per-class", type=int, default=250, help="Samples per class when using ASVspoof protocol")
    parser.add_argument("--all", action="store_true", help="Evaluate the ENTIRE ASVspoof dataset (all 71,237 files)")
    parser.add_argument("--all-balanced", action="store_true", help="Evaluate ALL bonafide files with an equal number of spoofs (14,710 files)")
    parser.add_argument("--protocol", type=str, default=str(DEFAULT_ASVSPOOF_PROTOCOL), help="Path to protocol file")
    parser.add_argument("--flac-dir", type=str, default=str(DEFAULT_ASVSPOOF_FLAC_DIR), help="Path to FLAC files directory")
    parser.add_argument("--out", type=str, default=None, help="Path to output JSON")
    args = parser.parse_args()

    import torch
    prep_mod = _import_file("aasist_prep", AASIST_DIR / "preprocessing.py")
    preprocess_audio = prep_mod.preprocess_audio

    model, device = load_aasist_model()

    if args.all or args.all_balanced or args.use_asvspoof_dir:
        logger.info(f"Loading from ASVspoof protocol: {args.protocol}")
        n_pc = None if args.all else args.samples_per_class
        real_files, fake_files = collect_samples_from_protocol(
            Path(args.protocol), Path(args.flac_dir), n_per_class=n_pc, all_balanced=args.all_balanced
        )
    else:
        logger.info(f"Loading from balanced audio subset: {AUDIO_SUBSET_REAL.parent}")
        real_files, fake_files = collect_samples_from_subset(args.limit)

    total_files = len(real_files) + len(fake_files)
    logger.info(f"Collected {len(real_files)} real and {len(fake_files)} fake audio files (total {total_files}).")

    scores, labels = [], []
    failed = 0
    t_start = time.perf_counter()
    count = 0
    verbose_per_item = total_files <= 200

    for label_val, file_list, tag in [(0, real_files, "REAL"), (1, fake_files, "FAKE")]:
        for fpath in file_list:
            if not fpath.exists():
                logger.warning(f"File missing: {fpath}")
                failed += 1
                continue
            try:
                t0 = time.perf_counter()
                audio_tensor = preprocess_audio(str(fpath))
                with torch.no_grad():
                    _, out = model(audio_tensor.to(device))
                probs = torch.softmax(out, dim=-1)[0]
                spoof_prob = float(probs[0].item())  # Class 0 = spoof/fake
                elapsed = (time.perf_counter() - t0) * 1000

                scores.append(spoof_prob)
                labels.append(label_val)
                count += 1

                if verbose_per_item:
                    verdict = "FAKE" if spoof_prob >= 0.5 else "REAL"
                    ok = "[OK]" if (verdict == "FAKE") == (label_val == 1) else "[FAIL]"
                    print(f"  {ok} [{tag}] {fpath.name:<26s}  spoof_prob={spoof_prob:.4f}  {elapsed:5.1f}ms")
                elif count % 250 == 0 or count == total_files:
                    now = time.perf_counter() - t_start
                    fps = count / max(now, 0.1)
                    eta = (total_files - count) / max(fps, 0.1)
                    print(f"  [{count:>5d}/{total_files:>5d}] ({count/total_files*100:>5.1f}%)  Speed: {fps:.1f} files/s  ETA: {eta:.0f}s")

            except Exception as exc:
                logger.error(f"Error on {fpath.name}: {exc}")
                failed += 1

    total_time = time.perf_counter() - t_start
    m = compute_metrics(scores, labels)

    print("\n" + "=" * 62)
    print("  AASIST BENCHMARK RESULTS")
    print("=" * 62)
    print(f"  Total Evaluated : {m['n_total']} files ({total_time:.1f}s, {m['n_total']/max(total_time,0.1):.1f} files/sec)")
    print(f"  Accuracy        : {m['accuracy'] * 100:.2f}%")
    print(f"  Real Accuracy   : {m['real_acc'] * 100:.2f}%  (TN={m['confusion_matrix']['TN']}, FP={m['confusion_matrix']['FP']})")
    print(f"  Fake Accuracy   : {m['fake_acc'] * 100:.2f}%  (TP={m['confusion_matrix']['TP']}, FN={m['confusion_matrix']['FN']})")
    print(f"  AUC Score       : {m['auc']:.4f}")
    if not np.isnan(m["eer"]):
        print(f"  Equal Error Rate: {m['eer'] * 100:.2f}%  (Paper target: ~0.83%)")
    print("=" * 62)

    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2)
        print(f"Saved results JSON to: {out_p}")


if __name__ == "__main__":
    main()
