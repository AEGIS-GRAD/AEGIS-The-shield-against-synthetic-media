"""
LoRA Fine-tuning script for Desklib AI Text Detector (DeBERTa-v3-large).
Optimized for 8 GB VRAM GPU (RTX 4060):
- fp16 precision
- LoRA rank=8 on query and value projection matrices
- Small batch size (4) with gradient accumulation (4) -> effective batch 16
- Max sequence length capped at 512
- Saves adapter weights to detectors/text-detector/models/desklib-finetuned/
"""
import os
import json
import argparse
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from transformers import AutoTokenizer
from peft import LoraConfig, get_peft_model, TaskType
from desklib_model import DesklibAIDetectionModel

class TextClassificationDataset(Dataset):
    def __init__(self, jsonl_file, tokenizer, max_length=512):
        self.samples = []
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self.samples.append(json.loads(line))
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        item = self.samples[idx]
        encoding = self.tokenizer(
            item["text"],
            padding="max_length",
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt"
        )
        return {
            "input_ids": encoding["input_ids"].squeeze(0),
            "attention_mask": encoding["attention_mask"].squeeze(0),
            "label": torch.tensor(float(item["label"]), dtype=torch.float32)
        }

def train():
    parser = argparse.ArgumentParser(description="Fine-tune Desklib Detector with LoRA")
    parser.add_argument("--base_model_dir", type=str, default="detectors/text-detector/models/desklib-base")
    parser.add_argument("--train_file", type=str, default="detectors/text-detector/data/datasets/train.jsonl")
    parser.add_argument("--eval_file", type=str, default="detectors/text-detector/data/datasets/heldout_test.jsonl")
    parser.add_argument("--output_dir", type=str, default="detectors/text-detector/models/desklib-finetuned")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--grad_accum", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max_len", type=int, default=512)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[*] Training on device: {device} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")

    tokenizer = AutoTokenizer.from_pretrained(args.base_model_dir)
    base_model = DesklibAIDetectionModel.from_pretrained(args.base_model_dir)

    # Configure LoRA targeting DeBERTa attention projection layers
    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["query_proj", "value_proj"],
        lora_dropout=0.05,
        bias="none",
    )
    
    # Apply LoRA specifically to base transformer
    base_model.model = get_peft_model(base_model.model, lora_config)
    base_model.model.print_trainable_parameters()
    base_model.to(device)

    train_dataset = TextClassificationDataset(args.train_file, tokenizer, args.max_len)
    eval_dataset = TextClassificationDataset(args.eval_file, tokenizer, args.max_len)

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    eval_loader = DataLoader(eval_dataset, batch_size=args.batch_size, shuffle=False)

    optimizer = torch.optim.AdamW(
        [p for p in base_model.parameters() if p.requires_grad],
        lr=args.lr,
        weight_decay=0.01
    )

    use_amp = torch.cuda.is_available()
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

    os.makedirs(args.output_dir, exist_ok=True)
    print(f"[*] Starting fine-tuning for {args.epochs} epochs...")

    for epoch in range(1, args.epochs + 1):
        base_model.train()
        total_train_loss = 0.0
        optimizer.zero_grad()

        for step, batch in enumerate(train_loader):
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["label"].to(device)

            with torch.cuda.amp.autocast(enabled=use_amp):
                out = base_model(input_ids, attention_mask=attention_mask, labels=labels)
                loss = out["loss"] / args.grad_accum

            scaler.scale(loss).backward()
            total_train_loss += loss.item() * args.grad_accum

            if (step + 1) % args.grad_accum == 0 or (step + 1) == len(train_loader):
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad()

        avg_train_loss = total_train_loss / len(train_loader)

        # Validation pass
        base_model.eval()
        eval_loss = 0.0
        correct = 0
        total = 0
        with torch.no_grad():
            for batch in eval_loader:
                input_ids = batch["input_ids"].to(device)
                attention_mask = batch["attention_mask"].to(device)
                labels = batch["label"].to(device)

                with torch.cuda.amp.autocast(enabled=use_amp):
                    out = base_model(input_ids, attention_mask=attention_mask, labels=labels)
                    eval_loss += out["loss"].item()
                    preds = (torch.sigmoid(out["logits"].view(-1)) >= 0.5).float()
                    correct += (preds == labels).sum().item()
                    total += labels.size(0)

        avg_eval_loss = eval_loss / max(1, len(eval_loader))
        acc = (correct / total) if total > 0 else 0.0
        print(f"Epoch {epoch}/{args.epochs} - Train Loss: {avg_train_loss:.4f} | Held-out Loss: {avg_eval_loss:.4f} | Held-out Acc: {acc:.2%}")

    # Save fine-tuned checkpoint
    adapter_path = os.path.join(args.output_dir, "lora_adapter")
    base_model.model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(args.output_dir)
    print(f"[+] Successfully saved fine-tuned LoRA checkpoint to {adapter_path}")

if __name__ == "__main__":
    train()
