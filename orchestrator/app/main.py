import os
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Security
from fastapi.security.api_key import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN, HTTP_413_REQUEST_ENTITY_TOO_LARGE

from metadata import get_input_metadata
from rules import decide_detectors_to_call
from dispatch import call_all_detectors
from aggregate import aggregate_results
from db import init_db, log_decision
from models import OrchestrationResponse

API_KEY = os.environ.get("INTERNAL_API_KEY", "dev_default_key")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB limit

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header != API_KEY:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Could not validate credentials")
    return api_key_header

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="AEGIS Rule-Based Baseline Orchestrator", lifespan=lifespan)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/orchestrate", response_model=OrchestrationResponse)
async def orchestrate(
    file: UploadFile = File(...),
    api_key: str = Depends(get_api_key)
):
    # Enforce payload size limits (input validation / resource limits)
    file.file.seek(0, os.SEEK_END)
    file_size = file.file.tell()
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")
    file.file.seek(0)

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
            job_id=job_id,
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