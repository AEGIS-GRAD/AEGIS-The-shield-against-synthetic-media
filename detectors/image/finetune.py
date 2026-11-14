"""
finetune.py
───────────
Fine-tunes the Community Forensics ViT-Small model on an image subset (e.g. OpenFake)
specifically optimized for an 8 GB GPU on Windows using native PyTorch FP16 AMP.

Usage Examples:
  1. Fine-tune on a local folder with 'real' and 'fake' subfolders:
     python finetune.py --data-dir "eval/data/image_subset" --epochs 5 --batch-size 16 --lr 2e-5

  2. Fine-tune on a subset of the HuggingFace OpenFake dataset:
     python finetune.py --openfake --max-samples 1000 --epochs 3 --batch-size 16
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from PIL import Image

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import torchvision.transforms as T
import timm
from safetensors.torch import load_file, save_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("finetune_commfor")

# Community Forensics 384x384 image transform
TRAIN_TRANSFORM = T.Compose([
    T.Resize((384, 384)),
    T.RandomHorizontalFlip(p=0.5),
    T.ToTensor(),
    T.Normalize(mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]),
])


class FolderImageDataset(Dataset):
    """Loads images from folder structure: data_dir/real and data_dir/fake"""
    def __init__(self, root_dir: str, transform=None):
        self.samples = []
        self.transform = transform
        
        real_dir = Path(root_dir) / "real"
        fake_dir = Path(root_dir) / "fake"
        
        exts = {".jpg", ".jpeg", ".png", ".webp"}
        if real_dir.exists():
            for p in real_dir.rglob("*"):
                if p.suffix.lower() in exts:
                    self.samples.append((str(p), 0.0))  # 0.0 = Real
                    
        if fake_dir.exists():
            for p in fake_dir.rglob("*"):
                if p.suffix.lower() in exts:
                    self.samples.append((str(p), 1.0))  # 1.0 = Fake/Synthetic
                    
        logger.info(f"Loaded {len(self.samples)} images from {root_dir}")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        path, label = self.samples[idx]
        try:
            image = Image.open(path).convert("RGB")
        except Exception:
            image = Image.new("RGB", (384, 384), (0, 0, 0))
            
        if self.transform:
            image = self.transform(image)
        return image, torch.tensor([label], dtype=torch.float32)


class HFOpenFakeDataset(Dataset):
    """Streams a small subset of ComplexDataLab/OpenFake from HuggingFace."""
    def __init__(self, max_samples: int = 1000, transform=None):
        from datasets import load_dataset
        logger.info(f"Streaming {max_samples} samples from ComplexDataLab/OpenFake...")
        ds = load_dataset("ComplexDataLab/OpenFake", split="train", streaming=True)
        self.items = []
        self.transform = transform
        for i, item in enumerate(ds):
            if i >= max_samples:
                break
            label = 1.0 if item.get("label") in (1, "fake", "synthetic") else 0.0
            self.items.append((item["image"], label))
        logger.info(f"Loaded {len(self.items)} samples from OpenFake.")

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        img, label = self.items[idx]
        img = img.convert("RGB")
        if self.transform:
            img = self.transform(img)
        return img, torch.tensor([label], dtype=torch.float32)


def main():
    parser = argparse.ArgumentParser(description="Fine-tune Community Forensics on OpenFake / Local subset")
    parser.add_argument("--data-dir", type=str, default="", help="Path to local folder with 'real' and 'fake' subfolders")
    parser.add_argument("--openfake", action="store_true", help="Download and fine-tune on HuggingFace OpenFake subset")
    parser.add_argument("--max-samples", type=int, default=500, help="Max OpenFake samples to stream")
    parser.add_argument("--weights-path", type=str, default="weights/model.safetensors", help="Path to existing weights")
    parser.add_argument("--output-path", type=str, default="weights/model.safetensors", help="Path to save updated weights")
    parser.add_argument("--epochs", type=int, default=3, help="Number of fine-tuning epochs")
    parser.add_argument("--batch-size", type=int, default=8, help="Batch size (8-16 fits well in 8 GB VRAM)")
    parser.add_argument("--lr", type=float, default=2e-5, help="Learning rate (small to prevent catastrophic forgetting)")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Starting fine-tuning on device: {device}")

    # 1. Dataset setup
    if args.openfake:
        dataset = HFOpenFakeDataset(max_samples=args.max_samples, transform=TRAIN_TRANSFORM)
    elif args.data_dir and os.path.exists(args.data_dir):
        dataset = FolderImageDataset(args.data_dir, transform=TRAIN_TRANSFORM)
    else:
        logger.error("Please provide either --data-dir <path> or --openfake")
        sys.exit(1)

    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True, num_workers=0)

    # 2. Build model architecture & load checkpoint
    model = timm.create_model("vit_small_patch16_384", pretrained=False, num_classes=1)
    if os.path.exists(args.weights_path):
        logger.info(f"Loading initial checkpoint: {args.weights_path}")
        state_dict = load_file(args.weights_path)
        model.load_state_dict(state_dict, strict=True)
    else:
        logger.warning(f"Weights file not found at {args.weights_path}; starting with fresh weights.")

    model = model.to(device)

    # 3. Setup optimizer, loss, and mixed-precision scaler (FP16 for 8 GB GPU)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-2)
    criterion = nn.BCEWithLogitsLoss()
    scaler = torch.cuda.amp.GradScaler(enabled=(device.type == "cuda"))

    # 4. Training loop
    model.train()
    for epoch in range(1, args.epochs + 1):
        total_loss = 0.0
        correct = 0
        total = 0

        for batch_idx, (images, targets) in enumerate(loader):
            images, targets = images.to(device), targets.to(device)

            optimizer.zero_grad()
            with torch.cuda.amp.autocast(enabled=(device.type == "cuda"), dtype=torch.float16):
                logits = model(images)
                loss = criterion(logits, targets)

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            total_loss += loss.item()
            preds = (torch.sigmoid(logits) >= 0.5).float()
            correct += (preds == targets).sum().item()
            total += targets.size(0)

            if (batch_idx + 1) % 5 == 0 or (batch_idx + 1) == len(loader):
                logger.info(f"Epoch [{epoch}/{args.epochs}] Batch [{batch_idx+1}/{len(loader)}] Loss: {loss.item():.4f}")

        acc = (correct / total) if total > 0 else 0.0
        avg_loss = total_loss / len(loader) if len(loader) > 0 else 0.0
        logger.info(f"=== Epoch {epoch} Complete | Avg Loss: {avg_loss:.4f} | Accuracy: {acc:.2%} ===")

    # 5. Save fine-tuned weights directly back as safetensors
    os.makedirs(os.path.dirname(args.output_path), exist_ok=True)
    save_file(model.state_dict(), args.output_path)
    logger.info(f"Successfully saved fine-tuned model to: {args.output_path}")


if __name__ == "__main__":
    main()
