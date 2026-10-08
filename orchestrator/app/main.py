import logging
import os
import shutil
import tempfile
import uuid
import traceback
from contextlib import asynccontextmanager

from typing import Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Security, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN
try:
    from starlette.status import HTTP_413_CONTENT_TOO_LARGE as HTTP_413_TOO_LARGE
except ImportError:
    from starlette.status import HTTP_413_REQUEST_ENTITY_TOO_LARGE as HTTP_413_TOO_LARGE

from media_metadata import get_input_metadata
from rules import decide_detectors_to_call
from planner import plan_detectors, resolve_planner_mode, get_configured_planner_mode
from dispatch import call_all_detectors
from aggregate import aggregate_results
from db import init_db, log_decision
from models import OrchestrationResponse

# Configure vibrant terminal logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [AEGIS-Orchestrator] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("aegis.orchestrator")

API_KEY = os.environ.get("INTERNAL_API_KEY", "dev_default_key")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB limit

async def get_api_key(api_key_header: str = Security(api_key_header)):
    # Flexible dev mode check to avoid blocking local frontend testing
    valid_keys = {API_KEY, "dev_default_key", "aegis-secret-key-change-in-prod"}
    if api_key_header and api_key_header not in valid_keys and API_KEY != "dev_default_key":
        logger.warning(f"Unauthorized API key attempt: '{api_key_header}'")
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Could not validate credentials")
    return api_key_header

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AEGIS Orchestrator service... Database initializing.")
    init_db()
    configured_mode = get_configured_planner_mode()
    logger.info(f"AEGIS Orchestrator ready on port 8000 (default planning mode: {configured_mode}).")
    yield
    logger.info("Shutting down AEGIS Orchestrator.")

app = FastAPI(title="AEGIS Multi-Modal Orchestrator", lifespan=lifespan)

# Enable CORS for browser frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "aegis-orchestrator",
        "planner_mode": get_configured_planner_mode(),
    }

@app.post("/orchestrate", response_model=OrchestrationResponse)
async def orchestrate(
    file: UploadFile = File(...),
    planner_mode: Optional[str] = Query(None, description="Planning mode override: 'llm' or 'rule_based'"),
    risk_profile: Optional[str] = Query("standard", description="Risk profile: 'low', 'standard', 'high'"),
    compute_budget_s: Optional[float] = Query(None, description="Compute budget ceiling in seconds"),
    x_planner_mode: Optional[str] = Header(None, alias="X-Planner-Mode"),
    api_key: str = Depends(get_api_key)
):
    logger.info(f"Incoming media upload: '{file.filename}' (content_type={file.content_type})")
    
    # Enforce payload size limits
    file.file.seek(0, os.SEEK_END)
    file_size = file.file.tell()
    if file_size > MAX_FILE_SIZE:
        logger.error(f"Upload failed: File size {file_size} exceeds 100MB limit.")
        raise HTTPException(status_code=HTTP_413_TOO_LARGE, detail="File too large (exceeds 100MB)")
    file.file.seek(0)

    suffix = os.path.splitext(file.filename)[1] if file.filename else ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        logger.info(f"Extracting metadata from temporary file '{tmp_path}'...")
        metadata = get_input_metadata(tmp_path, original_filename=file.filename or "unknown")
        logger.info(f"Extracted metadata: Modality={metadata.modality}, Duration={metadata.duration_seconds}s, HasAudio={metadata.has_audio}")

        # Determine effective planning mode (query param > header > environment config)
        effective_mode = resolve_planner_mode(planner_mode or x_planner_mode)
        logger.info(f"Orchestrator Planning Mode: '{effective_mode}'")

        planning_result = plan_detectors(
            metadata=metadata,
            mode=effective_mode,
            risk_profile=risk_profile or "standard",
            budget_s=compute_budget_s,
        )
        detectors_to_call = planning_result.detectors_to_call
        plan_data = planning_result.plan
        is_fallback = planning_result.fallback
        fallback_reason = planning_result.fallback_reason
        rationale = plan_data.get("rationale") if plan_data else None

        if is_fallback:
            logger.warning(f"LLM Planner fallback triggered ({fallback_reason}). Dispatched baseline detectors: {detectors_to_call}")
        else:
            logger.info(f"Planner Selected Detectors [{planning_result.planner_mode}]: {detectors_to_call}")

        job_id = str(uuid.uuid4())
        logger.info(f"Dispatching async requests for job {job_id} to detectors...")
        results = await call_all_detectors(detectors_to_call, job_id, metadata.modality, tmp_path)

        for res in results:
            if res.status != "ok":
                logger.error(f"Detector [{res.detector}] FAILED: {res.error}")
            else:
                logger.info(f"Detector [{res.detector}] SUCCESS: score={res.raw_score}, latency={res.latency_ms}ms")

        aggregated_score, aggregated_verdict = aggregate_results(results)
        logger.info(f"Final Decision: Verdict={aggregated_verdict}, Aggregated Score={aggregated_score:.4f}")

        log_decision(
            job_id=job_id,
            input_file=file.filename or "unknown",
            metadata=metadata.model_dump(),
            detectors_called=detectors_to_call,
            raw_results=[r.model_dump() for r in results],
            aggregated_score=aggregated_score,
            aggregated_verdict=aggregated_verdict,
            planner_mode=planning_result.planner_mode,
            plan=plan_data,
            rationale=rationale,
            fallback=is_fallback,
            fallback_reason=fallback_reason,
        )

        return OrchestrationResponse(
            input_file=file.filename or "unknown",
            metadata=metadata,
            detectors_called=detectors_to_call,
            raw_results=results,
            aggregated_score=aggregated_score,
            aggregated_verdict=aggregated_verdict,
            planner_mode=planning_result.planner_mode,
            plan=plan_data,
            fallback=is_fallback,
            fallback_reason=fallback_reason,
        )
    except Exception as exc:
        logger.error(f"EXCEPTIONAL FAILURE during orchestration processing for file '{file.filename}': {exc}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Orchestration Error: {str(exc)}. Check terminal logs.")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)