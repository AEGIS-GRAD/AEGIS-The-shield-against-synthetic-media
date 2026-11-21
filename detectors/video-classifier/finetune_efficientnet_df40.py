"""
AEGIS Video Classifier Fine-Tuning on DF40 & FaceForensics++
Script: finetune_efficientnet_df40.py

Architecture: EfficientNet-B0 (torchvision) with 2-class head
Training data: DF40 (27 training fake methods) + FF++ real frames
Validation data: FF++ real val frames + stratified sample of DF40 val fakes
Held-out data: uniface, wav2lip, VQGAN (never seen during training or model selection)
"""

from __future__ import annotations

import argparse
import csv
import datetime
import gc
import hashlib
import json
import logging
import os
import random
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
import torchvision.models as tv_models
from sklearn.metrics import roc_auc_score, roc_curve, balanced_accuracy_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("finetune_df40")

# ─────────────────────────────────────────────────────────────────────────────
# Constants & Defaults
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_TRAIN_CSV = Path(r"E:\df40_check\manifests\train.csv")
DEFAULT_VAL_CSV = Path(r"E:\df40_check\manifests\val.csv")
DEFAULT_HELDOUT_CSV = Path(r"E:\df40_check\manifests\heldout_methods.csv")
DEFAULT_OUTPUT_DIR = Path(r"D:\DeepFake_Grad\detectors\video-classifier\models")

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 1, 3)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 1, 3)


def sha256_file(path: Path | str) -> str:
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Augmentation Pipeline (Applied identically to Real and Fake)
# ─────────────────────────────────────────────────────────────────────────────

def augment_image_cv2(img_bgr: np.ndarray, rng: random.Random) -> np.ndarray:
    """Applies stochastic augmentations to a 256x256 BGR image."""
    h, w = img_bgr.shape[:2]

    # 1. Horizontal flip (p=0.5)
    if rng.random() < 0.5:
        img_bgr = cv2.flip(img_bgr, 1)

    # 2. JPEG re-compression (p=0.5, quality 40-95)
    if rng.random() < 0.5:
        quality = rng.randint(40, 95)
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        res, enc = cv2.imencode(".jpg", img_bgr, encode_param)
        if res:
            dec = cv2.imdecode(enc, cv2.IMREAD_COLOR)
            if dec is not None:
                img_bgr = dec

    # 3. Gaussian blur (p=0.2, kernel 3 or 5)
    if rng.random() < 0.2:
        k = rng.choice([3, 5])
        img_bgr = cv2.GaussianBlur(img_bgr, (k, k), 0)

    # 4. Random downscale to 50-100% then upscale back (p=0.3)
    if rng.random() < 0.3:
        scale = rng.uniform(0.5, 0.99)
        dw, dh = max(16, int(w * scale)), max(16, int(h * scale))
        down = cv2.resize(img_bgr, (dw, dh), interpolation=cv2.INTER_AREA)
        img_bgr = cv2.resize(down, (w, h), interpolation=cv2.INTER_LINEAR)

    # 5. Gaussian noise (p=0.15)
    if rng.random() < 0.15:
        sigma = rng.uniform(5.0, 20.0)
        noise = np.random.normal(0, sigma, img_bgr.shape).astype(np.float32)
        img_bgr = np.clip(img_bgr.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    # 6. Brightness, contrast, and gamma jitter +-30% (p=0.8)
    if rng.random() < 0.8:
        alpha = rng.uniform(0.7, 1.3)     # contrast
        beta = rng.uniform(-30.0, 30.0)   # brightness
        gamma = rng.uniform(0.7, 1.3)     # gamma
        img_f = np.clip(img_bgr.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)
        inv_gamma = 1.0 / gamma
        lut = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)]).astype(np.uint8)
        img_bgr = cv2.LUT(img_f, lut)

    # 7. Small random scale and rotation ~5% (p=0.3)
    if rng.random() < 0.3:
        angle = rng.uniform(-5.0, 5.0)
        scale = rng.uniform(0.95, 1.05)
        M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, scale)
        img_bgr = cv2.warpAffine(img_bgr, M, (w, h), borderMode=cv2.BORDER_REFLECT)

    return img_bgr


# ─────────────────────────────────────────────────────────────────────────────
# Dataset Classes
# ─────────────────────────────────────────────────────────────────────────────

def worker_init_fn(worker_id: int):
    cv2.setNumThreads(0)


