import base64
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

import psutil
import torch
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, Header, status
from pydantic import BaseModel, Field

from infer import aggregate_scores, load_model, predict_frame
from preprocess import VideoPreprocessor
from telemetry import track_inference
from prometheus_client import make_asgi_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("video-classifier")

MODEL_VERSION = "efficientnet-b0-v1.0"

app = FastAPI(
    title="AEGIS Video Classifier Detector",
    description="EfficientNet-B0 / FaceForensics++ video frame classification microservice",
    version="0.1.0",
)

# Expose Prometheus Metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

preprocessor = VideoPreprocessor(target_size=(224, 224))
model_instance = None


def get_model():
    """Lazily loads and returns the singleton PyTorch model instance."""
    global model_instance
    if model_instance is None:
        logger.info("Initializing EfficientNet-B0 model instance...")
        model_instance = load_model()
    return model_instance


class Evidence(BaseModel):
    claim: str
    flags: List[str] = []


class DetectorRequest(BaseModel):
    job_id: str
    modality: str
    payload: str


class DetectorResponse(BaseModel):
    job_id: str
    confidence: float
    raw_score: float
    latency_ms: int
    ram_usage_mb: Optional[float] = None
    vram_usage_mb: Optional[float] = None
    model_version: str = MODEL_VERSION
    evidence: Evidence


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "video-classifier"


@app.get("/health", response_model=HealthResponse)
def health_check() -> Dict[str, str]:
    """Health check endpoint for service status monitoring."""
    return {"status": "healthy", "service": "video-classifier"}


@app.post("/detect", response_model=DetectorResponse)
@track_inference("video-classifier")
async def detect(
    request: Request,
    x_internal_token: Optional[str] = Header(default=None),
) -> DetectorResponse:
    """Detects video deepfake content using EfficientNet-B0 frame-level classification."""
    expected_token = os.getenv("INTERNAL_API_KEY")
    if expected_token and x_internal_token and x_internal_token != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")

    start_time = time.perf_counter()
    job_id = str(uuid.uuid4())
    content_type = request.headers.get("content-type", "")

    target_video_path: Optional[str] = None
    cleanup_path: Optional[str] = None

    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            upload_file = form.get("file")
            if not upload_file:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file uploaded.")
            suffix = Path(upload_file.filename).suffix if upload_file.filename else ".mp4"
            with tempfile.NamedTemporaryFile(suffix=suffix or ".mp4", delete=False) as tmp:
                content = await upload_file.read()
                if not content:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")
                tmp.write(content)
                target_video_path = tmp.name
                cleanup_path = tmp.name
        else:
            try:
                body = await request.json()
                req = DetectorRequest(**body)
                job_id = req.job_id
                payload_str = req.payload.strip()
            except Exception as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Malformed request payload: {exc}")

            if os.path.isabs(payload_str) and os.path.exists(payload_str):
                target_video_path = payload_str
            else:
                if "," in payload_str and "base64" in payload_str.split(",")[0]:
                    payload_str = payload_str.split(",", 1)[1]
                try:
                    decoded = base64.b64decode(payload_str)
                except Exception as exc:
                    raise HTTPException(status_code=400, detail=f"Failed to decode base64: {exc}")
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                    tmp.write(decoded)
                    target_video_path = tmp.name
                    cleanup_path = tmp.name

        try:
            frame_tensors = preprocessor.preprocess_video(target_video_path, sample_n=10)
        except Exception as e:
            logger.error(f"Error preprocessing video: {e}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to process video file: {str(e)}",
            )

        if not frame_tensors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not extract any valid frames from video.",
            )

        loaded_model = get_model()
        frame_scores = [predict_frame(loaded_model, tensor) for tensor in frame_tensors]

        raw_score = aggregate_scores(frame_scores)
        confidence = max(0.0, min(1.0, float(raw_score)))

        end_time = time.perf_counter()
        latency_ms = int(round((end_time - start_time) * 1000))

        process = psutil.Process()
        ram_usage_mb = round(process.memory_info().rss / (1024 * 1024), 2)
        vram_usage_mb = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 2) if torch.cuda.is_available() else None

        claim = f"Frame-level EfficientNet-B0 analysis computed fake probability of {confidence:.2f} across sampled frames."
        flags = ["high_fake_probability"] if confidence > 0.65 else (["authentic_frames"] if confidence < 0.35 else ["borderline_frames"])

        return DetectorResponse(
            job_id=job_id,
            confidence=round(confidence, 4),
            raw_score=round(raw_score, 4),
            latency_ms=latency_ms,
            ram_usage_mb=ram_usage_mb,
            vram_usage_mb=vram_usage_mb,
            model_version=MODEL_VERSION,
            evidence=Evidence(claim=claim, flags=flags),
        )
    finally:
        if cleanup_path and os.path.exists(cleanup_path):
            try:
                os.remove(cleanup_path)
            except Exception:
                pass
