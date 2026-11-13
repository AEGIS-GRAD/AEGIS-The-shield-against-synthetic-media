"""
FastAPI microservice for AEGIS Text Detector.
Serves:
- POST /analyze: analyzes text using Desklib DeBERTa and extracts stylometry explainability features.
- GET /health: healthcheck endpoint.
"""
import time
import os
import torch
from fastapi import FastAPI, HTTPException
from schemas import (
    TextAnalysisRequest,
    TextAnalysisResponse,
    StylometryMetrics,
    DetectRequest,
    DetectResponse,
    DetectEvidence,
)
from desklib_model import load_desklib, predict_text
from stylometry import extract_stylometry_features

app = FastAPI(
    title="AEGIS Text Forensic Detector",
    description="Fine-tuned Desklib AI-text detection paired with stylometry explainability",
    version="1.0.0"
)

# Global model state
MODEL = None
TOKENIZER = None
DEVICE = None

@app.on_event("startup")
def startup_event():
    global MODEL, TOKENIZER, DEVICE
    model_path = os.path.join(os.path.dirname(__file__), "models", "desklib-base")
    print(f"[*] Starting Text Detector service from {model_path}...")
    MODEL, TOKENIZER, DEVICE = load_desklib(model_path)
    print(f"[+] Text Detector model loaded on {DEVICE}")

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "detector": "text-detector",
        "device": str(DEVICE) if DEVICE else "uninitialized"
    }

@app.post("/analyze", response_model=TextAnalysisResponse)
def analyze_text(request: TextAnalysisRequest):
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Text field cannot be empty.")

    t0 = time.time()
    # 1. Neural classification
    pred = predict_text(request.text, MODEL, TOKENIZER, DEVICE)

    # 2. Stylometry explainability
    stylometry_res = None
    if request.include_stylometry:
        feat = extract_stylometry_features(request.text)
        stylometry_res = StylometryMetrics(
            vocabulary_diversity=feat["vocabulary_diversity"],
            ngram_repetition=feat["ngram_repetition"],
            sentence_variation=feat["sentence_variation"],
            synthetic_indication_score=feat["synthetic_indication_score"],
            stylometry_verdict=feat["stylometry_verdict"],
            summary=feat["summary"]
        )

    latency_ms = round((time.time() - t0) * 1000, 2)

    return TextAnalysisResponse(
        detector="desklib_ai_text_detector",
        model_version="v1.01",
        request_id=request.request_id,
        ai_score=pred["ai_score"],
        human_score=pred["human_score"],
        prediction=pred["prediction"],
        confidence=pred["confidence"],
        stylometry=stylometry_res,
        execution_time_ms=latency_ms
    )


@app.post("/detect", response_model=DetectResponse)
def detect(request: DetectRequest):
    t0 = time.time()
    text_content = ""
    if os.path.isfile(request.payload):
        try:
            with open(request.payload, "r", encoding="utf-8", errors="replace") as f:
                text_content = f.read(50_000)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read payload file: {e}")
    else:
        text_content = request.payload

    if not text_content.strip():
        return DetectResponse(
            status="ok",
            job_id=request.job_id,
            confidence=0.5,
            raw_score=0.5,
            latency_ms=0,
            model_version="desklib-deberta-v1.01",
            evidence=DetectEvidence(
                claim="Empty text provided",
                flags=["empty_text"]
            )
        )

    ai_score = 0.5
    confidence = 0.5
    prediction = "uncertain"
    if MODEL is not None and TOKENIZER is not None:
        pred = predict_text(text_content, MODEL, TOKENIZER, DEVICE)
        ai_score = pred["ai_score"]
        confidence = pred["confidence"]
        prediction = pred["prediction"]

    feat = extract_stylometry_features(text_content)
    flags = []
    if feat.get("stylometry_verdict") == "synthetic":
        flags.append("stylometry_synthetic")
    vocab = feat.get("vocabulary_diversity", {})
    if vocab.get("type_token_ratio", 1.0) < 0.4:
        flags.append("low_vocabulary_diversity")
    repetition = feat.get("ngram_repetition", {})
    if repetition.get("repetition_ratio_2gram", 0.0) > 0.25:
        flags.append("high_ngram_repetition")

    latency_ms = int(round((time.time() - t0) * 1000))

    return DetectResponse(
        status="ok",
        job_id=request.job_id,
        confidence=confidence,
        raw_score=ai_score,
        latency_ms=latency_ms,
        model_version="desklib-deberta-v1.01",
        evidence=DetectEvidence(
            claim=f"Text classified as {prediction} with synthetic score {ai_score:.3f}. {feat.get('summary', '')}",
            flags=flags
        )
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
