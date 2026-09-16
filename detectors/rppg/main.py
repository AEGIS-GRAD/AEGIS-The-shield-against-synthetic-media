"""rPPG heartbeat-consistency detector — FastAPI microservice.

POST /detect  — accepts a video upload, runs the rPPG pipeline, and returns
               a detection result matching the AEGIS shared response contract.
GET  /health  — liveness check.

Score/verdict contract (shared/docs/model_scope.md):
  score     : float in [0, 1], P(synthetic) — higher = more likely fake.
  verdict   : "synthetic" if score > 0.5 else "authentic".
  confidence: abs(score - 0.5) * 2  — distance from the decision boundary.

rPPG-specific score mapping
---------------------------
  score = 1 - signal_quality_score

Rationale: a high-quality, periodic BVP signal is a strong physiological
indicator of a real face; low signal quality suggests the video may lack
genuine skin-tone micro-variation (consistent with a synthetic/deepfake face).

TODO: This is a placeholder heuristic mapping, NOT a validated detection
threshold.  Proper calibration requires labelled real/fake video pairs and
empirical ROC analysis.  See task description for context.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from preprocess import RppgPreprocessor
from rppg_extract import estimate_heart_rate, extract_pulse_signal, signal_quality_score

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rppg")

app = FastAPI(
    title="AEGIS rPPG Heartbeat-Consistency Detector",
    description=(
        "Classical rPPG (CHROM algorithm) microservice that detects deepfakes "
        "by analysing heart-rate signal consistency in face videos."
    ),
    version="0.1.0",
)

preprocessor = RppgPreprocessor()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    claim: str = Field(..., description="A human-readable claim regarding physiological consistency.")
    flags: Optional[List[str]] = Field(default=None, description="Specific heuristic flags triggered.")


class DetectionResponse(BaseModel):
    job_id: str = Field(..., description="Unique job identifier.")
    modality: str = Field("video", description="Input media modality")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score. 0.0 = Authentic, 1.0 = Synthetic, 0.5 = Inconclusive.",
    )
    raw_score: float = Field(..., description="Uncalibrated quality or raw difference score.")
    score: Optional[float] = Field(None, description="P(synthetic) in [0, 1].")
    verdict: str = Field(
        ..., description="Classification verdict: 'synthetic', 'authentic', or 'inconclusive'"
    )
    model: str = Field("rppg-chrom", description="Algorithm identifier")
    model_version: str = Field("rppg-chrom-v1.0", description="Model version")
    estimated_bpm: float = Field(
        ..., description="Estimated heart rate in beats-per-minute (diagnostic)"
    )
    latency_ms: int = Field(0, description="Processing time in milliseconds.")
    evidence: Evidence = Field(..., description="Forensic evidence claim and flags.")


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "rppg"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
def health_check() -> Dict[str, str]:
    """Liveness / readiness probe for container orchestration."""
    return {"status": "healthy", "service": "rppg"}


@app.post("/detect", response_model=DetectionResponse)
async def detect_video(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Detect deepfake content via rPPG heartbeat-consistency analysis.

    Runs the full pipeline with edge-case guardrails:
      1. Preprocess & extract per-frame mean face RGB with duration/illumination/occlusion validation.
      2. If guardrails triggered (short clip, dark lighting, occluded face), return inconclusive neutral response.
      3. Apply CHROM algorithm + bandpass filter.
      4. Estimate heart rate and spectral purity.
      5. Output schema-conforming response.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No video file provided.",
        )

    suffix = Path(file.filename).suffix or ".mp4"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    start_time = time.perf_counter()
    job_id = str(uuid.uuid4())

    try:
        content = await file.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )
        tmp.write(content)
        tmp.close()

        # Step 1 — preprocessing & guardrails evaluation
        try:
            rgb_signals, fps, meta = preprocessor.preprocess_video(tmp.name)
        except Exception as exc:
            logger.error("Preprocessing failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to extract face signals from video: {exc}",
            ) from exc

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        # Guardrail check: if edge cases triggered, return neutral inconclusive result
        if meta.get("guardrail_triggered", False):
            logger.info("Guardrail triggered for job %s: flags=%s claim=%s", job_id, meta["flags"], meta["claim"])
            return {
                "job_id": job_id,
                "modality": "video",
                "confidence": 0.5,
                "raw_score": 0.0,
                "score": 0.5,
                "verdict": "inconclusive",
                "model": "rppg-chrom",
                "model_version": "rppg-chrom-v1.0",
                "estimated_bpm": 0.0,
                "latency_ms": elapsed_ms,
                "evidence": {
                    "claim": meta["claim"],
                    "flags": meta["flags"],
                },
            }

        # Step 2 — CHROM pulse extraction
        try:
            pulse = extract_pulse_signal(rgb_signals, fps)
        except Exception as exc:
            logger.error("Pulse extraction failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to extract pulse signal: {exc}",
            ) from exc

        # Step 3 — Heart rate + signal quality
        try:
            bpm = estimate_heart_rate(pulse, fps)
        except Exception as exc:
            logger.warning("Heart-rate estimation failed: %s. Defaulting to 60 BPM.", exc)
            bpm = 60.0

        quality = signal_quality_score(pulse)

        # Step 4 — Score/verdict mapping with sanity check
        score = float(1.0 - quality)
        score = max(0.0, min(1.0, score))
        verdict = "synthetic" if score > 0.5 else "authentic"
        confidence = abs(score - 0.5) * 2.0
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        claim = (
            f"BVP pulse signal extracted via CHROM with estimated heart rate of {bpm:.1f} BPM "
            f"(spectral purity: {quality:.2f})."
        )
        flags = []
        if bpm < 45.0 or bpm > 180.0:
            flags.append("atypical_heart_rate")

        logger.info(
            "rPPG result: bpm=%.1f quality=%.4f score=%.4f verdict=%s",
            bpm,
            quality,
            score,
            verdict,
        )

        return {
            "job_id": job_id,
            "modality": "video",
            "confidence": round(confidence, 4),
            "raw_score": round(score, 4),
            "score": round(score, 4),
            "verdict": verdict,
            "model": "rppg-chrom",
            "model_version": "rppg-chrom-v1.0",
            "estimated_bpm": round(bpm, 2),
            "latency_ms": elapsed_ms,
            "evidence": {
                "claim": claim,
                "flags": flags,
            },
        }

    finally:
        if os.path.exists(tmp.name):
            try:
                os.remove(tmp.name)
            except Exception as exc:
                logger.warning("Could not delete temporary file %s: %s", tmp.name, exc)
