# ── Video Frame Classifier Detector ──────────────────────────────────────────
# Detects spatial deepfake artifacts in video frames using an EfficientNet backbone.
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# ── System dependencies ────────────────────────────────────────────────────────
# libgl1 / libglib2.0-0  : required by OpenCV (headless mode)
# ffmpeg                 : video decoding and frame extraction
# curl                   : healthcheck probe
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ────────────────────────────────────────────────────────
RUN pip install --no-cache-dir --upgrade pip

# CPU-only PyTorch + Torchvision
RUN pip install --no-cache-dir \
    torch==2.2.2+cpu torchvision==0.17.2+cpu \
    --extra-index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN grep -vE "^(torch|#)" requirements.txt > /tmp/reqs.txt \
    && pip install --no-cache-dir -r /tmp/reqs.txt \
    && rm /tmp/reqs.txt

# Create models directory for weights
RUN mkdir -p /app/models

# ── Application source ─────────────────────────────────────────────────────────
COPY . /app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