class DF40Dataset(Dataset):
    """Dataset for DF40 and FaceForensics++ frames."""

    def __init__(
        self,
        samples: List[Dict[str, Any]],
        is_training: bool = False,
        crop_size: int = 224,
        seed: int = 42,
    ):
        self.samples = samples
        self.is_training = is_training
        self.crop_size = crop_size
        self.seed = seed

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, int, str, str]:
        row = self.samples[idx]
        path = row["path"]
        label = int(row["label"])
        method = row["method"]
        video_id = row["video_id"]

        # Read image
        img_bgr = cv2.imread(path, cv2.IMREAD_COLOR)
        if img_bgr is None:
            # Fallback black image if read fails
            img_bgr = np.zeros((256, 256, 3), dtype=np.uint8)

        # Ensure 256x256 with cv2.INTER_AREA (crucial for 1024, 512, 259 px)
        if img_bgr.shape[0] != 256 or img_bgr.shape[1] != 256:
            img_bgr = cv2.resize(img_bgr, (256, 256), interpolation=cv2.INTER_AREA)

        # Augmentation (training only)
        if self.is_training:
            rng = random.Random(self.seed + idx * 7)
            img_bgr = augment_image_cv2(img_bgr, rng)
            # Random Crop 224
            max_y = 256 - self.crop_size
            max_x = 256 - self.crop_size
            top = rng.randint(0, max_y)
            left = rng.randint(0, max_x)
            img_crop = img_bgr[top : top + self.crop_size, left : left + self.crop_size]
        else:
            # Centre Crop 224
            top = (256 - self.crop_size) // 2
            left = (256 - self.crop_size) // 2
            img_crop = img_bgr[top : top + self.crop_size, left : left + self.crop_size]

        # Convert BGR to RGB
        img_rgb = cv2.cvtColor(img_crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        # ImageNet normalization: (img - mean) / std
        img_norm = (img_rgb - IMAGENET_MEAN) / IMAGENET_STD
        # HWC -> CHW
        tensor = torch.from_numpy(img_norm.transpose(2, 0, 1)).float()

        return tensor, label, method, video_id


# ─────────────────────────────────────────────────────────────────────────────
# Model Factory
# ─────────────────────────────────────────────────────────────────────────────

def create_efficientnet_b0(init_from: Optional[str] = None) -> nn.Module:
    """Builds EfficientNet-B0 with 2-class head."""
    if init_from and Path(init_from).is_file():
        log.info("Building EfficientNet-B0 initialized from custom weights: %s", init_from)
        model = tv_models.efficientnet_b0(weights=None)
        in_features = model.classifier[1].in_features
        model.classifier[1] = nn.Linear(in_features, 2)
        state_dict = torch.load(init_from, map_location="cpu", weights_only=True)
        if isinstance(state_dict, dict) and "model_state_dict" in state_dict:
            state_dict = state_dict["model_state_dict"]
        model.load_state_dict(state_dict)
    else:
        log.info("Building EfficientNet-B0 with default ImageNet pretrained weights...")
        try:
            model = tv_models.efficientnet_b0(weights=tv_models.EfficientNet_B0_Weights.DEFAULT)
        except Exception:
            model = tv_models.efficientnet_b0(pretrained=True)
        in_features = model.classifier[1].in_features
        model.classifier[1] = nn.Linear(in_features, 2)

    return model


# ─────────────────────────────────────────────────────────────────────────────
# Sampling Functions
# ─────────────────────────────────────────────────────────────────────────────

def sample_train_epoch_records(
    real_records: List[Dict[str, Any]],
    fakes_by_method: Dict[str, List[Dict[str, Any]]],
    seed: int,
) -> List[Dict[str, Any]]:
    """Each epoch: all real train frames + equal number of fakes drawn evenly across the 27 methods."""
    n_real = len(real_records)
    methods = sorted(fakes_by_method.keys())
    n_methods = len(methods)

    base_fakes_per_method = n_real // n_methods
    remainder = n_real % n_methods

    rng = random.Random(seed)
    # Shuffle methods so remainder is distributed randomly across methods
    shuffled_methods = list(methods)
    rng.shuffle(shuffled_methods)

    selected_fakes = []
    for idx, m in enumerate(shuffled_methods):
        target_count = base_fakes_per_method + (1 if idx < remainder else 0)
        pool = fakes_by_method[m]
        # Draw target_count frames with seed
        if len(pool) >= target_count:
            chosen = rng.sample(pool, target_count)
        else:
            chosen = pool * (target_count // len(pool)) + rng.sample(pool, target_count % len(pool))
        selected_fakes.extend(chosen)

    combined = list(real_records) + selected_fakes
    rng.shuffle(combined)
    return combined


def sample_val_records(
    real_records: List[Dict[str, Any]],
    fakes_by_method: Dict[str, List[Dict[str, Any]]],
    max_fakes_per_method: int = 500,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """All real val frames + fixed stratified sample of up to 500 val fakes per method."""
    rng = random.Random(seed)
    selected = list(real_records)
    for m in sorted(fakes_by_method.keys()):
        pool = fakes_by_method[m]
        count = min(len(pool), max_fakes_per_method)
        selected.extend(rng.sample(pool, count))
    return selected


# ─────────────────────────────────────────────────────────────────────────────
# Metrics Calculation
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(
    labels: np.ndarray,
    probs: np.ndarray,
    methods: List[str],
    video_ids: List[str],
) -> Dict[str, Any]:
    """Computes overall AUC, EER, balanced acc @ 0.5, video-level AUC, and per-method metrics."""
    out: Dict[str, Any] = {}

    # Overall AUC
    try:
        if len(np.unique(labels)) > 1:
            out["overall_auc"] = float(roc_auc_score(labels, probs))
        else:
            out["overall_auc"] = 0.5
    except Exception:
        out["overall_auc"] = 0.5

    # Overall EER
    try:
        fpr, tpr, thresholds = roc_curve(labels, probs)
        fnr = 1.0 - tpr
        idx_eer = np.nanargmin(np.abs(fnr - fpr))
        out["overall_eer"] = float(fpr[idx_eer])
    except Exception:
        out["overall_eer"] = 0.5

    # Balanced accuracy @ 0.5
    preds_05 = (probs >= 0.5).astype(int)
    try:
        out["balanced_acc_05"] = float(balanced_accuracy_score(labels, preds_05))
    except Exception:
        out["balanced_acc_05"] = 0.5

    # Video-level AUC (mean probability per video_id)
    vid_probs: Dict[str, List[float]] = {}
    vid_labels: Dict[str, int] = {}
    for p, l, v in zip(probs, labels, video_ids):
        vid_probs.setdefault(v, []).append(p)
        vid_labels[v] = l

    agg_vids = list(vid_probs.keys())
    agg_p = np.array([np.mean(vid_probs[v]) for v in agg_vids])
    agg_l = np.array([vid_labels[v] for v in agg_vids])
    try:
        if len(np.unique(agg_l)) > 1:
            out["video_auc"] = float(roc_auc_score(agg_l, agg_p))
        else:
            out["video_auc"] = 0.5
    except Exception:
        out["video_auc"] = 0.5

    # Per-method metrics (each method's fakes vs ALL real frames)
    real_mask = (labels == 0)
    real_probs = probs[real_mask]

    per_method_auc = {}
    per_method_recall = {}
    unique_fake_methods = sorted(set(m for m, l in zip(methods, labels) if l == 1))

    for m in unique_fake_methods:
        fake_mask = (np.array(methods) == m) & (labels == 1)
        m_probs = probs[fake_mask]
        if len(m_probs) == 0 or len(real_probs) == 0:
            per_method_auc[m] = 0.5
            per_method_recall[m] = 0.0
            continue

        pair_y = np.array([0] * len(real_probs) + [1] * len(m_probs))
        pair_p = np.concatenate([real_probs, m_probs])
        try:
            auc = float(roc_auc_score(pair_y, pair_p))
        except Exception:
            auc = 0.5
        rec = float(np.mean(m_probs >= 0.5))

        per_method_auc[m] = auc
        per_method_recall[m] = rec

    out["per_method_auc"] = per_method_auc
    out["per_method_recall"] = per_method_recall
    out["mean_per_method_auc"] = float(np.mean(list(per_method_auc.values()))) if per_method_auc else 0.5

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Visual Augmentation Check Grid
# ─────────────────────────────────────────────────────────────────────────────

def save_augmentation_grid(
    real_sample: List[Dict[str, Any]],
    fake_sample: List[Dict[str, Any]],
    out_path: Path,
):
    """Saves a 24-image contact sheet (12 real, 12 fake) illustrating augmentations."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)

    tiles = []
    # 12 real
    for r in real_sample[:12]:
        img = cv2.imread(r["path"], cv2.IMREAD_COLOR)
        if img is None:
            img = np.zeros((256, 256, 3), dtype=np.uint8)
        img = cv2.resize(img, (256, 256), interpolation=cv2.INTER_AREA)
        aug = augment_image_cv2(img, rng)
        # Center crop 224
        crop = aug[16:240, 16:240]
        cv2.putText(crop, "REAL", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        tiles.append(crop)

    # 12 fake
    for r in fake_sample[:12]:
        img = cv2.imread(r["path"], cv2.IMREAD_COLOR)
        if img is None:
            img = np.zeros((256, 256, 3), dtype=np.uint8)
        img = cv2.resize(img, (256, 256), interpolation=cv2.INTER_AREA)
        aug = augment_image_cv2(img, rng)
        crop = aug[16:240, 16:240]
        label_text = f"FAKE: {r['method'][:8]}"
        cv2.putText(crop, label_text, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        tiles.append(crop)

    # 4 rows x 6 columns
    rows = []
    for r_idx in range(4):
        row_tiles = tiles[r_idx * 6 : (r_idx + 1) * 6]
        rows.append(np.hstack(row_tiles))
    grid = np.vstack(rows)
    cv2.imwrite(str(out_path), grid)
    log.info("Saved augmentation check grid to: %s", out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Atomic Checkpoint Saver
# ─────────────────────────────────────────────────────────────────────────────

def save_atomic_checkpoint(checkpoint_dict: Dict[str, Any], target_path: Path):
    """Atomically writes checkpoint to temp file in same directory, then renames."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(
        dir=str(target_path.parent),
        prefix=target_path.stem + "_tmp_",
        suffix=".pth",
    )
    os.close(temp_fd)
    try:
        torch.save(checkpoint_dict, temp_path)
        # Atomic replace on Windows
        os.replace(temp_path, str(target_path))
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e


# ─────────────────────────────────────────────────────────────────────────────
# Main Training & Evaluation Script
# ─────────────────────────────────────────────────────────────────────────────

def run_training(args):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    log_csv_path = output_dir / "finetune_df40_log.csv"
    config_json_path = output_dir / "finetune_df40_config.json"
    ckpt_last_path = output_dir / "efficientnet_b0_df40_ckpt_last.pth"
    best_weights_path = output_dir / "efficientnet_b0_df40_finetuned.pth"
    val_table_path = output_dir / "df40_val_per_method.csv"
    heldout_report_path = output_dir / "df40_heldout_report.json"
    aug_grid_path = output_dir / "aug_check.png"
    stop_file_path = output_dir / "STOP"

    # Startup message on how to stop
    print("\n" + "=" * 70)
    print("AEGIS DF40 Fine-Tuning Controller")
    print(f"Device: {device} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")
    print("HOW TO STOP CLEANLY:")
    print(f"  1. Graceful stop after epoch: Create file -> {stop_file_path}")
    print("  2. Immediate abort: Press Ctrl+C (discards unfinished epoch, next run restarts it)")
    print("=" * 70 + "\n")

    # 1. Hashes of manifests
    train_csv_path = Path(args.train_csv)
    val_csv_path = Path(args.val_csv)
    heldout_csv_path = Path(args.heldout_csv)

    log.info("Computing manifest hashes...")
    train_sha256 = sha256_file(train_csv_path)
    val_sha256 = sha256_file(val_csv_path)
    heldout_sha256 = sha256_file(heldout_csv_path)

    # 2. Safety & Freshness Check
    if args.fresh:
        if not args.overwrite:
            existing_targets = [
                p for p in [best_weights_path, ckpt_last_path, log_csv_path] if p.exists()
            ]
            if existing_targets:
                log.error(
                    "Flag --fresh passed but target output files already exist:\n  %s\n"
                    "Refusing to overwrite. Pass --overwrite along with --fresh if intentional.",
                    "\n  ".join(str(p) for p in existing_targets),
                )
                sys.exit(1)
        else:
            log.warning("--fresh and --overwrite passed. Removing previous checkpoints in %s...", output_dir)
            if ckpt_last_path.exists():
                os.remove(ckpt_last_path)
            if log_csv_path.exists():
                os.remove(log_csv_path)

    # 3. Load Manifest Records
    log.info("Reading manifests...")
    train_records = []
    with open(train_csv_path, "r", encoding="utf-8") as f:
        train_records = list(csv.DictReader(f))

    val_records = []
    with open(val_csv_path, "r", encoding="utf-8") as f:
        val_records = list(csv.DictReader(f))

    # Split train records into real and fakes by method
    train_real = [r for r in train_records if r["method"] == "real"]
    train_fakes_by_method: Dict[str, List[Dict[str, Any]]] = {}
    for r in train_records:
        if r["method"] != "real":
            train_fakes_by_method.setdefault(r["method"], []).append(r)

    val_real = [r for r in val_records if r["method"] == "real"]
    val_fakes_by_method: Dict[str, List[Dict[str, Any]]] = {}
    for r in val_records:
        if r["method"] != "real":
            val_fakes_by_method.setdefault(r["method"], []).append(r)

    log.info("Train pool: %d real frames | %d fake methods (%d total fake frames)",
             len(train_real), len(train_fakes_by_method), sum(len(v) for v in train_fakes_by_method.values()))
    log.info("Val pool:   %d real frames | %d fake methods (%d total fake frames)",
             len(val_real), len(val_fakes_by_method), sum(len(v) for v in val_fakes_by_method.values()))

    # Build static validation evaluation sample (all real + up to 500 fakes per method)
    val_eval_sample = sample_val_records(val_real, val_fakes_by_method, max_fakes_per_method=500, seed=42)
    log.info("Fixed validation evaluation sample: %d frames", len(val_eval_sample))

    # Generate Augmentation Grid if not present
    if not aug_grid_path.exists():
        sample_fake_pool = []
        for m in sorted(train_fakes_by_method.keys())[:12]:
            sample_fake_pool.append(train_fakes_by_method[m][0])
        save_augmentation_grid(train_real, sample_fake_pool, aug_grid_path)

    # 4. Save Config JSON
    config_dict = {
        "manifests": {
            "train_csv": str(train_csv_path),
            "train_sha256": train_sha256,
            "val_csv": str(val_csv_path),
            "val_sha256": val_sha256,
            "heldout_csv": str(heldout_csv_path),
            "heldout_sha256": heldout_sha256,
        },
        "hyperparameters": {
            "model": "efficientnet_b0",
            "init_from": args.init_from,
            "base_seed": args.seed,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "weight_decay": args.weight_decay,
            "warmup_epochs": 1,
            "label_smoothing": 0.05,
            "gradient_clipping": 1.0,
            "focal_loss": args.focal,
            "num_workers": args.num_workers,
            "amp": True,
            "channels_last": True,
        },
    }
    with open(config_json_path, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, indent=2)

    # 5. Model, Optimizer, Loss, Scaler
    model = create_efficientnet_b0(init_from=args.init_from)
    model.to(device, memory_format=torch.channels_last)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scaler = torch.amp.GradScaler("cuda", enabled=(device.type == "cuda"))

    if args.focal:
        log.info("Using Focal Loss...")
        # Simple focal loss fallback
        class FocalLoss(nn.Module):
            def __init__(self, gamma=2.0):
                super().__init__()
                self.gamma = gamma
                self.ce = nn.CrossEntropyLoss(label_smoothing=0.05, reduction="none")
            def forward(self, logits, targets):
                ce_loss = self.ce(logits, targets)
                pt = torch.exp(-ce_loss)
                return (((1 - pt) ** self.gamma) * ce_loss).mean()
        criterion = FocalLoss()
    else:
        criterion = nn.CrossEntropyLoss(label_smoothing=0.05)

    # Learning rate scheduler: 1 warmup epoch, then cosine decay
    def get_lr_scheduler(opt, total_epochs):
        def lr_lambda(epoch):
            if epoch < 1:
                return float(epoch + 1) / 1.0
            progress = float(epoch - 1) / float(max(1, total_epochs - 1))
            return 0.5 * (1.0 + np.cos(np.pi * progress))
        return torch.optim.lr_scheduler.LambdaLR(opt, lr_lambda)

    scheduler = get_lr_scheduler(optimizer, args.epochs)

    # 6. Check for Resume Checkpoint
    start_epoch = 1
    best_mean_auc = 0.0
    best_epoch = 0

    if not args.fresh and ckpt_last_path.is_file():
        log.info("Found last checkpoint: %s. Resuming...", ckpt_last_path)
        ckpt = torch.load(ckpt_last_path, map_location="cpu", weights_only=True)

        # Safety checks on hyperparams and manifest hashes
        saved_args = ckpt.get("args", {})
        saved_train_hash = ckpt.get("train_sha256", "")
        saved_val_hash = ckpt.get("val_sha256", "")

        diffs = []
        if saved_train_hash and saved_train_hash != train_sha256:
            diffs.append(f"train.csv hash mismatch ({saved_train_hash} vs {train_sha256})")
        if saved_val_hash and saved_val_hash != val_sha256:
            diffs.append(f"val.csv hash mismatch ({saved_val_hash} vs {val_sha256})")
        if saved_args.get("lr") != args.lr:
            diffs.append(f"lr mismatch ({saved_args.get('lr')} vs {args.lr})")
        if saved_args.get("batch_size") != args.batch_size:
            diffs.append(f"batch_size mismatch ({saved_args.get('batch_size')} vs {args.batch_size})")
        if saved_args.get("epochs", args.epochs) > args.epochs:
            diffs.append(f"--epochs ({args.epochs}) is smaller than saved epochs ({saved_args.get('epochs')})")

        if diffs:
            log.error("Safety check failed on resume! Discrepancies found:\n  - %s", "\n  - ".join(diffs))
            sys.exit(1)

        model.load_state_dict(ckpt["model"])
        optimizer.load_state_dict(ckpt["optimizer"])
        scheduler.load_state_dict(ckpt["scheduler"])
        if "scaler" in ckpt and scaler.is_enabled():
            scaler.load_state_dict(ckpt["scaler"])

        start_epoch = ckpt["epoch"] + 1
        best_mean_auc = ckpt.get("best_metric", 0.0)
        best_epoch = ckpt.get("best_epoch", 0)

        # Restore RNG states
        if "rng_python" in ckpt:
            random.setstate(ckpt["rng_python"])
        if "rng_numpy" in ckpt:
            np.random.set_state(ckpt["rng_numpy"])
        if "rng_torch" in ckpt:
            torch.set_rng_state(ckpt["rng_torch"])
        if "rng_cuda" in ckpt and torch.cuda.is_available() and ckpt["rng_cuda"] is not None:
            torch.cuda.set_rng_state(ckpt["rng_cuda"])

        print(f"Resuming from epoch {start_epoch}, best so far {best_mean_auc:.4f} at epoch {best_epoch}")

    # Set up signal handler for clean Ctrl+C stopping
    interrupted = False
    def handle_sigint(sig, frame):
        nonlocal interrupted
        print("\n[!] Ctrl+C caught! Discarding unfinished epoch. The next run will redo it from the start.")
        interrupted = True
        sys.exit(130)

    signal.signal(signal.SIGINT, handle_sigint)

    # Initialize log CSV if new
    if not log_csv_path.exists():
        with open(log_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "epoch", "train_loss", "lr", "overall_auc", "overall_eer",
                "balanced_acc_05", "video_auc", "mean_per_method_auc", "elapsed_s"
            ])

    # 7. Training Loop
    current_batch_size = args.batch_size

    for epoch in range(start_epoch, args.epochs + 1):
        epoch_t0 = time.time()
        log.info("\n--- Starting Epoch %d / %d (seed: %d) ---", epoch, args.epochs, args.seed + epoch)

        # Draw train epoch samples (seed = base seed + epoch)
        epoch_train_records = sample_train_epoch_records(
            train_real, train_fakes_by_method, seed=args.seed + epoch
        )
        if args.smoke_test:
            # 30 batches * batch_size samples
            epoch_train_records = epoch_train_records[: 30 * current_batch_size]

        train_ds = DF40Dataset(epoch_train_records, is_training=True, crop_size=224, seed=args.seed + epoch)

        # Prepare train dataloader with auto OOM fallback
        while True:
            try:
                train_loader = DataLoader(
                    train_ds,
                    batch_size=current_batch_size,
                    shuffle=True,
                    num_workers=args.num_workers,
                    pin_memory=(device.type == "cuda"),
                    persistent_workers=(args.num_workers > 0),
                    worker_init_fn=worker_init_fn,
                )
                break
            except Exception as e:
                log.error("DataLoader creation error: %s", e)
                raise e

        model.train()
        total_loss = 0.0
        n_batches = 0
        batch_t0 = time.time()

        for batch_idx, (inputs, targets, _, _) in enumerate(train_loader, start=1):
            inputs = inputs.to(device, memory_format=torch.channels_last, non_blocking=True)
            targets = targets.to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)

            try:
                with torch.amp.autocast("cuda", enabled=(device.type == "cuda")):
                    outputs = model(inputs)
                    loss = criterion(outputs, targets)

                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                scaler.step(optimizer)
                scaler.update()

            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                current_batch_size = max(8, current_batch_size // 2)
                log.warning("OOM detected! Reducing batch size to %d and restarting epoch...", current_batch_size)
                break

            total_loss += loss.item()
            n_batches += 1

            if batch_idx % 100 == 0 or batch_idx == len(train_loader):
                elapsed_b = time.time() - batch_t0
                speed = (100 * current_batch_size) / elapsed_b if elapsed_b > 0 else 0
                gpu_mem = torch.cuda.memory_allocated() / (1024 ** 2) if torch.cuda.is_available() else 0
                log.info(
                    "Epoch %d [%d/%d]  Loss: %.4f  LR: %.2e  Speed: %.1f img/s  GPU Mem: %.0f MB",
                    epoch, batch_idx, len(train_loader), loss.item(), optimizer.param_groups[0]["lr"], speed, gpu_mem
                )
                batch_t0 = time.time()

        scheduler.step()
        avg_train_loss = total_loss / max(1, n_batches)

        # 8. Validation Evaluation
        log.info("Running validation for Epoch %d...", epoch)
        val_eval_records = val_eval_sample
        if args.smoke_test:
            val_eval_records = val_eval_sample[: 10 * current_batch_size]

        val_ds = DF40Dataset(val_eval_records, is_training=False, crop_size=224)
        val_loader = DataLoader(
            val_ds,
            batch_size=current_batch_size,
            shuffle=False,
            num_workers=args.num_workers,
            pin_memory=(device.type == "cuda"),
            worker_init_fn=worker_init_fn,
        )

        model.eval()
        val_labels = []
        val_probs = []
        val_methods = []
        val_video_ids = []

        with torch.no_grad():
            for inputs, targets, methods, vids in val_loader:
                inputs = inputs.to(device, memory_format=torch.channels_last, non_blocking=True)
                with torch.amp.autocast("cuda", enabled=(device.type == "cuda")):
                    logits = model(inputs)
                    probs = torch.softmax(logits, dim=1)[:, 1]

                val_labels.extend(targets.cpu().numpy().tolist())
                val_probs.extend(probs.cpu().numpy().tolist())
                val_methods.extend(methods)
                val_video_ids.extend(vids)

        val_metrics = compute_metrics(
            np.array(val_labels),
            np.array(val_probs),
            val_methods,
            val_video_ids,
        )

        epoch_elapsed = time.time() - epoch_t0
        mean_method_auc = val_metrics["mean_per_method_auc"]

        log.info(
            "Epoch %d Summary: Train Loss: %.4f | Val AUC: %.4f | Val EER: %.4f | "
            "Bal Acc: %.4f | Video AUC: %.4f | Mean Method AUC: %.4f | Time: %.1fs",
            epoch, avg_train_loss, val_metrics["overall_auc"], val_metrics["overall_eer"],
            val_metrics["balanced_acc_05"], val_metrics["video_auc"], mean_method_auc, epoch_elapsed
        )

        # Shortcut warnings
        for m, auc in val_metrics["per_method_auc"].items():
            if epoch <= 2 and auc > 0.999:
                log.warning("SHORTCUT ALERT: Method '%s' has AUC %.4f > 0.999 in epoch %d!", m, auc, epoch)
            if auc < 0.70:
                log.warning("PERFORMANCE ALERT: Method '%s' has low AUC %.4f (< 0.70) in epoch %d.", m, auc, epoch)

        # Append to log CSV
        with open(log_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                epoch,
                f"{avg_train_loss:.4f}",
                f"{optimizer.param_groups[0]['lr']:.2e}",
                f"{val_metrics['overall_auc']:.4f}",
                f"{val_metrics['overall_eer']:.4f}",
                f"{val_metrics['balanced_acc_05']:.4f}",
                f"{val_metrics['video_auc']:.4f}",
                f"{mean_method_auc:.4f}",
                f"{epoch_elapsed:.1f}",
            ])

        # Track Best Model
        is_best = mean_method_auc > best_mean_auc
        if is_best:
            best_mean_auc = mean_method_auc
            best_epoch = epoch
            log.info("New best model! Mean Per-Method AUC: %.4f at Epoch %d. Saving best weights...", best_mean_auc, best_epoch)
            # Save plain state_dict
            torch.save(model.state_dict(), best_weights_path)

            # Write per-method validation metrics table for best epoch
            with open(val_table_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["method", "auc_vs_real", "recall_at_05"])
                for m in sorted(val_metrics["per_method_auc"].keys()):
                    writer.writerow([m, f"{val_metrics['per_method_auc'][m]:.4f}", f"{val_metrics['per_method_recall'][m]:.4f}"])

        # Save numbered per-epoch checkpoint
        numbered_ckpt_path = output_dir / f"efficientnet_b0_df40_ckpt_ep{epoch}.pth"
        full_ckpt_data = {
            "epoch": epoch,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "scaler": scaler.state_dict() if scaler.is_enabled() else None,
            "best_metric": best_mean_auc,
            "best_epoch": best_epoch,
            "args": vars(args),
            "train_sha256": train_sha256,
            "val_sha256": val_sha256,
            "rng_python": random.getstate(),
            "rng_numpy": np.random.get_state(),
            "rng_torch": torch.get_rng_state(),
            "rng_cuda": torch.cuda.get_rng_state() if torch.cuda.is_available() else None,
        }
        torch.save(full_ckpt_data, numbered_ckpt_path)

        # Save ckpt_last.pth ATOMICALLY
        save_atomic_checkpoint(full_ckpt_data, ckpt_last_path)
        log.info("Checkpoints saved: ep%d and ckpt_last.pth (atomic).", epoch)

        # Check for STOP file
        if stop_file_path.exists():
            log.info("\nSTOP file detected at %s! Completing epoch %d and shutting down gracefully.", stop_file_path, epoch)
            try:
                os.remove(stop_file_path)
            except Exception:
                pass
            print(f"Graceful exit complete. Resuming next time will continue from epoch {epoch + 1}.")
            return

    log.info("\n=== Training Complete. Best Epoch: %d (Mean Per-Method AUC: %.4f) ===", best_epoch, best_mean_auc)

    # 9. Final Evaluation on Full val.csv & heldout_methods.csv using Best Weights
    if best_weights_path.exists() and not getattr(args, "skip_final_eval", False):
        run_final_evaluation(best_weights_path, args, output_dir, train_real, val_real, val_records, heldout_csv_path, device)


