#!/usr/bin/env python3
"""AEGIS Multi-Detector Weight Verification and Setup Script.

Ensures all detector model weights are downloaded and verified before launching Docker Compose.
Run this script once after cloning the repository:
    python scripts/setup_models.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Models configuration: (Detector Name, Target Path, Optional HuggingFace Repo ID, Optional Filename)
MODELS_CONFIG = [
    {
        "name": "Video Classifier (DF40 Fine-tuned)",
        "path": REPO_ROOT / "detectors" / "video-classifier" / "models" / "efficientnet_b0_df40_finetuned.pth",
        "description": "Primary spatial artifact detector trained on 27 DF40 methods (15.6 MB)",
        "hf_repo": None,
        "hf_filename": None,
    },
    {
        "name": "AASIST Audio Detector",
        "path": REPO_ROOT / "detectors" / "aasist" / "AASIST.pth",
        "description": "Audio spoofing graph attention network (1.3 MB)",
        "hf_repo": None,
        "hf_filename": None,
    },
    {
        "name": "Image Detector (Community Forensics)",
        "path": REPO_ROOT / "detectors" / "image" / "weights" / "model.safetensors",
        "description": "ViT-Small 384x384 image deepfake detector (87.3 MB)",
        "hf_repo": "OwensLab/commfor-model-384",
        "hf_filename": "model.safetensors",
    },
    {
        "name": "Text Detector (Desklib Base)",
        "path": REPO_ROOT / "detectors" / "text-detector" / "models" / "desklib-base" / "model.safetensors",
        "description": "DeBERTa-v3 synthetic text detector (1.7 GB)",
        "hf_repo": "desklib/ai-text-detector-v1.01",
        "hf_filename": None,  # Requires full snapshot
    },
]


def check_and_download_models():
    print("=" * 70)
    print("🛡️  AEGIS Detector Models Pre-Flight Verification")
    print("=" * 70)

    try:
        from huggingface_hub import hf_hub_download, snapshot_download
        has_hf = True
    except ImportError:
        has_hf = False

    all_ready = True
    summary = []

    for entry in MODELS_CONFIG:
        name = entry["name"]
        target_path: Path = entry["path"]
        desc = entry["description"]
        hf_repo = entry["hf_repo"]
        hf_filename = entry["hf_filename"]

        if target_path.exists():
            size_mb = target_path.stat().st_size / (1024 * 1024)
            print(f"[READY] {name}: Found ({size_mb:.2f} MB)")
            summary.append((name, "READY", f"{size_mb:.2f} MB"))
            continue

        print(f"[MISSING] {name}: Not found at {target_path}")

        if hf_repo and has_hf:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"          Attempting download from HuggingFace ({hf_repo})...")
            try:
                if hf_filename:
                    downloaded = hf_hub_download(repo_id=hf_repo, filename=hf_filename)
                    import shutil
                    shutil.copyfile(downloaded, target_path)
                else:
                    snapshot_download(
                        repo_id=hf_repo,
                        local_dir=str(target_path.parent),
                        local_dir_use_symlinks=False,
                    )
                size_mb = target_path.stat().st_size / (1024 * 1024)
                print(f"[DOWNLOADED] {name}: Successfully retrieved ({size_mb:.2f} MB)")
                summary.append((name, "DOWNLOADED", f"{size_mb:.2f} MB"))
                continue
            except Exception as e:
                print(f"[ERROR] Failed to download {name} from HuggingFace: {e}")
                summary.append((name, "FAILED", str(e)))
                all_ready = False
        else:
            if not has_hf and hf_repo:
                print(f"          huggingface_hub not installed. Run 'pip install huggingface_hub' to auto-download.")
            summary.append((name, "MISSING", "Not found locally"))
            all_ready = False

    print("\n" + "=" * 70)
    print("📋 Summary of Models:")
    print("-" * 70)
    for name, status, details in summary:
        print(f" - {name:<35} : [{status}] {details}")
    print("=" * 70)

    if all_ready:
        print("\n✅ All models are verified and ready!")
        print("   You can now launch the full stack with:")
        print("   $ docker compose up --build -d\n")
    else:
        print("\n⚠️  Some models are missing. Please ensure all required weights exist before launching.")


if __name__ == "__main__":
    check_and_download_models()
