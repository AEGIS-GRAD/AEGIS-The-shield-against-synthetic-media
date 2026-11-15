FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi>=0.110.0 \
    uvicorn[standard]>=0.29.0 \
    pydantic>=2.6.0 \
    opencv-python-headless>=4.8.0 \
    numpy>=1.24.0 \
    PyWavelets>=1.4.1 \
    cryptography>=41.0.0 \
    prometheus-client>=0.20.0 \
    httpx>=0.27.0

COPY security /app/security

ENV PYTHONPATH=/app:/app/security
ENV AEGIS_INGESTION_HOST=0.0.0.0
ENV AEGIS_INGESTION_PORT=8443
ENV AEGIS_TELEMETRY_HOST=0.0.0.0
ENV AEGIS_TELEMETRY_PORT=8444

EXPOSE 8443 8444

CMD ["python", "/app/security/gateway/ingestion/server.py"]
