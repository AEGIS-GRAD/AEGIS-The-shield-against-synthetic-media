# ── AEGIS Text Authenticity Detector (Desklib DeBERTa-v3-large + Perplexity) ──
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    AEGIS_TEXT_PRELOAD=1 \
    AEGIS_TEXT_FP16=1 \
    AEGIS_TEXT_USE_FINETUNED=1 \
    AEGIS_TEXT_ENABLE_PPL=1 \
    AEGIS_TEXT_ENABLE_BINOCULARS=0 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

# curl is used exclusively by the container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

# Optional override allows slim CPU wheel builds in constrained CI runners
ARG TORCH_INDEX_URL=""
COPY requirements.txt .
RUN if [ -n "$TORCH_INDEX_URL" ]; then \
        pip install --no-cache-dir torch>=2.4.0 --index-url "$TORCH_INDEX_URL"; \
    fi && \
    pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/models /shared_volume

COPY . /app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
