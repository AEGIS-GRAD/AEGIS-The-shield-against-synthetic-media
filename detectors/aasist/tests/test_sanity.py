"""
Sanity check: Runs inference across 50 ASVspoof 2019 samples (25 bonafide, 25 spoof)
and validates model accuracy, confusion matrix, and performance metrics.
"""

import os
import csv
import base64
import pytest
from fastapi.testclient import TestClient

from app import app, load_model

client = TestClient(app)
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
LABELS_FILE = os.path.join(FIXTURES_DIR, "labels.csv")


@pytest.fixture(scope="session", autouse=True)
def initialize_model():
    weights_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../weights/AASIST.pth")
    )
    load_model(weights_path)


def test_50_samples_sanity_and_accuracy():
    """
    Evaluates 50 ASVspoof 2019 samples and checks accuracy against ground truth.
    Asserts >= 90% accuracy on this benchmark fixture subset.
    """
    assert os.path.exists(LABELS_FILE), f"Missing labels file: {LABELS_FILE}"

    samples = []
    with open(LABELS_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            samples.append(row)

    assert len(samples) == 50, f"Expected 50 fixture samples, found {len(samples)}"

    tp = 0  # Spoof correctly identified as spoof
    tn = 0  # Bonafide correctly identified as bonafide
    fp = 0  # Bonafide falsely identified as spoof
    fn = 0  # Spoof falsely identified as bonafide

    results = []

    for idx, sample in enumerate(samples):
        filepath = os.path.join(FIXTURES_DIR, sample["filename"])
        assert os.path.exists(filepath), f"Audio file not found: {filepath}"

        with open(filepath, "rb") as f:
            b64_audio = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "job_id": f"sanity-check-{idx:03d}",
            "modality": "audio",
            "payload": b64_audio
        }

        response = client.post("/detect", json=payload)
        assert response.status_code == 200, f"Detection failed for {sample['filename']}: {response.text}"

        data = response.json()
        conf = data["confidence"]
        pred_label = "spoof" if conf >= 0.5 else "bonafide"
        true_label = sample["label"]

        if true_label == "spoof":
            if pred_label == "spoof":
                tp += 1
            else:
                fn += 1
        else:
            if pred_label == "bonafide":
                tn += 1
            else:
                fp += 1

        results.append({
            "filename": sample["filename"],
            "true": true_label,
            "pred": pred_label,
            "confidence": conf,
            "latency_ms": data["latency_ms"]
        })

    total = len(samples)
    correct = tp + tn
    accuracy = (correct / total) * 100.0
    avg_latency = sum(r["latency_ms"] for r in results) / total

    print("\n" + "=" * 60)
    print("      AASIST 50-SAMPLE SANITY CHECK BENCHMARK")
    print("=" * 60)
    print(f"Total Samples Evaluated: {total}")
    print(f"True Positives (Spoof -> Spoof):       {tp}")
    print(f"True Negatives (Bonafide -> Bonafide): {tn}")
    print(f"False Positives (Bonafide -> Spoof):   {fp}")
    print(f"False Negatives (Spoof -> Bonafide):   {fn}")
    print("-" * 60)
    print(f"Final Accuracy:                        {accuracy:.2f}%")
    print(f"Average Inference Latency:             {avg_latency:.2f} ms")
    print("=" * 60)

    # Assert model exceeds 90% benchmark accuracy
    assert accuracy >= 90.0, f"Accuracy {accuracy:.2f}% below required 90.0% threshold"
