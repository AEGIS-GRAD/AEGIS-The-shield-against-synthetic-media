from __future__ import annotations

import csv
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

import cv2
import numpy as np
from tabulate import tabulate

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = Path(__file__).resolve().parents[1]
VC_DIR = REPO_ROOT / "detectors" / "video-classifier"

for _p in [str(REPO_ROOT), str(ENGINE_DIR), str(VC_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from preprocess import VideoPreprocessor  # type: ignore[import-not-found,import-untyped]
except Exception:
    import importlib.util
    _spec = importlib.util.spec_from_file_location("vc_preprocess", str(VC_DIR / "preprocess.py"))
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        VideoPreprocessor = _mod.VideoPreprocessor  # type: ignore[assignment]
    else:
        VideoPreprocessor = None  # type: ignore[assignment,misc]

try:
    from engine.edge_model.sliding_window import SlidingWindowDetector
    from engine.edge_model.build_edge_model import DEFAULT_WEIGHTS_PATH
    from engine.edge_model.export_onnx import FP32_ONNX_PATH, INT8_ONNX_PATH, run_export_pipeline
    from engine.edge_model.streaming_rppg import StreamingRppgDetector  # Role 5
except ImportError:
    from edge_model.sliding_window import SlidingWindowDetector  # type: ignore[no-redef]
    from edge_model.build_edge_model import DEFAULT_WEIGHTS_PATH  # type: ignore[no-redef]
    from edge_model.export_onnx import FP32_ONNX_PATH, INT8_ONNX_PATH, run_export_pipeline  # type: ignore[no-redef]
    from edge_model.streaming_rppg import StreamingRppgDetector  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "eval" / "data" / "eval_manifest.csv"
RESULTS_PATH = REPO_ROOT / "engine" / "benchmark" / "results.txt"
DUAL_MODEL_RESULTS_PATH = REPO_ROOT / "engine" / "benchmark" / "results_dual_model.txt"  # Role 5


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


def compute_accuracy(labels: np.ndarray, scores: np.ndarray) -> float:
    """Computes binary classification accuracy percentage given true labels (0/1) and predicted scores."""
    if len(labels) == 0 or len(scores) == 0:
        return 0.0
    preds = (scores >= 0.5).astype(int)
    return float(np.mean(preds == labels) * 100.0)


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


# =============================================================================
# ROLE 5 — Dual-Model Surveillance Benchmark
# =============================================================================

def _extract_face_mean_rgb(frame_bgr: np.ndarray) -> Tuple[Optional[np.ndarray], bool]:
    """Extract mean face-region RGB from a BGR frame using Haar cascade.

    Returns (mean_rgb_array, face_detected).
    Falls back to center-crop if no face found, flagged as not detected.
    """
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3, minSize=(40, 40))

    if len(faces) > 0:
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])  # pick largest face
        roi = frame_bgr[y:y+h, x:x+w]
        rgb_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        return rgb_roi.reshape(-1, 3).mean(axis=0).astype(np.float32), True

    # No face found — signal to rPPG that it should return not_applicable
    return None, False


