# ── AASIST Audio Deepfake Detector ─────────────────────────────────────────────
# Detects audio spoofing / voice cloning using a Graph-Attention network.
# Runs CPU-only inference (no GPU required for stub/dev; swap torch index for CUDA in prod).
FROM python:3.11-slim

# Prevent interactive prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# ── System dependencies ────────────────────────────────────────────────────────
# libsndfile1  : required by soundfile / librosa for audio I/O
# curl         : used by docker-compose healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies (layered for cache efficiency) ─────────────────────────
# 1. Upgrade pip first (cheap, cached separately)
RUN pip install --no-cache-dir --upgrade pip

# 2. CPU-only PyTorch — largest layer, cached until requirements change
RUN pip install --no-cache-dir \
    torch==2.2.2+cpu torchaudio==2.2.2+cpu \
    --extra-index-url https://download.pytorch.org/whl/cpu

# 3. App requirements (excluding torch lines already installed above)
COPY requirements.txt .
RUN grep -vE "^(torch|#)" requirements.txt > /tmp/reqs.txt \
    && pip install --no-cache-dir -r /tmp/reqs.txt \
    && rm /tmp/reqs.txt

# ── Application source ─────────────────────────────────────────────────────────
# AASIST.pth model weights live at the detector root and are included here.
COPY . /app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
