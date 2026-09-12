# AEGIS Video Classifier Microservice

This microservice wraps the pretrained **EfficientNet-B0** frame classifier fine-tuned on the FaceForensics++ (c23) dataset ([`Xicor9/efficientnet-b0-ffpp-c23`](https://huggingface.co/Xicor9/efficientnet-b0-ffpp-c23)).

## Overview

- **Input Modality**: Video files (`.mp4`, `.avi`, `.mov`, etc.).
- **Preprocessing**: Frame extraction (every 10th frame), MTCNN face cropping (with fallback center crop), $224 \times 224$ resizing, and ImageNet normalization.
- **Model Architecture**: PyTorch `torchvision.models.efficientnet_b0` with custom 2-class linear head (`nn.Linear(1280, 2)`).
- **Output Contract**:
  - `score`: $P(\text{synthetic})$ in $[0.0, 1.0]$.
  - `verdict`: `"synthetic"` if `score > 0.5` else `"authentic"`.
  - `confidence`: Distance from decision threshold $| \text{score} - 0.5 | \times 2$.
  - `model`: `"efficientnet-b0-ffpp-c23"`.

## Environment Variables

- `MODEL_CHECKPOINT_REPO`: HuggingFace Hub repository identifier (default: `"Xicor9/efficientnet-b0-ffpp-c23"`).

## Endpoints

- `GET /health`: Service health check.
- `POST /detect`: Upload video file for deepfake detection.