def benchmark_surveillance_dual_model(
    video_paths_labels: List[Tuple[Path, int]],
    fps: float = 30.0,
) -> Dict[str, Any]:
    """Benchmark the dual-model surveillance pipeline (Role 5 deliverable).

    For each video:
      1. Streams every frame through SlidingWindowDetector (spatial CNN).
      2. Simultaneously streams face RGB through StreamingRppgDetector (physiological).
      3. Fuses scores: 0.6 * spatial + 0.4 * rppg (or falls back to spatial-only).
      4. Compares fused verdict against true label.

    Returns metrics dict with latency, throughput, accuracy, EER,
    and rPPG engagement rate (% of frames where rPPG was active, not warming up).
    """
    spatial_detector = SlidingWindowDetector(backend="pytorch", window_size=16, stride=8)
    rppg_detector = StreamingRppgDetector(fps=fps, window_seconds=6.0, stride_frames=15)

    _IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    _IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    total_frames = 0
    total_time_s = 0.0
    rppg_active_frames = 0  # frames where rPPG returned a real score (not warming_up / N/A)
    labels: List[int] = []
    fused_scores: List[float] = []
    spatial_only_scores: List[float] = []

    for video_path, true_label in video_paths_labels:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning("Could not open video: %s — skipping.", video_path.name)
            continue

        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        rppg_detector.reset()   # fresh temporal buffer per video

        frame_scores_fused: List[float] = []
        frame_scores_spatial: List[float] = []

        while cap.isOpened():
            ret, frame_bgr = cap.read()
            if not ret:
                break

            start = time.perf_counter()

            # --- Spatial classifier (MobileNetV3) ---
            resized = cv2.resize(frame_bgr, (224, 224))
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            normed = ((rgb - _IMAGENET_MEAN) / _IMAGENET_STD).transpose(2, 0, 1)  # (3,224,224)
            spatial_raw = spatial_detector.push_frame(normed)
            spatial_score = spatial_raw if spatial_raw is not None else 0.5

            # --- Streaming rPPG (CHROM rolling window) ---
            mean_rgb, face_detected = _extract_face_mean_rgb(frame_bgr)
            rppg_result = rppg_detector.process_frame(mean_rgb, face_detected=face_detected)
            rppg_score: Optional[float] = rppg_result.get("score")
            rppg_status: str = rppg_result.get("status", "")

            # --- Score fusion ---
            if rppg_score is not None:
                fused = float(np.clip(0.6 * spatial_score + 0.4 * rppg_score, 0.0, 1.0))
                rppg_active_frames += 1
            else:
                fused = float(np.clip(spatial_score, 0.0, 1.0))

            elapsed = time.perf_counter() - start
            total_time_s += elapsed
            total_frames += 1
            frame_scores_fused.append(fused)
            frame_scores_spatial.append(spatial_score)

        cap.release()

        if frame_scores_fused:
            # Video-level verdict = mean of frame-level fused scores
            labels.append(true_label)
            fused_scores.append(float(np.mean(frame_scores_fused)))
            spatial_only_scores.append(float(np.mean(frame_scores_spatial)))

    # --- Aggregate metrics ---
    labels_arr = np.array(labels)
    fused_arr = np.array(fused_scores)
    spatial_arr = np.array(spatial_only_scores)

    avg_latency_ms: float = 0.0
    rppg_engagement_pct: float = 0.0
    throughput_fps: float = 0.0

    if total_frames > 0:
        avg_latency_ms = float(total_time_s / total_frames * 1000.0)
        rppg_engagement_pct = float(rppg_active_frames / total_frames * 100.0)

    if total_time_s > 0:
        throughput_fps = float(total_frames / total_time_s)

    return {
        "videos": len(labels),
        "total_frames": total_frames,
        "avg_latency_ms": round(avg_latency_ms, 2),
        "throughput_fps": round(throughput_fps, 1),
        "accuracy_fused": round(compute_accuracy(labels_arr, fused_arr), 2),
        "accuracy_spatial_only": round(compute_accuracy(labels_arr, spatial_arr), 2),
        "eer_fused": round(compute_eer(labels_arr, fused_arr), 2),
        "eer_spatial_only": round(compute_eer(labels_arr, spatial_arr), 2),
        "rppg_engagement_pct": round(rppg_engagement_pct, 1),
    }


def run_surveillance_benchmark() -> None:
    """Entry point for the Role 5 dual-model surveillance benchmark.

    Compares:
      - Baseline: MobileNetV3-Small spatial classifier only
      - Dual-model: MobileNetV3-Small + Streaming rPPG (fused 60/40)

    Outputs a report table and saves to engine/benchmark/results_dual_model.txt.
    """
    logger.info("=" * 65)
    logger.info("  AEGIS ROLE 5 — DUAL-MODEL SURVEILLANCE BENCHMARK")
    logger.info("=" * 65)

    samples = load_video_dataset(limit=10)
    if not samples:
        logger.error(
            "No video samples found in eval_manifest.csv.\n"
            "Make sure eval/data/eval_manifest.csv exists and "
            "points to real video files (run eval/scripts/make_subset.py first).\n"
            "Running with SYNTHETIC data for smoke-test..."
        )
        # --- Smoke-test with synthetic numpy videos ---
        _run_synthetic_smoke_test()
        return

    logger.info("Loaded %d video samples. Running dual-model benchmark...", len(samples))
    metrics = benchmark_surveillance_dual_model(samples, fps=30.0)

    _print_and_save_surveillance_report(metrics)


