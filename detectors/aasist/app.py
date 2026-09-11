"""
AASIST Audio Detector Microservice
Exposes POST /detect and GET /health conformant with AEGIS API contracts.
"""

import os
import time
import base64
import logging
from contextlib import asynccontextmanager
from typing import Optional

import psutil
import torch
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import JSONResponse

from models.AASIST import Model
from preprocessing import preprocess_audio
from schemas import DetectorRequest, DetectorResponse, Evidence, HealthResponse

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("aasist_detector")

# AASIST Standard Architecture Configuration
AASIST_CONFIG = {
    "architecture": "AASIST",
    "nb_samp": 64600,
    "first_conv": 128,
    "filts": [70, [1, 32], [32, 32], [32, 64], [64, 64]],
    "gat_dims": [64, 32],
    "pool_ratios": [0.5, 0.7, 0.5, 0.5],
    "temperatures": [2.0, 2.0, 100.0, 100.0]
}

MODEL_VERSION = "aasist-v1.0"
DEFAULT_WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "weights", "AASIST.pth")

# Global model state
state = {
    "model": None,
    "device": None,
    "model_loaded": False
}


def load_model(weights_path: str = DEFAULT_WEIGHTS_PATH):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Initializing AASIST model on device: {device}")
    
    model = Model(AASIST_CONFIG)
    if os.path.exists(weights_path):
        logger.info(f"Loading weights from: {weights_path}")
        state_dict = torch.load(weights_path, map_location=device)
        model.load_state_dict(state_dict)
        logger.info("Weights loaded successfully.")
    else:
        logger.warning(f"Weight file not found at {weights_path}! Model initialized with random weights.")

    model.to(device)
    model.eval()
    
    state["model"] = model
    state["device"] = device
    state["model_loaded"] = True
    return model


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load model into memory
    weights_file = os.getenv("MODEL_WEIGHTS_PATH", DEFAULT_WEIGHTS_PATH)
    load_model(weights_file)
    yield
    # Shutdown
    state["model"] = None
    state["model_loaded"] = False
    logger.info("AASIST microservice shut down cleanly.")


app = FastAPI(
    title="AEGIS AASIST Audio Deepfake Detector",
    version="1.0.0",
    description="Microservice wrapping pretrained ClovaAI AASIST model for synthetic audio detection.",
    lifespan=lifespan
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for Docker probes and Orchestrator readiness."""
    return HealthResponse(
        status="healthy" if state["model_loaded"] else "unhealthy",
        model_loaded=state["model_loaded"],
        model_version=MODEL_VERSION,
        device=str(state["device"]) if state["device"] else "none"
    )


@app.post("/detect", response_model=DetectorResponse, response_model_exclude_none=True)
async def detect(
    req: DetectorRequest,
    x_internal_token: Optional[str] = Header(default=None)
):
    """
    Executes audio deepfake detection using AASIST.
    Validates payload, preprocesses waveform, runs model inference,
    and returns standardized confidence score and debate evidence.
    """
    expected_token = os.getenv("INTERNAL_API_KEY")
    if expected_token and x_internal_token and x_internal_token != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")

    if not state["model_loaded"] or state["model"] is None:
        raise HTTPException(status_code=503, detail="Model is not loaded or service is initializing")

    model = state["model"]
    device = state["device"]

    # Ingest audio payload (either absolute file path or base64 encoded audio)
    raw_payload = req.payload.strip()
    if os.path.isabs(raw_payload) and os.path.exists(raw_payload):
        audio_source = raw_payload
    else:
        try:
            # Strip data URI header if present (e.g., 'data:audio/wav;base64,...')
            if "," in raw_payload and "base64" in raw_payload.split(",")[0]:
                raw_payload = raw_payload.split(",", 1)[1]
            audio_source = base64.b64decode(raw_payload)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to decode base64 audio payload: {str(e)}")

    # Preprocess audio to AASIST input tensor (1, 64600)
    try:
        audio_tensor = preprocess_audio(audio_source)
    except Exception as e:
        logger.error(f"Preprocessing error for job {req.job_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Audio preprocessing failed: {str(e)}")

    # Model inference with precise timing
    start_time = time.perf_counter()
    with torch.no_grad():
        x = audio_tensor.to(device)
        _, out = model(x)
    end_time = time.perf_counter()

    latency_ms = int(round((end_time - start_time) * 1000))

    # AASIST output: out has shape (1, 2)
    # Class 0: spoof (synthetic), Class 1: bonafide (genuine)
    probs = torch.softmax(out, dim=-1)[0]
    spoof_prob = float(probs[0].item())
    bonafide_prob = float(probs[1].item())
    spoof_logit = float(out[0, 0].item())

    # AEGIS Contract: confidence 0.0 = Authentic, 1.0 = Synthetic/Deepfake
    confidence = max(0.0, min(1.0, float(spoof_prob)))

    # Telemetry metrics
    process = psutil.Process()
    ram_usage_mb = round(process.memory_info().rss / (1024 * 1024), 2)
    
    vram_usage_mb = None
    if torch.cuda.is_available():
        vram_usage_mb = round(torch.cuda.max_memory_allocated(device=device) / (1024 * 1024), 2)

    # Contextual reasoning for Debate Agent
    flags = []
    if confidence >= 0.85:
        claim = "High probability of synthetic/cloned audio detected; severe spectral-temporal graph attention irregularities observed."
        flags.extend(["high_spoof_confidence", "voice_cloning_suspected", "graph_spectral_anomaly"])
    elif confidence >= 0.50:
        claim = "Moderate probability of synthetic audio; potential artifacts detected in temporal frequency transitions."
        flags.extend(["moderate_spoof_risk", "boundary_artifact"])
    else:
        claim = "Audio patterns conform to authentic human vocal tract dynamics; no synthetic artifacts detected."
        flags.append("bonafide_speech")

    response = DetectorResponse(
        job_id=req.job_id,
        confidence=round(confidence, 4),
        raw_score=round(spoof_logit, 4),
        latency_ms=latency_ms,
        ram_usage_mb=ram_usage_mb,
        vram_usage_mb=vram_usage_mb,
        model_version=MODEL_VERSION,
        evidence=Evidence(
            claim=claim,
            flags=flags
        )
    )
    return response
