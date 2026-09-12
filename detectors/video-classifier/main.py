import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from infer import aggregate_scores, load_model, predict_frame
from preprocess import VideoPreprocessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("video-classifier")

app = FastAPI(
    title="AEGIS Video Classifier Detector",
    description="EfficientNet-B0 / FaceForensics++ video frame classification microservice",
    version="0.1.0",
)

preprocessor = VideoPreprocessor(target_size=(224, 224))
model_instance = None


def get_model():
    """Lazily loads and returns the singleton PyTorch model instance."""
    global model_instance
    if model_instance is None:
        logger.info("Initializing EfficientNet-B0 model instance...")
        model_instance = load_model()
    return model_instance


class DetectionResponse(BaseModel):
    modality: str = Field("video", description="Input media modality")
    score: float = Field(..., description="0-1 authenticity score (1.0 = synthetic, 0.0 = authentic)")
    verdict: str = Field(..., description="Classification verdict: 'synthetic' or 'authentic'")
    confidence: float = Field(..., description="Confidence level in [0.0, 1.0]")
    model: str = Field("efficientnet-b0-ffpp-c23", description="Model architecture/weights key")


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "video-classifier"


@app.get("/health", response_model=HealthResponse)
def health_check() -> Dict[str, str]:
    """Health check endpoint for service status monitoring."""
    return {"status": "healthy", "service": "video-classifier"}


@app.post("/detect", response_model=DetectionResponse)
async def detect_video(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Detects video deepfake content using EfficientNet-B0 frame-level classification.

    Args:
        file: Uploaded video file.

    Returns:
        JSON response with authenticity score, verdict, confidence, and model identifier.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No video file provided."
        )

    # Save uploaded file to temporary location for OpenCV reading
    suffix = Path(file.filename).suffix or ".mp4"
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        content = await file.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty."
            )
        temp_file.write(content)
        temp_file.close()

        # Step 1: Preprocess video frames
        try:
            frame_tensors = preprocessor.preprocess_video(temp_file.name, sample_n=10)
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

        # Step 2: Per-frame inference using real model
        loaded_model = get_model()
        frame_scores = [predict_frame(loaded_model, tensor) for tensor in frame_tensors]

        # Step 3: Score aggregation & decision contract
        score = aggregate_scores(frame_scores)
        verdict = "synthetic" if score > 0.5 else "authentic"
        confidence = abs(score - 0.5) * 2.0

        return {
            "modality": "video",
            "score": round(score, 4),
            "verdict": verdict,
            "confidence": round(confidence, 4),
            "model": "efficientnet-b0-ffpp-c23",
        }
    finally:
        if os.path.exists(temp_file.name):
            try:
                os.remove(temp_file.name)
            except Exception as e:
                logger.warning(f"Could not delete temporary file {temp_file.name}: {e}")
