"""
Baseline Accuracy Benchmark — Wrapped Detectors
================================================

Goal: run one or more detectors (each running as a microservice with a
/detect endpoint) against labeled evaluation samples, and compute:
  - Accuracy / Precision / Recall   (for all detectors)
  - EER (Equal Error Rate)          (AASIST only, or any audio spoof detector)

The result is written to a Markdown file, ready to be committed under eval/.

--------------------------------------------------------------------
How to use this file:
1. Update the values in the "CONFIG" section below to match your data
   and endpoints.
2. First run with dummy data to confirm the script works end-to-end:
       python run_baseline_benchmark.py --dry-run
3. Once the real data and wrapper endpoints are ready:
       python run_baseline_benchmark.py
--------------------------------------------------------------------
"""

import argparse
import csv
import os
import random
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import requests
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_curve


# ======================================================================
# CONFIG — update these values for your project (TODO = not wired up yet)
# ======================================================================

@dataclass
class DetectorConfig:
    name: str                  # display name used in the results table
    endpoint_url: str          # e.g. "http://localhost:8001/detect"
    samples_dir: str           # folder containing the sample files (audio/image/video)
    labels_csv: str            # CSV with two columns: filename, label (real/fake)
    file_field_name: str = "file"   # form field name the file is sent under
    compute_eer: bool = False       # True for AASIST only (or any audio spoof detector)


# TODO: once the real AASIST wrapper endpoint is live, update these values
AASIST_CONFIG = DetectorConfig(
    name="AASIST (Audio)",
    endpoint_url="http://localhost:8001/detect",      # TODO: real wrapper URL
    samples_dir="data/eval_samples/audio",             # TODO: real samples folder
    labels_csv="data/eval_samples/audio_labels.csv",   # TODO: real labels file (filename,label)
    compute_eer=True,
)

# TODO: once the second detector (rppg / syncnet / video_classifier) is wrapped and ready
SECOND_DETECTOR_CONFIG = DetectorConfig(
    name="TODO_DETECTOR_NAME",
    endpoint_url="http://localhost:8002/detect",       # TODO
    samples_dir="data/eval_samples/video",              # TODO
    labels_csv="data/eval_samples/video_labels.csv",    # TODO
    compute_eer=False,
)

OUTPUT_MARKDOWN_PATH = "eval/baseline_benchmark.md"
N_SAMPLES = 100  # number of samples required by the task


# ======================================================================
# 1) Load labels from a CSV file
#    Expected format:  filename,label
#                       sample_001.wav,real
#                       sample_002.wav,fake
# ======================================================================

def load_labels(labels_csv_path: str) -> dict:
    labels = {}
    with open(labels_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            labels[row["filename"]] = row["label"].strip().lower()
    return labels


# ======================================================================
# 2) Call the detector through its /detect endpoint
#    Assumption: the endpoint accepts a file (multipart/form-data) and
#    returns JSON with at least two keys: is_fake (bool) and confidence (float 0-1)
#    If your endpoint's request/response shape differs, only this function
#    needs to change.
# ======================================================================

def call_detector(endpoint_url: str, file_path: str, field_name: str = "file") -> dict:
    with open(file_path, "rb") as f:
        files = {field_name: f}
        response = requests.post(endpoint_url, files=files, timeout=30)
    response.raise_for_status()
    return response.json()   # expected: {"is_fake": True/False, "confidence": 0.87}


# ======================================================================
# 3) Run the full benchmark for a single detector
# ======================================================================

def run_benchmark_for_detector(config: DetectorConfig, n_samples: int = N_SAMPLES) -> list:
    labels = load_labels(config.labels_csv)

    # take the first n_samples only (or all available if fewer)
    filenames = list(labels.keys())[:n_samples]

    results = []
    for filename in filenames:
        file_path = os.path.join(config.samples_dir, filename)
        true_label = labels[filename]

        try:
            prediction = call_detector(config.endpoint_url, file_path, config.file_field_name)
        except Exception as e:
            print(f"⚠️  Failed on {filename}: {e}")
            continue

        results.append({
            "filename": filename,
            "true_label": true_label,
            "predicted_label": "fake" if prediction.get("is_fake") else "real",
            "confidence": float(prediction.get("confidence", 0.5)),
        })

    return results


# ======================================================================
# 4) Compute metrics (accuracy / precision / recall / EER)
# ======================================================================

def compute_basic_metrics(results: list) -> dict:
    y_true = [1 if r["true_label"] == "fake" else 0 for r in results]
    y_pred = [1 if r["predicted_label"] == "fake" else 0 for r in results]

    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
    }


