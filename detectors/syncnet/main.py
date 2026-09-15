"""
SyncNet Audio-Visual Synchronization Detector — FastAPI Microservice.

Exposes:
  GET  /health  — Liveness & readiness probe.
  GET  /metrics — Prometheus metrics.
  POST /detect  — Accepts video payload (JSON DetectorRequest per SCHEMA.md or multipart file upload)
                  and returns standardized DetectorResponse.
"""
from __future__ import annotations

import base64
import logging
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import psutil
import torch
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from infer import MODEL_VERSION, SyncNetInference
from models.syncnet import load_syncnet_model
from preprocess import SyncNetPreprocessor
from schemas import DetectorRequest, DetectorResponse, Evidence, HealthResponse
from telemetry import track_inference

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("syncnet")

# Global singleton state
state = {
    "model": None,
    "device": None,
    "inference": None,
    "preprocessor": None,
    "model_loaded": False,
}


def init_service():
    """Initializes PyTorch model, inference engine, and preprocessor."""
    if state["model_loaded"] and state["inference"] is not None:
        return

    weights_path = os.getenv(
        "SYNCNET_WEIGHTS_PATH",
        os.path.join(os.path.dirname(__file__), "weights", "syncnet_v2.model"),
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Initializing SyncNet detector on device: {device}...")

    model, device = load_syncnet_model(weights_path=weights_path, device=device)
    inference = SyncNetInference(model=model, device=device)
    preprocessor = SyncNetPreprocessor(device=device)

    state["model"] = model
    state["device"] = device
    state["inference"] = inference
    state["preprocessor"] = preprocessor
    state["model_loaded"] = True
    logger.info("SyncNet microservice initialization complete.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_service()
    yield
    state["model"] = None
    state["inference"] = None
    state["preprocessor"] = None
    state["model_loaded"] = False
    logger.info("SyncNet microservice shut down cleanly.")


app = FastAPI(
    title="AEGIS SyncNet Audio-Visual Sync Detector",
    description="Microservice evaluating audio-to-video lip synchronization consistency.",
    version="1.0.0",
    lifespan=lifespan,
)

# Expose Prometheus Metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Readiness probe for Orchestrator and Docker healthchecks."""
    if not state["model_loaded"]:
        init_service()

    return HealthResponse(
        status="healthy" if state["model_loaded"] else "unhealthy",
        service="syncnet",
        model_loaded=state["model_loaded"],
        model_version=MODEL_VERSION,
        device=str(state["device"]) if state["device"] else "none",
    )


@app.post("/detect", response_model=DetectorResponse, response_model_exclude_none=True)
@track_inference("syncnet")
async def detect(
    request: Request,
    x_internal_token: Optional[str] = Header(default=None),
) -> DetectorResponse:
    """Analyzes audio-visual lip-sync consistency.

    Supports both:
    1. Standard AEGIS JSON contract: {"job_id": "...", "modality": "video", "payload": "..."}
    2. Multipart form upload with 'file' field for local testing.
    """
    expected_token = os.getenv("INTERNAL_API_KEY")
    if expected_token and x_internal_token and x_internal_token != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")

    if not state["model_loaded"]:
        init_service()

    preprocessor: SyncNetPreprocessor = state["preprocessor"]
    inference: SyncNetInference = state["inference"]

    content_type = request.headers.get("content-type", request.headers.get("content_type", ""))
    target_video_path: Optional[str] = None
    cleanup_path: Optional[str] = None
    job_id = str(uuid.uuid4())

    start_time = time.perf_counter()

    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            upload_file = form.get("file")
            if not upload_file:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No file uploaded in form data.",
                )
            job_id_form = form.get("job_id")
            if job_id_form and isinstance(job_id_form, str):
                job_id = job_id_form

            suffix = Path(upload_file.filename).suffix if upload_file.filename else ".mp4"
            with tempfile.NamedTemporaryFile(suffix=suffix or ".mp4", delete=False) as tmp:
                content = await upload_file.read()
                if not content:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Uploaded file is empty.",
                    )
                tmp.write(content)
                target_video_path = tmp.name
                cleanup_path = tmp.name
        else:
            # JSON Payload per SCHEMA.md
            try:
                body = await request.json()
                req = DetectorRequest(**body)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Malformed DetectorRequest payload: {exc}",
                )

            job_id = req.job_id
            payload_str = req.payload.strip()

            # Check if payload is an existing absolute file path
            if os.path.isabs(payload_str) and os.path.exists(payload_str):
                target_video_path = payload_str
                cleanup_path = None  # Do NOT delete caller's external file
            else:
                # Base64 encoded payload
                if "," in payload_str and "base64" in payload_str.split(",")[0]:
                    payload_str = payload_str.split(",", 1)[1]
                try:
                    decoded = base64.b64decode(payload_str)
                except Exception as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Failed to decode base64 video payload: {exc}",
                    )
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                    tmp.write(decoded)
                    target_video_path = tmp.name
                    cleanup_path = tmp.name

        # Run preprocessing: video lip sequences & audio MFCC
        try:
            vid_seqs, aud_seqs, has_audio = preprocessor.preprocess(target_video_path)
        except Exception as exc:
            logger.error(f"Preprocessing failed for job {job_id}: {exc}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to process video media: {exc}",
            )

        # Run inference & scoring
        confidence, raw_score, evidence = inference.score_video(
            vid_tensors=vid_seqs,
            aud_tensors=aud_seqs,
            has_audio=has_audio,
        )

        end_time = time.perf_counter()
        latency_ms = int(round((end_time - start_time) * 1000))

        # Measure RAM / VRAM
        process = psutil.Process()
        ram_usage_mb = round(process.memory_info().rss / (1024 * 1024), 2)
        vram_usage_mb = None
        if torch.cuda.is_available():
            vram_usage_mb = round(torch.cuda.max_memory_allocated(device=state["device"]) / (1024 * 1024), 2)

        return DetectorResponse(
            job_id=job_id,
            confidence=confidence,
            raw_score=raw_score,
            latency_ms=latency_ms,
            ram_usage_mb=ram_usage_mb,
            vram_usage_mb=vram_usage_mb,
            model_version=MODEL_VERSION,
            evidence=evidence,
        )

    finally:
        # Cleanup temporary file ONLY if we allocated one
        if cleanup_path and os.path.exists(cleanup_path):
            try:
                os.remove(cleanup_path)
            except Exception:
                pass