def _run_synthetic_smoke_test() -> None:
    """Runs a quick smoke-test using synthetic numpy frames (no real videos needed).

    Generates 10 fake 'videos' of 60 frames each at 30fps and verifies the
    dual-model pipeline runs without errors, producing valid score ranges.
    """
    logger.info("Generating synthetic frames for smoke-test (10 videos × 60 frames)...")

    rng = np.random.default_rng(42)
    NUM_VIDEOS = 10
    FRAMES_PER_VIDEO = 240  # 8.0 seconds @ 30 FPS (ensures 6-sec warmup completes)
    FPS = 30.0

    spatial_detector = SlidingWindowDetector(backend="pytorch", window_size=16, stride=8)
    rppg_detector = StreamingRppgDetector(fps=FPS, window_seconds=6.0, stride_frames=15)

    _IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    _IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    all_fused: List[float] = []
    all_spatial: List[float] = []
    labels: List[int] = []
    rppg_active = 0
    total_frames = 0
    total_time_s = 0.0

    for vid_idx in range(NUM_VIDEOS):
        rppg_detector.reset()
        # Alternate real (0) vs fake (1)
        is_fake = (vid_idx % 2 == 1)
        labels.append(1 if is_fake else 0)
        frame_scores_fused: List[float] = []
        frame_scores_spatial: List[float] = []

        for frame_i in range(FRAMES_PER_VIDEO):
            start = time.perf_counter()

            # Synthetic BGR frame (224×224)
            if is_fake:
                frame_bgr = rng.integers(50, 200, (224, 224, 3), dtype=np.uint8)
            else:
                # Realistic face-like skin tone with heartbeat micro-variation
                t = frame_i / FPS
                hz = 72 / 60.0
                r = int(np.clip(150 + 5 * np.sin(2 * np.pi * hz * t), 0, 255))
                g = int(np.clip(100 + 3 * np.sin(2 * np.pi * hz * t + 0.1), 0, 255))
                b = int(np.clip(80  + 2 * np.sin(2 * np.pi * hz * t + 0.2), 0, 255))
                frame_bgr = np.full((224, 224, 3), [b, g, r], dtype=np.uint8)

            # Spatial classifier input
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            normed = ((rgb - _IMAGENET_MEAN) / _IMAGENET_STD).transpose(2, 0, 1)
            spatial_raw = spatial_detector.push_frame(normed)
            spatial_score = spatial_raw if spatial_raw is not None else 0.5

            # rPPG input (use center crop as "face")
            mean_rgb = frame_bgr.reshape(-1, 3).mean(axis=0)[[2, 1, 0]].astype(np.float32)  # BGR→RGB order
            rppg_result = rppg_detector.process_frame(mean_rgb, face_detected=True)
            rppg_score = rppg_result.get("score")
            rppg_status = rppg_result.get("status", "")

            # Fusion
            if rppg_score is not None:
                fused = float(np.clip(0.6 * spatial_score + 0.4 * rppg_score, 0.0, 1.0))
                rppg_active += 1
            else:
                fused = float(np.clip(spatial_score, 0.0, 1.0))

            elapsed = time.perf_counter() - start
            total_time_s += elapsed
            total_frames += 1
            frame_scores_fused.append(fused)
            frame_scores_spatial.append(spatial_score)

        all_fused.append(float(np.mean(frame_scores_fused)))
        all_spatial.append(float(np.mean(frame_scores_spatial)))

    avg_latency_ms: float = 0.0
    rppg_pct: float = 0.0
    throughput_fps: float = 0.0

    if total_frames > 0:
        avg_latency_ms = float(total_time_s / total_frames * 1000.0)
        rppg_pct = float(rppg_active / total_frames * 100.0)

    if total_time_s > 0:
        throughput_fps = float(total_frames / total_time_s)

    labels_arr = np.array(labels)
    fused_arr = np.array(all_fused)
    spatial_arr = np.array(all_spatial)

    metrics = {
        "videos": NUM_VIDEOS,
        "total_frames": total_frames,
        "avg_latency_ms": round(avg_latency_ms, 2),
        "throughput_fps": round(throughput_fps, 1),
        "accuracy_fused": round(compute_accuracy(labels_arr, fused_arr), 1),
        "accuracy_spatial_only": round(compute_accuracy(labels_arr, spatial_arr), 1),
        "eer_fused": round(compute_eer(labels_arr, fused_arr), 1),
        "eer_spatial_only": round(compute_eer(labels_arr, spatial_arr), 1),
        "rppg_engagement_pct": round(rppg_pct, 1),
    }
    _print_and_save_surveillance_report(metrics, smoke_test=True)


