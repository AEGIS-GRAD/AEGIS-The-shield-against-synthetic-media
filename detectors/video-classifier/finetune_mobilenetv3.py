#!/usr/bin/env python3
"""
finetune_mobilenetv3.py
───────────────────────
Fine-tunes MobileNetV3-Small on the FaceForensics++ (C23) dataset.

What this script does, step by step:
  1. Reads D:/archive/FaceForensics++_C23 via eval/config/data_paths.yaml
  2. Walks every video in each real/fake subfolder
  3. Extracts frames (sampled every N frames) and crops faces using MTCNN
  4. Splits data into train / validation sets (80/20 by default)
  5. Fine-tunes torchvision MobileNetV3-Small from ImageNet weights
  6. Saves the best checkpoint to:
       detectors/video-classifier/mobilenetv3_small_ffpp.pth
  7. Writes a training log CSV to:
       detectors/video-classifier/finetune_log.csv

Usage:
    python finetune_mobilenetv3.py [options]

Key options (all have sensible defaults):
    --config        Path to data_paths.yaml  (default: auto-detected)
    --output        Where to save .pth file  (default: mobilenetv3_small_ffpp.pth)
    --epochs        Number of training epochs (default: 10)
    --batch-size    Frames per mini-batch    (default: 32)
    --lr            Learning rate            (default: 1e-4)
    --frames-per-video  Frames sampled per video (default: 8)
    --val-split     Fraction held out for validation (default: 0.2)
    --seed          Random seed              (default: 42)
    --device        cuda / cpu / mps         (default: auto)
    --resume        Path to existing .pth to resume from
    --max-videos    Cap total videos (useful for quick smoke-tests)
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
import torch
import torch.nn as nn
import torchvision.models as tv_models
import torchvision.transforms as T
from torch.utils.data import DataLoader, Dataset

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("finetune")

# ─── Optional MTCNN face detector ─────────────────────────────────────────────
try:
    from facenet_pytorch import MTCNN
    HAS_MTCNN = True
except ImportError:
    MTCNN = None
    HAS_MTCNN = False
    log.warning(
        "facenet-pytorch not installed – face cropping will fall back to a "
        "center-square crop. Install with:  pip install facenet-pytorch"
    )

# ─── Optional PyYAML ──────────────────────────────────────────────────────────
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
LABEL_REAL = 0
LABEL_FAKE = 1
IMG_SIZE = (224, 224)
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD  = [0.229, 0.224, 0.225]


# ──────────────────────────────────────────────────────────────────────────────
# Config loader
# ──────────────────────────────────────────────────────────────────────────────

def load_config(config_path: Path) -> dict:
    """Load data_paths.yaml. Falls back to a simple line parser if PyYAML is absent."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found: {config_path}\n"
            "Make sure eval/config/data_paths.yaml exists and points to your dataset."
        )
    if HAS_YAML:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError("data_paths.yaml must be a YAML dictionary at the top level.")
        return data

    log.warning("PyYAML not found – using built-in YAML parser (limited).")
    cfg: dict = {"raw_data_root": "", "categories": {"real": [], "fake": []}}
    current_cat: Optional[str] = None
    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("raw_data_root:"):
                cfg["raw_data_root"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("real:"):
                current_cat = "real"
            elif line.startswith("fake:"):
                current_cat = "fake"
            elif line.startswith("- ") and current_cat in ("real", "fake"):
                cfg["categories"][current_cat].append(line[2:].strip().strip('"').strip("'"))
    return cfg


# ──────────────────────────────────────────────────────────────────────────────
# Frame extraction + face cropping
# ──────────────────────────────────────────────────────────────────────────────

class FaceExtractor:
    """Extracts face-cropped frames from a video file."""

    def __init__(self, device: str = "cpu"):
        self.device = device
        self.mtcnn = None
        if HAS_MTCNN:
            try:
                self.mtcnn = MTCNN(
                    keep_all=False,
                    select_largest=True,
                    device=device,
                    post_process=False,
                )
                log.info("MTCNN face detector initialised on device '%s'.", device)
            except Exception as exc:
                log.warning("MTCNN init failed (%s) – falling back to center crop.", exc)

    def _center_crop(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        s = min(h, w)
        y0 = (h - s) // 2
        x0 = (w - s) // 2
        return frame[y0 : y0 + s, x0 : x0 + s]

    def _detect_face(self, frame_rgb: np.ndarray) -> np.ndarray:
        if self.mtcnn is not None:
            try:
                boxes, _ = self.mtcnn.detect(frame_rgb)
                if boxes is not None and len(boxes) > 0:
                    b = boxes[0].astype(int)
                    h, w = frame_rgb.shape[:2]
                    x1, y1 = max(0, b[0]), max(0, b[1])
                    x2, y2 = min(w, b[2]), min(h, b[3])
                    if x2 > x1 and y2 > y1:
                        return frame_rgb[y1:y2, x1:x2]
            except Exception:
                pass
        return self._center_crop(frame_rgb)

    def extract(self, video_path: Path, n_frames: int = 8) -> List[np.ndarray]:
        """Sample n_frames evenly from video, detect and return face crops."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            log.warning("Cannot open video: %s", video_path)
            return []

        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            cap.release()
            return []

        indices = set(int(i * total / n_frames) for i in range(n_frames))
        faces: List[np.ndarray] = []
        frame_idx = 0

        while cap.isOpened():
            ret, frame_bgr = cap.read()
            if not ret:
                break
            if frame_idx in indices:
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                face = self._detect_face(frame_rgb)
                faces.append(face)
            frame_idx += 1

        cap.release()
        return faces


# ──────────────────────────────────────────────────────────────────────────────
# Dataset
# ──────────────────────────────────────────────────────────────────────────────

class FFPPFrameDataset(Dataset):
    """Each item is (tensor[3,224,224], label) where label is 0=real, 1=fake.
    Face images are loaded on-demand from disk (.npy files) to keep RAM usage minimal."""

    def __init__(self, samples: List[Tuple[Path, int]], transform=None):
        self.samples = samples
        self.transform = transform

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int):
        crop_path, label = self.samples[idx]
        face_np = np.load(crop_path)
        face_np = cv2.resize(face_np, IMG_SIZE, interpolation=cv2.INTER_LINEAR)
        if self.transform is not None:
            img = self.transform(face_np)
        else:
            img = torch.from_numpy(face_np).permute(2, 0, 1).float() / 255.0
        return img, label


def build_transform(augment: bool = True) -> T.Compose:
    ops = []
    if augment:
        ops += [
            T.ToPILImage(),
            T.RandomHorizontalFlip(p=0.5),
            T.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1),
            T.ToTensor(),
        ]
    else:
        ops += [T.ToPILImage(), T.ToTensor()]
    ops.append(T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD))
    return T.Compose(ops)


# ──────────────────────────────────────────────────────────────────────────────
# Model
# ──────────────────────────────────────────────────────────────────────────────

def build_model(resume: Optional[Path], device: str) -> nn.Module:
    """MobileNetV3-Small with a 2-class head (real / fake)."""
    try:
        model = tv_models.mobilenet_v3_small(
            weights=tv_models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
        )
    except AttributeError:
        model = tv_models.mobilenet_v3_small(pretrained=True)

    # Replace ImageNet head (1000 classes) with binary head (2 classes)
    in_features = model.classifier[3].in_features
    model.classifier[3] = nn.Linear(in_features, 2)

    if resume is not None:
        if not resume.exists():
            log.error("--resume path does not exist: %s", resume)
            sys.exit(1)
        state = torch.load(resume, map_location=device)
        if isinstance(state, dict) and "state_dict" in state:
            state = state["state_dict"]
        elif isinstance(state, dict) and "model" in state:
            state = state["model"]
        try:
            model.load_state_dict(state)
        except RuntimeError:
            state = {(k[7:] if k.startswith("module.") else k): v for k, v in state.items()}
            model.load_state_dict(state)
        log.info("Resumed from checkpoint: %s", resume)

    return model.to(device)


# ──────────────────────────────────────────────────────────────────────────────
# Data loading from FaceForensics++
# ──────────────────────────────────────────────────────────────────────────────

def collect_samples(
    data_root: Path,
    real_subfolders: List[str],
    fake_subfolders: List[str],
    extractor: FaceExtractor,
    frames_per_video: int,
    max_videos: Optional[int],
    seed: int,
    cache_dir: Path,
) -> List[Tuple[Path, int]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    all_videos: List[Tuple[Path, int]] = []

    for folder_name in real_subfolders:
        folder = data_root / folder_name
        if not folder.is_dir():
            log.warning("[Real] Subfolder not found – skipping: %s", folder)
            continue
        vids = [p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTENSIONS]
        log.info("[Real] %s: found %d videos.", folder_name, len(vids))
        all_videos.extend((v, LABEL_REAL) for v in vids)

    for folder_name in fake_subfolders:
        folder = data_root / folder_name
        if not folder.is_dir():
            log.warning("[Fake] Subfolder not found – skipping: %s", folder)
            continue
        vids = [p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTENSIONS]
        log.info("[Fake] %s: found %d videos.", folder_name, len(vids))
        all_videos.extend((v, LABEL_FAKE) for v in vids)

    if not all_videos:
        log.error(
            "No videos found under %s.\n"
            "Check that data_paths.yaml points to the correct directory "
            "and that the subfolder names match what is on disk.",
            data_root,
        )
        sys.exit(1)

    if max_videos is not None and len(all_videos) > max_videos:
        rng = random.Random(seed)
        all_videos = rng.sample(all_videos, max_videos)
        log.info("Video count capped to %d (--max-videos).", max_videos)

    log.info("Total videos to process: %d", len(all_videos))
    log.info("Frame cache directory: %s", cache_dir)
    samples: List[Tuple[Path, int]] = []
    cached_count = 0
    new_extracted_count = 0

    for i, (vid_path, label) in enumerate(all_videos, start=1):
        label_str = "real" if label == LABEL_REAL else "fake"
        vid_rel = str(vid_path.relative_to(data_root))
        vid_hash = hashlib.md5(vid_rel.encode("utf-8")).hexdigest()[:10]

        # Check if crop files already exist in cache
        expected_crops = [
            cache_dir / f"{vid_path.stem}_{vid_hash}_f{f_idx}.npy"
            for f_idx in range(frames_per_video)
        ]

        existing_crops = [p for p in expected_crops if p.exists()]
        if len(existing_crops) == frames_per_video:
            for crop_p in existing_crops:
                samples.append((crop_p, label))
            cached_count += 1
            if i % 200 == 0 or i == 1:
                log.info("  [Cached] Video %d / %d  [%s]", i, len(all_videos), label_str)
            continue

        if i % 50 == 0 or i == 1:
            log.info(
                "  Extracting video %d / %d  [%s] (Cached so far: %d)",
                i, len(all_videos), label_str, cached_count,
            )

        faces = extractor.extract(vid_path, n_frames=frames_per_video)
        for f_idx, face in enumerate(faces):
            crop_p = cache_dir / f"{vid_path.stem}_{vid_hash}_f{f_idx}.npy"
            np.save(crop_p, face)
            samples.append((crop_p, label))

        new_extracted_count += 1
        if new_extracted_count % 100 == 0:
            gc.collect()

    log.info(
        "Frame extraction complete. Total face samples: %d (From cache: %d / %d videos)",
        len(samples), cached_count, len(all_videos),
    )
    return samples


# ──────────────────────────────────────────────────────────────────────────────
# Train / eval loops
# ──────────────────────────────────────────────────────────────────────────────

def run_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer,
    device: str,
    is_train: bool,
) -> Tuple[float, float]:
    model.train(is_train)
    total_loss = 0.0
    correct = 0
    total = 0

    with torch.set_grad_enabled(is_train):
        for images, labels in loader:
            images = images.to(device)
            labels = labels.to(device)
            logits = model(images)
            loss = criterion(logits, labels)

            if is_train and optimizer is not None:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            total_loss += loss.item() * images.size(0)
            preds = logits.argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += images.size(0)

    avg_loss = total_loss / max(total, 1)
    accuracy = 100.0 * correct / max(total, 1)
    return avg_loss, accuracy


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    repo_root = here.parent.parent
    default_config = repo_root / "eval" / "config" / "data_paths.yaml"
    # The model is consumed by engine/edge_model/build_edge_model.py — save there.
    default_output = repo_root / "engine" / "edge_model" / "mobilenetv3_small_ffpp.pth"
    default_log    = here / "finetune_log.csv"
    default_cache  = here / ".frame_cache"

    p = argparse.ArgumentParser(
        description="Fine-tune MobileNetV3-Small on FaceForensics++ C23.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--config",           type=Path,  default=default_config)
    p.add_argument("--output",           type=Path,  default=default_output)
    p.add_argument("--log-csv",          type=Path,  default=default_log)
    p.add_argument("--cache-dir",        type=Path,  default=default_cache,
                   help="Directory to save/load extracted face crops (.npy files)")
    p.add_argument("--epochs",           type=int,   default=10)
    p.add_argument("--batch-size",       type=int,   default=32)
    p.add_argument("--lr",               type=float, default=1e-4)
    p.add_argument("--frames-per-video", type=int,   default=8)
    p.add_argument("--val-split",        type=float, default=0.2)
    p.add_argument("--seed",             type=int,   default=42)
    p.add_argument("--device",           type=str,   default=None,
                   help="cuda | cpu | mps  (default: auto-detect)")
    p.add_argument("--resume",           type=Path,  default=None,
                   help="Existing .pth checkpoint to resume fine-tuning from")
    p.add_argument("--max-videos",       type=int,   default=None,
                   help="Cap total videos processed (handy for quick smoke-tests)")
    p.add_argument("--workers",          type=int,   default=0,
                   help="DataLoader worker processes (0 = main thread, recommended on Windows)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Device
    if args.device:
        device = args.device
    elif torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    log.info("Using device: %s", device)

    # Reproducibility
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if device == "cuda":
        torch.cuda.manual_seed_all(args.seed)

    # Load config
    log.info("Loading dataset config: %s", args.config)
    cfg = load_config(args.config)
    data_root = Path(cfg["raw_data_root"])
    real_subs = cfg.get("categories", {}).get("real", ["original"])
    fake_subs = cfg.get("categories", {}).get("fake", [
        "Deepfakes", "Face2Face", "FaceShifter",
        "FaceSwap", "NeuralTextures", "DeepFakeDetection",
    ])

    log.info("Dataset root : %s", data_root)
    log.info("Real folders : %s", real_subs)
    log.info("Fake folders : %s", fake_subs)

    if not data_root.exists():
        log.error(
            "Dataset root does not exist: %s\n"
            "Please update eval/config/data_paths.yaml with the correct path.",
            data_root,
        )
        sys.exit(1)

    # Extract frames
    # Use CPU for MTCNN even on CUDA systems to avoid tensor device mismatches
    extractor = FaceExtractor(device="cpu")
    log.info(
        "Extracting %d frames per video. This may take a while...",
        args.frames_per_video,
    )
    samples = collect_samples(
        data_root=data_root,
        real_subfolders=real_subs,
        fake_subfolders=fake_subs,
        extractor=extractor,
        frames_per_video=args.frames_per_video,
        max_videos=args.max_videos,
        seed=args.seed,
        cache_dir=args.cache_dir,
    )

    if not samples:
        log.error("No samples collected. Aborting.")
        sys.exit(1)

    # Train / Val split
    rng = random.Random(args.seed)
    rng.shuffle(samples)
    n_val = int(len(samples) * args.val_split)
    val_samples   = samples[:n_val]
    train_samples = samples[n_val:]

    log.info(
        "Train: %d samples | Val: %d samples",
        len(train_samples), len(val_samples),
    )

    train_ds = FFPPFrameDataset(train_samples, transform=build_transform(augment=True))
    val_ds   = FFPPFrameDataset(val_samples,   transform=build_transform(augment=False))

    train_loader = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True,
        num_workers=args.workers, pin_memory=(device == "cuda"),
    )
    val_loader = DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False,
        num_workers=args.workers, pin_memory=(device == "cuda"),
    )

    # Model, loss, optimiser, scheduler
    model     = build_model(resume=args.resume, device=device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.epochs, eta_min=1e-6
    )

    # CSV log
    args.log_csv.parent.mkdir(parents=True, exist_ok=True)
    csv_file = open(args.log_csv, "w", newline="", encoding="utf-8")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["epoch", "train_loss", "train_acc", "val_loss", "val_acc", "lr", "elapsed_s"])
    log.info("Training log -> %s", args.log_csv)

    # Training loop
    best_val_acc = -1.0
    best_epoch   = -1
    output_path  = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("=" * 60)
    log.info("Starting fine-tuning for %d epoch(s).", args.epochs)
    log.info("Best checkpoint -> %s", output_path)
    log.info("=" * 60)

    t_start = time.time()

    for epoch in range(1, args.epochs + 1):
        ep_start = time.time()

        train_loss, train_acc = run_epoch(
            model, train_loader, criterion, optimizer, device, is_train=True
        )
        val_loss, val_acc = run_epoch(
            model, val_loader, criterion, None, device, is_train=False
        )
        scheduler.step()

        elapsed = time.time() - ep_start
        current_lr = scheduler.get_last_lr()[0]

        log.info(
            "Epoch %2d/%d | Train Loss %.4f Acc %.2f%% | Val Loss %.4f Acc %.2f%% | LR %.2e | %.1fs",
            epoch, args.epochs,
            train_loss, train_acc,
            val_loss,   val_acc,
            current_lr, elapsed,
        )

        csv_writer.writerow([
            epoch, f"{train_loss:.4f}", f"{train_acc:.2f}",
            f"{val_loss:.4f}", f"{val_acc:.2f}",
            f"{current_lr:.2e}", f"{elapsed:.1f}",
        ])
        csv_file.flush()

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_epoch   = epoch
            torch.save(model.state_dict(), output_path)
            log.info("  [+] New best val acc %.2f%% -> saved checkpoint.", best_val_acc)

    total_time = time.time() - t_start
    csv_file.close()

    log.info("=" * 60)
    log.info("Fine-tuning complete.")
    log.info("Best Val Acc : %.2f%% at epoch %d", best_val_acc, best_epoch)
    log.info("Model saved  : %s", output_path)
    log.info("Log CSV      : %s", args.log_csv)
    log.info("Total time   : %.1f minutes", total_time / 60)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
