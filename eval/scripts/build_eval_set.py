"""
Build Evaluation Dataset Manifest & Edge Cases Directory Structure.

Discovers staged samples from eval/data/video_subset/{real,fake}/ and
eval/data/audio_subset/{real,fake}/, samples at least 100 items (30 real video,
30 fake video, 30 real audio, 30 fake audio = 120 total), creates edge cases
directory structure, and writes eval/data/eval_manifest.csv.
"""

import csv
import os
import random
from pathlib import Path

# Base paths relative to workspace root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = BASE_DIR / "eval"
DATA_DIR = EVAL_DIR / "data"

VIDEO_REAL_DIR = DATA_DIR / "video_subset" / "real"
VIDEO_FAKE_DIR = DATA_DIR / "video_subset" / "fake"
AUDIO_REAL_DIR = DATA_DIR / "audio_subset" / "real"
AUDIO_FAKE_DIR = DATA_DIR / "audio_subset" / "fake"

EDGE_CASES_DIR = DATA_DIR / "edge_cases"
DUBBED_DIR = EDGE_CASES_DIR / "dubbed"
SILENT_DIR = EDGE_CASES_DIR / "silent"
MANIFEST_PATH = DATA_DIR / "eval_manifest.csv"


def create_edge_cases_structure():
    """Creates eval/data/edge_cases/{dubbed,silent}/ structure and README."""
    os.makedirs(DUBBED_DIR, exist_ok=True)
    os.makedirs(SILENT_DIR, exist_ok=True)

    readme_path = EDGE_CASES_DIR / "README.md"
    readme_content = """# Edge Cases Evaluation Directory

This directory contains placeholder folders for edge-case media evaluation:

- `dubbed/`: Dubbed videos where lip movement and audio phonemes are mismatched, but neither track is individually AI-synthesized.
- `silent/`: Video files containing no audio track, used to evaluate single-modality video detectors and pipeline graceful fallback.

Note: These edge cases require manual sourcing or specialized synthetic edit generation and are excluded from automatic benchmark manifests.
"""
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)
    print(f"Created edge cases structure at {EDGE_CASES_DIR}")


def build_manifest(samples_per_category: int = 30, seed: int = 42):
    """Samples video and audio subsets and builds eval_manifest.csv."""
    random.seed(seed)

    categories = [
        (VIDEO_REAL_DIR, "video", "real"),
        (VIDEO_FAKE_DIR, "video", "fake"),
        (AUDIO_REAL_DIR, "audio", "real"),
        (AUDIO_FAKE_DIR, "audio", "fake"),
    ]

    manifest_rows = []

    for directory, modality, label in categories:
        if not directory.exists():
            print(f"Warning: Directory {directory} does not exist!")
            continue

        files = [f for f in directory.iterdir() if f.is_file() and not f.name.startswith(".")]
        files.sort()

        if len(files) > samples_per_category:
            sampled = random.sample(files, samples_per_category)
        else:
            sampled = files

        sampled.sort()
        print(f"Sampled {len(sampled)} files for {modality}/{label} from {directory}")

        for filepath in sampled:
            # Store path relative to workspace root (using forward slashes)
            rel_path = filepath.relative_to(BASE_DIR).as_posix()
            manifest_rows.append({
                "sample_path": rel_path,
                "modality": modality,
                "true_label": label,
            })

    # Shuffle combined manifest deterministically
    random.shuffle(manifest_rows)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_path", "modality", "true_label"])
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"Wrote {len(manifest_rows)} benchmark samples to {MANIFEST_PATH}")


def main():
    create_edge_cases_structure()
    build_manifest(samples_per_category=30, seed=42)


if __name__ == "__main__":
    main()
