#!/usr/bin/env python3
"""
make_subset.py

Builds a stratified subset of the FaceForensics++ (c23) dataset into eval/data/video_subset/{real,fake}/.
Reads raw data path and category mappings from eval/config/data_paths.yaml.
"""

import argparse
import os
import random
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


def load_config(config_path: Path) -> dict:
    """Load configuration from YAML file, with fallback simple parser if PyYAML is absent."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found at '{config_path}'. "
            "Please ensure eval/config/data_paths.yaml exists."
        )

    try:
        import yaml

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise ValueError("Config YAML must be a dictionary.")
            return data
    except ImportError:
        # Simple fallback parser for data_paths.yaml format
        config: Dict[str, dict] = {"raw_data_root": "", "categories": {"real": [], "fake": []}}
        current_cat = None
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith("#"):
                    continue
                if line_str.startswith("raw_data_root:"):
                    val = line_str.split(":", 1)[1].strip().strip('"').strip("'")
                    config["raw_data_root"] = val
                elif line_str.startswith("real:"):
                    current_cat = "real"
                elif line_str.startswith("fake:"):
                    current_cat = "fake"
                elif line_str.startswith("- ") and current_cat:
                    item = line_str[2:].strip().strip('"').strip("'")
                    config["categories"][current_cat].append(item)
        return config


def find_video_files(folder_path: Path) -> List[Path]:
    """Find all video files in a folder."""
    if not folder_path.exists() or not folder_path.is_dir():
        return []
    return [
        p for p in folder_path.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]


def distribute_counts(total_count: int, num_buckets: int) -> List[int]:
    """Distribute total count evenly among buckets, placing remainder in first buckets."""
    if num_buckets <= 0:
        return []
    base = total_count // num_buckets
    remainder = total_count % num_buckets
    return [base + (1 if i < remainder else 0) for i in range(num_buckets)]


def build_subset(
    config_path: Path,
    output_dir: Path,
    n_real: int,
    n_fake: int,
    seed: int,
    clean: bool,
) -> None:
    config = load_config(config_path)
    raw_data_root = Path(config.get("raw_data_root", ""))
    categories = config.get("categories", {})
    real_subfolders = categories.get("real", ["original"])
    fake_subfolders = categories.get(
        "fake",
        [
            "Deepfakes",
            "Face2Face",
            "FaceShifter",
            "FaceSwap",
            "NeuralTextures",
            "DeepFakeDetection",
        ],
    )

    if not raw_data_root.exists():
        print(f"[ERROR] Raw data root path does not exist: {raw_data_root}")
        print(f"        Please update '{config_path}' with the correct path to FaceForensics++ raw data.")
        sys.exit(1)

    print(f"Raw data root: {raw_data_root}")
    print(f"Target output directory: {output_dir}")
    print(f"Sampling plan: {n_real} real, {n_fake} fake (seed: {seed})")

    real_out_dir = output_dir / "real"
    fake_out_dir = output_dir / "fake"

    if clean and output_dir.exists():
        print(f"Cleaning output directory '{output_dir}'...")
        shutil.rmtree(output_dir)

    real_out_dir.mkdir(parents=True, exist_ok=True)
    fake_out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Process REAL category
    real_files: List[Tuple[Path, str]] = []  # (source_path, target_name)
    real_counts_per_folder = distribute_counts(n_real, len(real_subfolders))

    for idx, subfolder in enumerate(real_subfolders):
        folder_path = raw_data_root / subfolder
        available = find_video_files(folder_path)
        available.sort()
        target_count = real_counts_per_folder[idx]

        if not available:
            print(f"[WARNING] No video files found in real subfolder '{subfolder}' ({folder_path})")
            continue

        rng = random.Random(seed + idx)
        sampled = rng.sample(available, min(target_count, len(available)))
        for src in sampled:
            real_files.append((src, src.name))

        print(f"  [Real] {subfolder}: sampled {len(sampled)} / {target_count} target (available: {len(available)})")

    # 2. Process FAKE category
    fake_files: List[Tuple[Path, str]] = []  # (source_path, target_name)
    fake_counts_per_folder = distribute_counts(n_fake, len(fake_subfolders))

    for idx, subfolder in enumerate(fake_subfolders):
        folder_path = raw_data_root / subfolder
        available = find_video_files(folder_path)
        available.sort()
        target_count = fake_counts_per_folder[idx]

        if not available:
            print(f"[WARNING] No video files found in fake subfolder '{subfolder}' ({folder_path})")
            continue

        rng = random.Random(seed + 1000 + idx)
        sampled = rng.sample(available, min(target_count, len(available)))
        for src in sampled:
            # Prefix with subfolder name to avoid name collisions across fake algorithms
            target_name = f"{subfolder}_{src.name}"
            fake_files.append((src, target_name))

        print(f"  [Fake] {subfolder}: sampled {len(sampled)} / {target_count} target (available: {len(available)})")

    # 3. Copy files to destination
    print("\nCopying real video subset...")
    for src, target_name in real_files:
        dest = real_out_dir / target_name
        shutil.copy2(src, dest)

    print("Copying fake video subset...")
    for src, target_name in fake_files:
        dest = fake_out_dir / target_name
        shutil.copy2(src, dest)

    print("\n[SUCCESS] Subset generation complete!")
    print(f"  Real videos in subset: {len(real_files)} -> {real_out_dir}")
    print(f"  Fake videos in subset: {len(fake_files)} -> {fake_out_dir}")


def main():
    repo_root = Path(__file__).resolve().parent.parent.parent
    default_config = repo_root / "eval" / "config" / "data_paths.yaml"
    default_output = repo_root / "eval" / "data" / "video_subset"

    parser = argparse.ArgumentParser(description="Create stratified subset of FaceForensics++ c23 dataset.")
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config,
        help=f"Path to data_paths.yaml configuration file (default: {default_config})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output,
        help=f"Target directory for output subset (default: {default_output})",
    )
    parser.add_argument(
        "--n-real",
        type=int,
        default=150,
        help="Number of real videos to include in subset (default: 150)",
    )
    parser.add_argument(
        "--n-fake",
        type=int,
        default=150,
        help="Number of fake videos to include in subset (default: 150)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for sampling reproducibility (default: 42)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove existing output directory before building subset",
    )

    args = parser.parse_args()
    build_subset(
        config_path=args.config,
        output_dir=args.output_dir,
        n_real=args.n_real,
        n_fake=args.n_fake,
        seed=args.seed,
        clean=args.clean,
    )


if __name__ == "__main__":
    main()
