#!/usr/bin/env python3
"""
finetune_efficientnet.py
─────────────────────────
Fine-tunes EfficientNet-B0 on the FaceForensics++ (C23) dataset.

Mirrors finetune_mobilenetv3.py in its data pipeline, but uses EfficientNet-B0
as the backbone. Designed to resume from the existing community checkpoint
(Xicor9/efficientnet-b0-ffpp-c23 → efficientnet_b0_ffpp_c23.pth) or any
prior fine-tuning checkpoint.

What this script does, step by step:
  1. Reads D:/archive/FaceForensics++_C23 via eval/config/data_paths.yaml
  2. Walks every video in each real/fake subfolder
  3. Extracts frames (sampled every N frames) and crops faces using MTCNN
     (falls back to center-crop if facenet-pytorch is not installed)
  4. Splits data into train / validation sets (80/20 by default)
  5. Fine-tunes torchvision EfficientNet-B0 from an existing checkpoint
  6. Saves per-epoch checkpoints every --checkpoint-every epochs so training
     can be interrupted and resumed without losing progress
  7. Saves the best validation-accuracy checkpoint to:
       engine/edge_model/efficientnet_b0_ffpp_finetuned.pth
  8. Writes a training log CSV to:
       detectors/video-classifier/finetune_efficientnet_log.csv

Usage:
    # Resume from the existing community checkpoint (recommended):
    D:\\Gpu-shit\\nasa\\Scripts\\python.exe detectors\\video-classifier\\finetune_efficientnet.py \
        --resume detectors\\video-classifier\\efficientnet_b0_ffpp_c23.pth \
        --epochs 10 --batch-size 32 --lr 5e-5 --checkpoint-every 2

    # Resume from a mid-training epoch-4 checkpoint:
    D:\\Gpu-shit\\nasa\\Scripts\\python.exe detectors\\video-classifier\\finetune_efficientnet.py \
        --resume engine\\edge_model\\efficientnet_b0_ffpp_ckpt_ep4.pth --epochs 10

    # Quick smoke test (limit to 20 videos):
    D:\\Gpu-shit\\nasa\\Scripts\\python.exe detectors\\video-classifier\\finetune_efficientnet.py \
        --max-videos 20 --epochs 2
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
log = logging.getLogger("finetune_efficientnet")

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
# Config loader (identical to finetune_mobilenetv3.py)
# ──────────────────────────────────────────────────────────────────────────────

def load_config(config_path: Path) -> dict:
    """Load data_paths.yaml. Falls back to a simple line parser if PyYAML is absent."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found: {config_path}\n"
            "Make sure eval/config/data_paths.yaml exists and points to your dataset."
        )
    if HAS_YAML:
        with open(config_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            if not isinstance(data, dict):
                raise ValueError("data_paths.yaml must be a YAML dictionary at the top level.")
            return data
    # Minimal fallback parser
    cfg: dict = {"raw_data_root": "", "categories": {"real": [], "fake": []}}
    current_cat: Optional[str] = None
    with open(config_path, "r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("raw_data_root:"):
                cfg["raw_data_root"] = s.split(":", 1)[1].strip().strip('"').strip("'")
            elif s == "real:":
                current_cat = "real"
            elif s == "fake:":
                current_cat = "fake"
            elif s.startswith("- ") and current_cat:
                cfg["categories"][current_cat].append(s[2:].strip().strip('"').strip("'"))
    return cfg


# ──────────────────────────────────────────────────────────────────────────────
# Face Extractor (identical to finetune_mobilenetv3.py)
# ──────────────────────────────────────────────────────────────────────────────

class FaceExtractor:
    """Extracts face crops from a video file using MTCNN (with center-crop fallback)."""

    def __init__(self, device: str = "cpu"):
        self.mtcnn = None
        if HAS_MTCNN:
            try:
                self.mtcnn = MTCNN(
                    image_size=224, margin=20, min_face_size=40,
                    thresholds=[0.6, 0.7, 0.7], keep_all=False, device=device,
                )
                log.info("MTCNN face detector initialised on device '%s'.", device)
            except Exception as exc:
                log.warning("MTCNN init failed (%s) – falling back to center crop.", exc)

    def _center_crop(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        s = min(h, w)
        y0 = (h - s) // 2
        x0 = (w - s) // 2
        return frame[y0: y0 + s, x0: x0 + s]

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
    """Each item is (tensor[3,224,224], label) where label is 0=real, 1=fake."""

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
# Focal Loss
# ──────────────────────────────────────────────────────────────────────────────

class FocalLoss(nn.Module):
    """Focal Loss — focuses training on hard, misclassified examples.

    Reference: Lin et al., "Focal Loss for Dense Object Detection" (ICCV 2017).
    gamma=0 -> vanilla CrossEntropy.  gamma=2 -> standard focal loss setting.
    """

    def __init__(self, gamma: float = 2.0, weight: Optional[torch.Tensor] = None):
        super().__init__()
        self.gamma = gamma
        self.ce = nn.CrossEntropyLoss(weight=weight, reduction="none")

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        ce_loss = self.ce(logits, targets)
        pt = torch.exp(-ce_loss)
        focal_loss = ((1 - pt) ** self.gamma) * ce_loss
        return focal_loss.mean()


# ──────────────────────────────────────────────────────────────────────────────
# Model builder
# ──────────────────────────────────────────────────────────────────────────────

def build_model(resume: Optional[Path], device: str) -> nn.Module:
    """EfficientNet-B0 with a 2-class head (real=0 / fake=1).

    If --resume points to the Xicor9 community checkpoint or any prior
    fine-tuning checkpoint, it loads those weights before training starts.
    """
    try:
        model = tv_models.efficientnet_b0(weights=tv_models.EfficientNet_B0_Weights.DEFAULT)
    except AttributeError:
        model = tv_models.efficientnet_b0(pretrained=True)

    in_features = model.classifier[1].in_features
    model.classifier[1] = nn.Linear(in_features, 2)

    if resume is not None:
        if not resume.exists():
            log.error("--resume path does not exist: %s", resume)
            sys.exit(1)
        state = torch.load(str(resume), map_location=device)
        if isinstance(state, dict):
            # Full checkpoint dict (from our own checkpoint saving)
            if "model_state_dict" in state:
                log.info("Resuming from full checkpoint dict (epoch %d, best_val=%.2f%%)",
                         state.get("epoch", "?"), state.get("best_val_acc", 0.0))
                state = state["model_state_dict"]
            elif "state_dict" in state:
                state = state["state_dict"]
            elif "model" in state:
                state = state["model"]
        try:
            model.load_state_dict(state)
            log.info("Resumed from checkpoint: %s", resume)
        except RuntimeError as e:
            log.warning("Strict load failed (%s). Trying non-strict...", e)
            try:
                model.load_state_dict(state, strict=False)
                log.info("Non-strict checkpoint load succeeded.")
            except RuntimeError:
                state2 = {(k[7:] if k.startswith("module.") else k): v for k, v in state.items()}
                model.load_state_dict(state2)
                log.info("Checkpoint loaded after stripping 'module.' prefix.")
    else:
        log.info("No --resume checkpoint provided. Training from ImageNet weights only.")

    return model.to(device)


# ──────────────────────────────────────────────────────────────────────────────
# Data collection from FaceForensics++
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
            log.warning("[Real] Subfolder not found - skipping: %s", folder)
            continue
        vids = [p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTENSIONS]
        log.info("[Real] %s: found %d videos.", folder_name, len(vids))
        all_videos.extend((v, LABEL_REAL) for v in vids)

    for folder_name in fake_subfolders:
        folder = data_root / folder_name
        if not folder.is_dir():
            log.warning("[Fake] Subfolder not found - skipping: %s", folder)
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
    epoch: int = 1,
    total_epochs: int = 10,
) -> Tuple[float, float]:
    model.train(is_train)
    total_loss = 0.0
    correct = 0
    total = 0
    n_batches = len(loader)
    phase_str = "Train" if is_train else "Val"

    with torch.set_grad_enabled(is_train):
        for b_idx, (images, labels) in enumerate(loader, start=1):
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

            # Print progress every 200 batches so the console doesn't feel stuck
            if b_idx % 200 == 0 or b_idx == n_batches:
                curr_acc = 100.0 * correct / max(total, 1)
                curr_loss = total_loss / max(total, 1)
                log.info(
                    "  [%s Ep %d/%d] Batch %4d / %4d (%5.1f%%) | Loss: %.4f | Acc: %.2f%%",
                    phase_str, epoch, total_epochs, b_idx, n_batches,
                    100.0 * b_idx / n_batches, curr_loss, curr_acc,
                )

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
    default_output = here / "models" / "efficientnet_b0_ffpp_finetuned.pth"
    default_log    = here / "models" / "finetune_efficientnet_log.csv"
    # Reuse the existing .frame_cache from MobileNet if present to avoid re-extracting 7,000 videos
    existing_cache = here / ".frame_cache"
    default_cache  = existing_cache if existing_cache.exists() else (here / ".frame_cache_efficientnet")

    p = argparse.ArgumentParser(
        description="Fine-tune EfficientNet-B0 on FaceForensics++ C23.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--config",           type=Path,  default=default_config)
    p.add_argument("--resume",           type=Path,  default=None,
                   help="Existing .pth to resume from (e.g. efficientnet_b0_ffpp_c23.pth)")
    p.add_argument("--output",           type=Path,  default=default_output)
    p.add_argument("--log-csv",          type=Path,  default=default_log)
    p.add_argument("--cache-dir",        type=Path,  default=default_cache)
    p.add_argument("--checkpoint-dir",   type=Path,  default=None,
                   help="Dir for per-epoch checkpoints (default: same dir as --output)")
    p.add_argument("--checkpoint-every", type=int,   default=2,
                   help="Save a checkpoint every N epochs (0 = never)")
    p.add_argument("--epochs",           type=int,   default=10)
    p.add_argument("--batch-size",       type=int,   default=32)
    p.add_argument("--lr",               type=float, default=5e-5)
    p.add_argument("--frames-per-video", type=int,   default=8)
    p.add_argument("--val-split",        type=float, default=0.2)
    p.add_argument("--seed",             type=int,   default=42)
    p.add_argument("--device",           type=str,   default=None)
    p.add_argument("--max-videos",       type=int,   default=None)
    p.add_argument("--workers",          type=int,   default=0)
    p.add_argument("--use-focal-loss",   action="store_true", default=True)
    p.add_argument("--focal-gamma",      type=float, default=2.0)
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
    if not data_root.exists():
        log.error(
            "Dataset root does not exist: %s\n"
            "Please update eval/config/data_paths.yaml with the correct path.",
            data_root,
        )
        sys.exit(1)

    checkpoint_dir = args.checkpoint_dir or args.output.parent
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Extract frames
    extractor = FaceExtractor(device="cpu")
    log.info("Extracting %d frames per video...", args.frames_per_video)
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
    log.info("Train: %d samples | Val: %d samples", len(train_samples), len(val_samples))

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

    # Model, loss, optimizer, scheduler
    model = build_model(resume=args.resume, device=device)

    if args.use_focal_loss:
        log.info("Using Focal Loss with gamma=%.1f", args.focal_gamma)
        criterion = FocalLoss(gamma=args.focal_gamma)
    else:
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
    csv_file.flush()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    best_val_acc = 0.0

    log.info("=" * 70)
    log.info("Starting EfficientNet-B0 fine-tuning  (%d epochs)", args.epochs)
    log.info("  Checkpoint every %d epoch(s) → %s/", args.checkpoint_every, checkpoint_dir)
    log.info("  Best model      → %s", args.output)
    log.info("  Training log    → %s", args.log_csv)
    log.info("=" * 70)

    for epoch in range(1, args.epochs + 1):
        t0 = time.perf_counter()

        train_loss, train_acc = run_epoch(
            model, train_loader, criterion, optimizer, device, is_train=True,
            epoch=epoch, total_epochs=args.epochs,
        )
        val_loss, val_acc = run_epoch(
            model, val_loader, criterion, None, device, is_train=False,
            epoch=epoch, total_epochs=args.epochs,
        )
        scheduler.step()
        elapsed = time.perf_counter() - t0
        current_lr = scheduler.get_last_lr()[0]

        log.info(
            "Epoch %2d/%d | Train loss=%.4f acc=%.2f%%  | "
            "Val loss=%.4f acc=%.2f%%  | LR=%.2e  | %.1fs",
            epoch, args.epochs,
            train_loss, train_acc,
            val_loss, val_acc,
            current_lr, elapsed,
        )

        csv_writer.writerow([
            epoch,
            f"{train_loss:.4f}", f"{train_acc:.2f}",
            f"{val_loss:.4f}", f"{val_acc:.2f}",
            f"{current_lr:.2e}", f"{elapsed:.1f}",
        ])
        csv_file.flush()

        # Save best model (weights only — lightweight)
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save(model.state_dict(), str(args.output))
            log.info("  ✓ New best val accuracy: %.2f%% → saved to %s", val_acc, args.output)

        # Per-epoch full checkpoint (includes optimizer + scheduler state for clean resume)
        if args.checkpoint_every > 0 and epoch % args.checkpoint_every == 0:
            ckpt_path = checkpoint_dir / f"efficientnet_b0_ffpp_ckpt_ep{epoch}.pth"
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "scheduler_state_dict": scheduler.state_dict(),
                "val_acc": val_acc,
                "best_val_acc": best_val_acc,
                "args": vars(args),
            }, str(ckpt_path))
            log.info("  [CKPT] Epoch checkpoint saved: %s", ckpt_path)

        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()

    csv_file.close()

    log.info("=" * 70)
    log.info("Training complete.")
    log.info("  Best validation accuracy : %.2f%%", best_val_acc)
    log.info("  Best model saved to      : %s", args.output)
    log.info("  Training log written to  : %s", args.log_csv)
    log.info("=" * 70)


if __name__ == "__main__":
    main()