def compute_eer(results: list) -> float:
    """EER: the point where False Positive Rate = False Negative Rate."""
    y_true = [1 if r["true_label"] == "fake" else 0 for r in results]
    scores = [r["confidence"] for r in results]  # confidence that the sample is fake

    fpr, tpr, _ = roc_curve(y_true, scores)
    fnr = 1 - tpr
    eer_index = np.nanargmin(np.abs(fnr - fpr))
    return float(fpr[eer_index])


# ======================================================================
# 5) Write the final results table to a Markdown file
# ======================================================================

def save_results_table(all_metrics: dict, output_path: str = OUTPUT_MARKDOWN_PATH):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Baseline Accuracy Benchmark\n\n")
        f.write("Regression baseline for all later comparisons — "
                f"{N_SAMPLES} labeled samples per detector.\n\n")
        f.write("| Detector | Accuracy | Precision | Recall | EER |\n")
        f.write("|---|---|---|---|---|\n")

        for detector_name, metrics in all_metrics.items():
            eer_str = f"{metrics['eer']:.3f}" if metrics.get("eer") is not None else "—"
            f.write(
                f"| {detector_name} | {metrics['accuracy']:.3f} | "
                f"{metrics['precision']:.3f} | {metrics['recall']:.3f} | {eer_str} |\n"
            )

    print(f"✅ Saved benchmark table to {output_path}")


# ======================================================================
# 6) DRY RUN — dummy data to verify everything works before the real
#    dataset arrives (this does NOT send any HTTP requests; it only
#    confirms the metrics computation is correct)
# ======================================================================

def generate_dummy_results(n_samples: int = 100, seed: int = 42) -> list:
    random.seed(seed)
    np.random.seed(seed)

    results = []
    for i in range(n_samples):
        true_label = random.choice(["real", "fake"])
        # a fake model that gets things wrong sometimes, to look realistic
        correct = random.random() > 0.12
        predicted_label = true_label if correct else ("fake" if true_label == "real" else "real")
        confidence = np.random.uniform(0.6, 0.99) if predicted_label == "fake" else np.random.uniform(0.01, 0.4)

        results.append({
            "filename": f"dummy_{i}.wav",
            "true_label": true_label,
            "predicted_label": predicted_label,
            "confidence": confidence,
        })
    return results


def run_dry_run():
    print("🧪 Running DRY RUN with dummy data (no real detectors called)...\n")

    dummy_all_metrics = {}

    for detector_name, compute_eer_flag in [("AASIST (Audio) [DUMMY]", True),
                                              ("Second Detector [DUMMY]", False)]:
        results = generate_dummy_results(n_samples=N_SAMPLES)
        metrics = compute_basic_metrics(results)
        if compute_eer_flag:
            metrics["eer"] = compute_eer(results)
        else:
            metrics["eer"] = None
        dummy_all_metrics[detector_name] = metrics

        print(f"{detector_name}: "
              f"acc={metrics['accuracy']:.3f}, "
              f"precision={metrics['precision']:.3f}, "
              f"recall={metrics['recall']:.3f}, "
              f"eer={metrics['eer']}")

    save_results_table(dummy_all_metrics, output_path="eval/baseline_benchmark_DRYRUN.md")
    print("\n✅ Dry run complete. Script logic verified — ready for real data + endpoints.")


# ======================================================================
# MAIN
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Baseline benchmark for wrapped detectors.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Run with dummy data instead of calling real detector endpoints.")
    args = parser.parse_args()

    if args.dry_run:
        run_dry_run()
        return

    all_metrics = {}

    for config in [AASIST_CONFIG, SECOND_DETECTOR_CONFIG]:
        print(f"\n▶ Running benchmark for {config.name}...")
        results = run_benchmark_for_detector(config, n_samples=N_SAMPLES)

        if not results:
            print(f"⚠️  No results for {config.name} — skipping. "
                  f"Check samples_dir/labels_csv/endpoint_url in CONFIG.")
            continue

        metrics = compute_basic_metrics(results)
        metrics["eer"] = compute_eer(results) if config.compute_eer else None
        all_metrics[config.name] = metrics

        print(f"   accuracy={metrics['accuracy']:.3f}  "
              f"precision={metrics['precision']:.3f}  "
              f"recall={metrics['recall']:.3f}  "
              f"eer={metrics['eer']}")

    if all_metrics:
        save_results_table(all_metrics)
    else:
        print("\n❌ No detector produced results. Nothing saved.")


if __name__ == "__main__":
    main()