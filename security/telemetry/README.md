# Telemetry & Monitoring Infrastructure

This module provides the central monitoring capabilities for the AEGIS microservices architecture, exposing system health, performance metrics, and application-specific metrics to Prometheus and Grafana.

## Overview

We have integrated **Prometheus** for metrics scraping and **Grafana** (to be configured later) for dashboarding. The infrastructure automatically tracks:
- **System Metrics**: CPU, Memory, File Descriptors (via `prometheus-client` defaults).
- **Application Metrics**: Inference latency, request volume, and PyTorch GPU memory allocations.

### Architecture

- **Prometheus Service**: Runs on port `9090`. It is configured to scrape all microservices listed in `prometheus.yml`.
- **Grafana Service**: Runs on port `3001` (to be fully provisioned in a subsequent phase).
- **Decorators**: The `telemetry.py` file inside each detector contains a `@track_inference(model_name)` wrapper. This wrapper intercepts the model's core execution and emits metrics to a `/metrics` endpoint.

## How to Instrument a New Microservice

To add telemetry to a new microservice (or an existing one that hasn't been instrumented yet), follow these steps:

1. **Install Dependencies**:
   Ensure `prometheus-client` is in the microservice's `requirements.txt`:
   ```text
   prometheus-client==0.20.0
   ```

2. **Add `telemetry.py`**:
   Copy the `telemetry.py` file from one of the instrumented detectors (e.g., `detectors/aasist/telemetry.py`) into the new microservice directory.

3. **Mount the Metrics Endpoint**:
   In the microservice's main entry point (e.g., `app.py` or `main.py`), import `metrics_app` and mount it to FastAPI:
   ```python
   from telemetry import metrics_app, track_inference

   # ... after initializing FastAPI app ...
   app.mount("/metrics", metrics_app)
   ```

4. **Decorate the Target Function**:
   Wrap the core processing or route function with the `@track_inference` decorator. Provide the name of the model so it gets labeled correctly in Prometheus.
   ```python
   @app.post("/detect")
   @track_inference("my-new-model")
   async def detect(file: UploadFile):
       # Model logic goes here
       ...
   ```

5. **Update Prometheus Config**:
   Add the new microservice to `security/telemetry/prometheus.yml` under the `scrape_configs` section:
   ```yaml
     - job_name: 'new_detector'
       static_configs:
         - targets: ['aegis_detector_new:8000']
   ```

## Checking Metrics

Once the containers are running (`docker-compose up -d`), you can view the raw metrics at:
- `http://localhost:<SERVICE_PORT>/metrics`

You can query the aggregated metrics using Prometheus at:
- `http://localhost:9090/`

**Key Custom Metrics:**
- `detector_inference_latency_seconds`: Histogram of inference latency.
- `detector_inference_calls_total`: Counter for total requests processed.
- `detector_gpu_memory_allocated_bytes`: PyTorch VRAM consumption.