# ─────────────────────────────────────────────────────────────────────────────
# Final Evaluation Module
# ─────────────────────────────────────────────────────────────────────────────

def run_final_evaluation(
    best_weights_path: Path,
    args,
    output_dir: Path,
    train_real,
    val_real,
    full_val_records: List[Dict[str, Any]],
    heldout_csv_path: Path,
    device,
):
    log.info("\n=======================================================")
    log.info("RUNNING FINAL POST-TRAINING EVALUATION WITH BEST WEIGHTS")
    log.info("=======================================================")

    eval_model = create_efficientnet_b0()
    eval_model.load_state_dict(torch.load(best_weights_path, map_location=device, weights_only=True))
    eval_model.to(device, memory_format=torch.channels_last)
    eval_model.eval()

    # If smoke test, slice to 10 batches for rapid testing
    if getattr(args, "smoke_test", False):
        full_val_records = full_val_records[: 10 * args.batch_size]

    # 1. Full val.csv evaluation
    val_ds = DF40Dataset(full_val_records, is_training=False, crop_size=224)
    val_loader = DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers,
        worker_init_fn=worker_init_fn
    )

    val_labels = []
    val_probs = []
    val_methods = []
    val_video_ids = []

    with torch.no_grad():
        for inputs, targets, methods, vids in val_loader:
            inputs = inputs.to(device, memory_format=torch.channels_last, non_blocking=True)
            with torch.amp.autocast("cuda", enabled=(device.type == "cuda")):
                logits = eval_model(inputs)
                probs = torch.softmax(logits, dim=1)[:, 1]
            val_labels.extend(targets.cpu().numpy().tolist())
            val_probs.extend(probs.cpu().numpy().tolist())
            val_methods.extend(methods)
            val_video_ids.extend(vids)

    val_labels_np = np.array(val_labels)
    val_probs_np = np.array(val_probs)

    val_metrics = compute_metrics(val_labels_np, val_probs_np, val_methods, val_video_ids)

    # 2. Threshold determination from validation real frames
    real_val_probs = val_probs_np[val_labels_np == 0]
    # Threshold at 1% False Alarm Rate on real frames (99th percentile of real scores)
    tau_1pct_far = float(np.percentile(real_val_probs, 99.0))

    # Threshold maximizing balanced accuracy
    best_tau_bacc = 0.5
    best_bacc = 0.0
    for cand_tau in np.linspace(0.01, 0.99, 99):
        bacc = float(balanced_accuracy_score(val_labels_np, (val_probs_np >= cand_tau).astype(int)))
        if bacc > best_bacc:
            best_bacc = bacc
            best_tau_bacc = float(cand_tau)

    log.info("Validation Thresholds: 1%% FAR Tau = %.4f | Max BalAcc Tau = %.4f (BalAcc = %.4f)",
             tau_1pct_far, best_tau_bacc, best_bacc)

    # 3. Held-out methods evaluation (all fakes vs real val frames)
    heldout_records = []
    with open(heldout_csv_path, "r", encoding="utf-8") as f:
        heldout_records = list(csv.DictReader(f))

    # Combine real val frames + held-out frames
    heldout_eval_records = list(val_real) + heldout_records
    if getattr(args, "smoke_test", False):
        heldout_eval_records = heldout_eval_records[: 10 * args.batch_size]

    heldout_ds = DF40Dataset(heldout_eval_records, is_training=False, crop_size=224)
    heldout_loader = DataLoader(
        heldout_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers,
        worker_init_fn=worker_init_fn
    )

    h_labels = []
    h_probs = []
    h_methods = []

    with torch.no_grad():
        for inputs, targets, methods, _ in heldout_loader:
            inputs = inputs.to(device, memory_format=torch.channels_last, non_blocking=True)
            with torch.amp.autocast("cuda", enabled=(device.type == "cuda")):
                logits = eval_model(inputs)
                probs = torch.softmax(logits, dim=1)[:, 1]
            h_labels.extend(targets.cpu().numpy().tolist())
            h_probs.extend(probs.cpu().numpy().tolist())
            h_methods.extend(methods)

    h_labels_np = np.array(h_labels)
    h_probs_np = np.array(h_probs)

    real_h_probs = h_probs_np[h_labels_np == 0]
    heldout_results = {}

    for hm in ["uniface", "wav2lip", "VQGAN"]:
        hm_mask = (np.array(h_methods) == hm)
        hm_fake_probs = h_probs_np[hm_mask]
        if len(hm_fake_probs) == 0:
            continue
        pair_y = np.array([0] * len(real_h_probs) + [1] * len(hm_fake_probs))
        pair_p = np.concatenate([real_h_probs, hm_fake_probs])
        auc = float(roc_auc_score(pair_y, pair_p))
        rec_tau_far = float(np.mean(hm_fake_probs >= tau_1pct_far))
        rec_tau_bacc = float(np.mean(hm_fake_probs >= best_tau_bacc))
        rec_05 = float(np.mean(hm_fake_probs >= 0.5))

        heldout_results[hm] = {
            "total_frames": len(hm_fake_probs),
            "auc_vs_real_val": round(auc, 4),
            "recall_at_1pct_far_tau": round(rec_tau_far, 4),
            "recall_at_best_bacc_tau": round(rec_tau_bacc, 4),
            "recall_at_05": round(rec_05, 4),
        }

    # 4. Save Final Report JSON
    report_data = {
        "evaluation_timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "best_weights_path": str(best_weights_path),
        "validation_full_metrics": {
            "total_val_frames": len(val_labels),
            "overall_auc": round(val_metrics["overall_auc"], 4),
            "overall_eer": round(val_metrics["overall_eer"], 4),
            "balanced_acc_05": round(val_metrics["balanced_acc_05"], 4),
            "video_auc": round(val_metrics["video_auc"], 4),
            "mean_per_method_auc": round(val_metrics["mean_per_method_auc"], 4),
            "per_method_auc": {k: round(v, 4) for k, v in val_metrics["per_method_auc"].items()},
            "per_method_recall_05": {k: round(v, 4) for k, v in val_metrics["per_method_recall"].items()},
        },
        "thresholds": {
            "tau_1pct_far": round(tau_1pct_far, 4),
            "tau_best_bacc": round(best_tau_bacc, 4),
            "val_bacc_at_best_tau": round(best_bacc, 4),
        },
        "heldout_evaluation": heldout_results,
    }

    report_path = output_dir / "df40_heldout_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    log.info("Held-out evaluation report saved to: %s", report_path)

    # Print summary table
    print("\n" + "=" * 70)
    print("FINAL HELD-OUT GENERALIZATION SUMMARY")
    print("=" * 70)
    print(f"{'Method':<12} {'Frames':<8} {'AUC':<10} {'Rec@1%FAR':<12} {'Rec@MaxBAcc':<14} {'Rec@0.5':<10}")
    print("-" * 70)
    for hm, metrics in heldout_results.items():
        print(f"{hm:<12} {metrics['total_frames']:<8} {metrics['auc_vs_real_val']:<10.4f} "
              f"{metrics['recall_at_1pct_far_tau']:<12.4f} {metrics['recall_at_best_bacc_tau']:<14.4f} "
              f"{metrics['recall_at_05']:<10.4f}")
    print("=" * 70 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Smoke Test Runner (Tests Pipeline + Stop/Resume Behavior)
# ─────────────────────────────────────────────────────────────────────────────

def run_smoke_test(args):
    print("\n" + "=" * 70)
    print("RUNNING SMOKE TEST & RESUME VERIFICATION")
    print("=" * 70)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")

    temp_dir = Path(tempfile.mkdtemp(prefix="smoke_df40_"))
    print(f"Temporary output directory: {temp_dir}")

    try:
        smoke_args = argparse.Namespace(**vars(args))
        smoke_args.output_dir = str(temp_dir)
        smoke_args.epochs = 1
        smoke_args.batch_size = 8
        smoke_args.num_workers = 2
        smoke_args.smoke_test = True
        smoke_args.skip_final_eval = True
        smoke_args.fresh = False
        smoke_args.overwrite = True

        print("\n--- Smoke Test Phase 1: Running Epoch 1 ---")
        run_training(smoke_args)

        ckpt_last = temp_dir / "efficientnet_b0_df40_ckpt_last.pth"
        log_csv = temp_dir / "finetune_df40_log.csv"

        assert ckpt_last.exists(), "ckpt_last.pth was not created in Phase 1!"
        assert log_csv.exists(), "finetune_df40_log.csv was not created in Phase 1!"

        with open(log_csv, "r") as f:
            lines_p1 = f.readlines()
        print(f"Phase 1 complete. Log lines: {len(lines_p1)} (expected 2: header + epoch 1)")
        assert len(lines_p1) == 2, f"Expected 2 lines in log, got {len(lines_p1)}"

        # Check saved metric in checkpoint
        ckpt_p1 = torch.load(ckpt_last, map_location="cpu", weights_only=True)
        best_metric_p1 = ckpt_p1["best_metric"]
        print(f"Phase 1 checkpoint verified: completed epoch={ckpt_p1['epoch']}, best_metric={best_metric_p1:.4f}")

        print("\n--- Smoke Test Phase 2: Resume Test for Epoch 2 ---")
        smoke_args.epochs = 2
        smoke_args.skip_final_eval = False
        run_training(smoke_args)

        with open(log_csv, "r") as f:
            lines_p2 = f.readlines()
        print(f"Phase 2 complete. Log lines: {len(lines_p2)} (expected 3: header + epoch 1 + epoch 2)")
        assert len(lines_p2) == 3, f"Expected 3 lines in log, got {len(lines_p2)}"

        ckpt_p2 = torch.load(ckpt_last, map_location="cpu", weights_only=True)
        print(f"Phase 2 checkpoint verified: completed epoch={ckpt_p2['epoch']}, best_metric={ckpt_p2['best_metric']:.4f}")
        assert ckpt_p2["epoch"] == 2, f"Expected epoch 2 in ckpt, got {ckpt_p2['epoch']}"

        print("\n" + "=" * 70)
        print("SMOKE TEST & RESUME VERIFICATION: ALL CHECKS PASSED (100% OK)")
        print("=" * 70)

    finally:
        # Clean up temporary directory
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"Cleaned up temporary smoke test directory: {temp_dir}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="AEGIS EfficientNet-B0 Fine-Tuning on DF40")
    parser.add_argument("--train-csv", type=str, default=str(DEFAULT_TRAIN_CSV))
    parser.add_argument("--val-csv", type=str, default=str(DEFAULT_VAL_CSV))
    parser.add_argument("--heldout-csv", type=str, default=str(DEFAULT_HELDOUT_CSV))
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--init-from", type=str, default=None, help="Path to custom .pth weights")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-workers", type=int, default=6)
    parser.add_argument("--focal", action="store_true", default=False, help="Use Focal Loss instead of CE")
    parser.add_argument("--fresh", action="store_true", default=False, help="Start fresh run, ignore ckpt_last.pth")
    parser.add_argument("--overwrite", action="store_true", default=False, help="Allow overwriting existing outputs")
    parser.add_argument("--smoke-test", action="store_true", default=False, help="Run 30-batch smoke test + resume test")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.smoke_test:
        run_smoke_test(args)
    else:
        run_training(args)
