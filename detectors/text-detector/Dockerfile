# ── AEGIS Text Authenticity Detector (Desklib DeBERTa-v3-large + Perplexity) ──
FROM python:3.11.18-slim

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
RUN apt-get update && apt-get upgrade -y --no-install-recommends && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser

# Optional override allows slim CPU wheel builds in constrained CI runners
ARG TORCH_INDEX_URL=""
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip==26.3 setuptools==84.2.1 wheel==0.48.0 && \
    rm -rf /usr/local/lib/python3.*/ensurepip && \
    if [ -n "$TORCH_INDEX_URL" ]; then \
        pip install --no-cache-dir torch==2.14.1 --index-url "$TORCH_INDEX_URL"; \
    fi && \
    pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/models /app/.cache/huggingface /shared_volume
COPY --chown=appuser:appuser . /app
RUN chown -R appuser:appuser /app /shared_volume

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=3 \
    CMD curl -fs http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
