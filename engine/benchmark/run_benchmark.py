from __future__ import annotations

import csv
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any

import numpy as np
from tabulate import tabulate

REPO_ROOT = Path(__file__).resolve().parents[2]
VC_DIR = REPO_ROOT / "detectors" / "video-classifier"
if str(VC_DIR) not in sys.path:
    sys.path.insert(0, str(VC_DIR))

from preprocess import VideoPreprocessor
from engine.edge_model.sliding_window import SlidingWindowDetector
from engine.edge_model.build_edge_model import DEFAULT_WEIGHTS_PATH
from engine.edge_model.export_onnx import FP32_ONNX_PATH, INT8_ONNX_PATH, run_export_pipeline

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "eval" / "data" / "eval_manifest.csv"
RESULTS_PATH = REPO_ROOT / "engine" / "benchmark" / "results.txt"


def compute_eer(labels: np.ndarray, scores: np.ndarray) -> float:
    """Computes Equal Error Rate (EER) given true labels (0/1) and predicted scores [0.0, 1.0]."""
    if len(labels) == 0 or len(np.unique(labels)) < 2:
        return 0.0

    thresholds = np.linspace(0.0, 1.0, 101)
    far_list = []
    frr_list = []

    for th in thresholds:
        preds = (scores >= th).astype(int)
        # FAR = FP / (FP + TN)
        fp = np.sum((preds == 1) & (labels == 0))
        tn = np.sum((preds == 0) & (labels == 0))
        far = fp / (fp + tn) if (fp + tn) > 0 else 0.0

        # FRR = FN / (FN + TP)
        fn = np.sum((preds == 0) & (labels == 1))
        tp = np.sum((preds == 1) & (labels == 1))
        frr = fn / (fn + tp) if (fn + tp) > 0 else 0.0

        far_list.append(far)
        frr_list.append(frr)

    far_arr = np.array(far_list)
    frr_arr = np.array(frr_list)
    diff = np.abs(far_arr - frr_arr)
    min_idx = np.argmin(diff)
    return float((far_arr[min_idx] + frr_arr[min_idx]) / 2.0 * 100.0)


def load_video_dataset(limit: int = 50) -> List[Tuple[Path, int]]:
    """Loads video sample paths and integer labels (1=fake, 0=real) from manifest."""
    samples: List[Tuple[Path, int]] = []
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("modality") == "video":
                    file_path = REPO_ROOT / row["sample_path"]
                    label_str = row.get("true_label", "").lower()
                    if file_path.exists() and label_str in ("real", "fake"):
                        label_val = 1 if label_str == "fake" else 0
                        samples.append((file_path, label_val))
                        if len(samples) >= limit:
                            break
    return samples


def benchmark_backend(
    backend: str,
    preprocessed_dataset: List[Tuple[List[Any], int]],
) -> Dict[str, Any]:
    """Runs latency and accuracy benchmark for a specific backend."""
    detector = SlidingWindowDetector(backend=backend, window_size=16, stride=8)

    total_frames = 0
    total_time_s = 0.0
    labels = []
    scores = []

    for frames, true_label in preprocessed_dataset:
        if not frames:
            continue

        start = time.perf_counter()
        score = detector.predict_window(frames)
        elapsed = time.perf_counter() - start

        total_time_s += elapsed
        total_frames += len(frames)
        labels.append(true_label)
        scores.append(score)

    labels_arr = np.array(labels)
    scores_arr = np.array(scores)
    preds_arr = (scores_arr >= 0.5).astype(int)

    acc = np.mean(preds_arr == labels_arr) * 100.0 if len(labels) > 0 else 0.0
    eer = compute_eer(labels_arr, scores_arr)
    avg_latency_ms = (total_time_s / total_frames * 1000.0) if total_frames > 0 else 0.0
    fps = total_frames / total_time_s if total_time_s > 0 else 0.0

    return {
        "backend": backend,
        "latency_ms": round(avg_latency_ms, 2),
        "fps": round(fps, 1),
        "accuracy": round(acc, 2),
        "eer": round(eer, 2),
        "samples": len(labels),
        "frames": total_frames,
    }


def get_file_size_mb(path: Path) -> float:
    """Returns size of file in megabytes."""
    return round(path.stat().st_size / (1024 * 1024), 2) if path.exists() else 0.0


def run_full_benchmark():
    """Runs export pipeline, preprocesses video subset, and executes 3-backend benchmark."""
    logger.info("Ensuring ONNX models are exported and quantized...")
    run_export_pipeline()

    samples = load_video_dataset(limit=10)
    logger.info(f"Loaded {len(samples)} video samples for benchmarking.")

    if not samples:
        logger.error("No valid video samples found for benchmark.")
        return

    # Preprocess all video frames once to measure pure model inference speed fairly across backends
    logger.info("Preprocessing video frames...")
    preprocessor = VideoPreprocessor(target_size=(224, 224))
    preprocessed_dataset: List[Tuple[List[Any], int]] = []
    for vpath, label in samples:
        try:
            tensors = preprocessor.preprocess_video(vpath, sample_n=10)
            preprocessed_dataset.append((tensors, label))
        except Exception as e:
            logger.warning(f"Skipping {vpath.name}: {e}")

    logger.info("Running benchmarks across PyTorch, ONNX FP32, and ONNX INT8 backends...")
    results = []
    sizes = {
        "pytorch": get_file_size_mb(DEFAULT_WEIGHTS_PATH),
        "onnx_fp32": get_file_size_mb(FP32_ONNX_PATH),
        "onnx_int8": get_file_size_mb(INT8_ONNX_PATH),
    }

    for backend in ["pytorch", "onnx_fp32", "onnx_int8"]:
        res = benchmark_backend(backend, preprocessed_dataset)
        res["size_mb"] = sizes.get(backend, 0.0)
        results.append(res)

    # Format result table
    headers = ["Backend", "Model Size (MB)", "Latency (ms/frame)", "Throughput (FPS)", "Accuracy (%)", "EER (%)"]
    rows = [
        [
            r["backend"].upper(),
            f"{r['size_mb']:.2f} MB",
            f"{r['latency_ms']:.2f} ms",
            f"{r['fps']:.1f} FPS",
            f"{r['accuracy']:.2f} %",
            f"{r['eer']:.2f} %",
        ]
        for r in results
    ]

    table_str = tabulate(rows, headers=headers, tablefmt="github")

    report = (
        "=====================================================================\n"
        "           AEGIS ENGINE EDGE MODEL BENCHMARK RESULTS                 \n"
        "=====================================================================\n\n"
        f"{table_str}\n\n"
        f"Evaluated on {results[0]['samples']} videos ({results[0]['frames']} frames total).\n"
        "MobileNetV3-Small deepfake classifier on FaceForensics++ evaluation subset.\n"
    )

    print("\n" + report)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"Saved benchmark results to {RESULTS_PATH}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_full_benchmark()
