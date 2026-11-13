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
from schemas import TextAnalysisRequest, TextAnalysisResponse, StylometryMetrics
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
