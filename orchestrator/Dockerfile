# ── AEGIS Orchestration Engine ─────────────────────────────────────────────
# Manages input ingestion, metadata extraction, dynamic detector routing,
# and score aggregation across microservice detectors.
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ── System dependencies ────────────────────────────────────────────────────────
# curl     : healthcheck probe
# sqlite3  : CLI access to the decision audit log
# ffmpeg   : provides ffprobe for modality, audio track, and resolution inspection
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy entire orchestrator source into /app
COPY . /app

# Set working directory to the inner app folder where main.py and logic modules reside
WORKDIR /app/app
ENV PYTHONPATH=/app/app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]