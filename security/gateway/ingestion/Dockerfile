FROM python:3.11.18-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser

COPY security/gateway/ingestion/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm -f /tmp/requirements.txt

COPY --chown=appuser:appuser security /app/security
RUN chown -R appuser:appuser /app

ENV PYTHONPATH=/app:/app/security
ENV AEGIS_INGESTION_HOST=0.0.0.0
ENV AEGIS_INGESTION_PORT=8443
ENV AEGIS_TELEMETRY_HOST=0.0.0.0
ENV AEGIS_TELEMETRY_PORT=8444

USER appuser
EXPOSE 8443 8444

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fs http://localhost:8444/telemetry/health || exit 1

CMD ["python", "/app/security/gateway/ingestion/server.py"]
