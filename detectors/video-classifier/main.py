import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from infer import aggregate_scores, predict_frame
from preprocess import VideoPreprocessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("video-classifier")

app = FastAPI(
    title="AEGIS Video Classifier Detector",
    description="Xception / FaceForensics++ video frame classification microservice",
    version="0.1.0",
)

preprocessor = VideoPreprocessor(target_size=(299, 299))


# TODO: Reconcile response schema once official Week 1 schema is finalized.
class DetectionResponse(BaseModel):
    modality: str = Field("video", description="Input media modality")
    score: float = Field(..., description="0-1 authenticity score (1.0 = authentic, 0.0 = synthetic)")
    verdict: str = Field(..., description="Classification verdict: 'authentic' or 'synthetic'")
    confidence: float = Field(..., description="Confidence level in [0.0, 1.0]")
    model: str = Field("xception-ffpp", description="Model architecture/weights key")


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "video-classifier"


@app.get("/health", response_model=HealthResponse)
def health_check() -> Dict[str, str]:
    """Health check endpoint for service status monitoring."""
    return {"status": "healthy", "service": "video-classifier"}


@app.post("/detect", response_model=DetectionResponse)
async def detect_video(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Detects video deepfake content using Xception frame-level classification.

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

        # Step 2: Per-frame stub inference
        frame_scores = [predict_frame(tensor) for tensor in frame_tensors]

        # Step 3: Score aggregation
        score = aggregate_scores(frame_scores)
        verdict = "authentic" if score >= 0.5 else "synthetic"
        confidence = max(score, 1.0 - score)

        # TODO: Reconcile response schema once official Week 1 schema is finalized.
        return {
            "modality": "video",
            "score": round(score, 4),
            "verdict": verdict,
            "confidence": round(confidence, 4),
            "model": "xception-ffpp",
        }
    finally:
        if os.path.exists(temp_file.name):
            try:
                os.remove(temp_file.name)
            except Exception as e:
                logger.warning(f"Could not delete temporary file {temp_file.name}: {e}")