def _print_and_save_surveillance_report(
    metrics: Dict[str, Any],
    smoke_test: bool = False,
) -> None:
    """Formats and prints the surveillance benchmark report."""
    mode_note = "(SMOKE-TEST — synthetic simulated streams)" if smoke_test else "(FaceForensics++ subset)"

    comparison_rows = [
        [
            "Spatial Only (MobileNetV3)",
            f"{metrics['accuracy_spatial_only']}%" if metrics['accuracy_spatial_only'] != "N/A" else "N/A",
            f"{metrics['eer_spatial_only']}%" if metrics['eer_spatial_only'] != "N/A" else "N/A",
            f"{metrics['avg_latency_ms']:.2f} ms",
            f"{metrics['throughput_fps']:.1f} FPS",
            "0%",
        ],
        [
            "Dual-Model (Spatial + rPPG)",
            f"{metrics['accuracy_fused']}%" if metrics['accuracy_fused'] != "N/A" else "N/A",
            f"{metrics['eer_fused']}%" if metrics['eer_fused'] != "N/A" else "N/A",
            f"{metrics['avg_latency_ms']:.2f} ms",
            f"{metrics['throughput_fps']:.1f} FPS",
            f"{metrics['rppg_engagement_pct']}%",
        ],
    ]

    headers = ["Pipeline", "Accuracy", "EER", "Avg Latency", "Throughput", "rPPG Active"]
    table_str = tabulate(comparison_rows, headers=headers, tablefmt="github")

    report = (
        "=====================================================================\n"
        "   AEGIS ROLE 5 — DUAL-MODEL SURVEILLANCE BENCHMARK RESULTS          \n"
        "=====================================================================\n\n"
        f"Mode: {mode_note}\n"
        f"Videos evaluated: {metrics['videos']}  |  "
        f"Total frames: {metrics['total_frames']}\n\n"
        f"{table_str}\n\n"
        "Fusion formula: fused_score = 0.6 × spatial_score + 0.4 × rppg_score\n"
        "Fallback: when rPPG is warming_up or not_applicable → fused = spatial only\n\n"
        "rPPG Active = % of frames where rPPG buffer was full and face was detected.\n"
        "Expect ~0% for first 6 seconds (warm-up), then rising toward 100%.\n"
    )

    print("\n" + report)

    DUAL_MODEL_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DUAL_MODEL_RESULTS_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info("Saved dual-model benchmark results to %s", DUAL_MODEL_RESULTS_PATH)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import argparse
    parser = argparse.ArgumentParser(description="AEGIS Engine Benchmark")
    parser.add_argument(
        "--mode",
        choices=["single", "dual", "all"],
        default="all",
        help=(
            "single = original 3-backend benchmark (PyTorch/ONNX FP32/INT8), "
            "dual = Role 5 dual-model surveillance benchmark, "
            "all = run both (default)"
        ),
    )
    args = parser.parse_args()

    if args.mode in ("single", "all"):
        run_full_benchmark()

    if args.mode in ("dual", "all"):
        run_surveillance_benchmark()
