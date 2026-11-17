# ── AEGIS Orchestration Engine ─────────────────────────────────────────────
# Manages input ingestion, metadata extraction, dynamic detector routing,
# and score aggregation across microservice detectors.
FROM python:3.11.18-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ── System dependencies ────────────────────────────────────────────────────────
# curl     : healthcheck probe
# sqlite3  : CLI access to the decision audit log
# ffmpeg   : provides ffprobe for modality, audio track, and resolution inspection
RUN apt-get update && apt-get upgrade -y --no-install-recommends && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip==26.3 setuptools==84.2.1 wheel==0.48.0 \
    && rm -rf /usr/local/lib/python3.*/ensurepip \
    && pip install --no-cache-dir -r requirements.txt

# Copy entire orchestrator source into /app
COPY --chown=appuser:appuser . /app
RUN chown -R appuser:appuser /app

# Set working directory to the inner app folder where main.py and logic modules reside
WORKDIR /app/app
ENV PYTHONPATH=/app/app:/repo

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fs http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
