# ── AASIST Audio Deepfake Detector ─────────────────────────────────────────────
FROM python:3.11.18-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get upgrade -y --no-install-recommends && apt-get install -y --no-install-recommends \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser

# CPU-only PyTorch + torchaudio (matching pinned versions in requirements.txt)
RUN pip install --no-cache-dir --upgrade pip==26.3 setuptools==84.2.1 wheel==0.48.0 && \
    rm -rf /usr/local/lib/python3.*/ensurepip && \
    pip install --no-cache-dir \
    torch==2.14.1 torchaudio==2.11.0 \
    --extra-index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN grep -vE "^(torch|#)" requirements.txt > /tmp/reqs.txt \
    && pip install --no-cache-dir -r /tmp/reqs.txt \
    && rm /tmp/reqs.txt

COPY --chown=appuser:appuser . /app
RUN chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fs http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
