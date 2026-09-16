import os
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile

from metadata import get_input_metadata
from rules import decide_detectors_to_call
from dispatch import call_all_detectors
from aggregate import aggregate_results
from db import init_db, log_decision
from models import OrchestrationResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AEGIS Rule-Based Baseline Orchestrator", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/orchestrate", response_model=OrchestrationResponse)
async def orchestrate(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename)[1] if file.filename else ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        metadata = get_input_metadata(tmp_path, original_filename=file.filename or "unknown")
        detectors_to_call = decide_detectors_to_call(metadata)

        job_id = str(uuid.uuid4())
        results = await call_all_detectors(detectors_to_call, job_id, metadata.modality, tmp_path)
        aggregated_score, aggregated_verdict = aggregate_results(results)

        log_decision(
            input_file=file.filename or "unknown",
            metadata=metadata.model_dump(),       # Pydantic v2: .model_dump()
            detectors_called=detectors_to_call,
            raw_results=[r.model_dump() for r in results],  # Pydantic v2: .model_dump()
            aggregated_score=aggregated_score,
            aggregated_verdict=aggregated_verdict,
        )

        return OrchestrationResponse(
            input_file=file.filename or "unknown",
            metadata=metadata,
            detectors_called=detectors_to_call,
            raw_results=results,
            aggregated_score=aggregated_score,
            aggregated_verdict=aggregated_verdict,
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)