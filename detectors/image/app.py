"""
Community Forensics Image Deepfake Detector Microservice.
Exposes POST /detect and GET /health conformant with AEGIS API contracts.
"""

import os
import time
import base64
import logging
from io import BytesIO
from contextlib import asynccontextmanager
from typing import Optional

import psutil
import torch
import torchvision.transforms as T
from fastapi import FastAPI, HTTPException, Header
from PIL import Image
from prometheus_client import make_asgi_app

from models.loader import load_model, MODEL_VERSION
from evidence.frequency_check import check_frequency
from evidence.exif_check import check_exif
from schemas import DetectorRequest, DetectorResponse, Evidence, HealthResponse
from telemetry import track_inference

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("image_detector")

# Standard ViT 384x384 image preprocessing
TRANSFORM = T.Compose([
    T.Resize((384, 384)),
    T.ToTensor(),
    T.Normalize(mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]),
])

state = {"model": None, "device": None, "model_loaded": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    weights_dir = os.getenv(
        "MODEL_WEIGHTS_DIR",
        os.path.join(os.path.dirname(__file__), "weights")
    )
    model, device = load_model(weights_dir)
    state["model"] = model
    state["device"] = device
    state["model_loaded"] = True
    logger.info("Community Forensics image detector initialized.")
    yield
    state["model"] = None
    state["model_loaded"] = False
    logger.info("Community Forensics image detector shut down cleanly.")


app = FastAPI(
    title="AEGIS Community Forensics Image Detector",
    version="1.0.0",
    description="Microservice wrapping OwensLab/commfor-model-384 with FFT and EXIF evidence.",
    lifespan=lifespan
)

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy" if state["model_loaded"] else "unhealthy",
        model_loaded=state["model_loaded"],
        model_version=MODEL_VERSION,
        device=str(state["device"]) if state["device"] else "none"
    )


@app.post("/detect", response_model=DetectorResponse, response_model_exclude_none=True)
@track_inference("commfor")
async def detect(
    req: DetectorRequest,
    x_internal_token: Optional[str] = Header(default=None)
):
    # Verify internal mesh token
    if os.getenv("AEGIS_MESH_STRICT", "").lower() not in ("1", "true", "yes", "on"):
        expected = os.getenv("INTERNAL_API_KEY")
        if expected and x_internal_token and x_internal_token != expected:
            raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")

    if not state["model_loaded"]:
        raise HTTPException(status_code=503, detail="Model not loaded")

    model = state["model"]
    device = state["device"]

    # Decode image
    raw = req.payload.strip()
    try:
        if os.path.isabs(raw) and os.path.exists(raw):
            pil_image = Image.open(raw).convert("RGB")
        else:
            if "," in raw and "base64" in raw.split(",")[0]:
                raw = raw.split(",", 1)[1]
            pil_image = Image.open(BytesIO(base64.b64decode(raw))).convert("RGB")
    except Exception as e:
        logger.warning(f"Payload not applicable or unreadable for job {req.job_id}: {e}")
        return DetectorResponse(
            job_id=req.job_id,
            confidence=0.5,
            raw_score=0.0,
            latency_ms=0,
            model_version=MODEL_VERSION,
            evidence=Evidence(
                claim="Payload is not applicable or cannot be decoded as an image.",
                flags=["not_applicable"]
            )
        )

    # Run evidence analysis on original resolution
    freq_result = check_frequency(pil_image)
    exif_result = check_exif(pil_image)

    # Preprocess & convert to FP16
    tensor = TRANSFORM(pil_image).unsqueeze(0).half().to(device)

    # Inference timing
    start_time = time.perf_counter()
    with torch.no_grad():
        raw_logit = model(tensor)
    latency_ms = int(round((time.perf_counter() - start_time) * 1000))

    raw_score = float(raw_logit.squeeze().item())
    confidence = float(torch.sigmoid(torch.tensor(raw_score)).item())
    confidence = max(0.0, min(1.0, confidence))

    # RAM and VRAM profiling
    ram_mb = round(psutil.Process().memory_info().rss / (1024 * 1024), 2)
    vram_mb = None
    if torch.cuda.is_available():
        vram_mb = round(torch.cuda.max_memory_allocated(device) / (1024 * 1024), 2)

    # Determine evidence flags & claim
    flags = []
    if freq_result["flag"]:
        flags.append("frequency_anomaly")
    if exif_result["exif_missing"]:
        flags.append("exif_missing")
    if exif_result["software_tag_present"]:
        flags.append("software_tag_present")
    if confidence >= 0.85:
        flags.append("high_confidence_synthetic")
    elif 0.40 <= confidence <= 0.60:
        flags.append("borderline")

    if confidence >= 0.85:
        claim = "Strong structural, frequency, or generator-specific synthetic artifacts detected."
    elif confidence >= 0.50:
        claim = "Moderate indicators of artificial generation detected."
    else:
        claim = "Visual texture and metadata conform to authentic photographic distribution."

    return DetectorResponse(
        job_id=req.job_id,
        confidence=round(confidence, 4),
        raw_score=round(raw_score, 4),
        latency_ms=latency_ms,
        ram_usage_mb=ram_mb,
        vram_usage_mb=vram_mb,
        model_version=MODEL_VERSION,
        evidence=Evidence(claim=claim, flags=flags if flags else None)
    )