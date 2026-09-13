"""
AEGIS Gateway Upload Validator.

Sits behind the nginx api_gateway (see ../nginx.conf.template) and in front
of the real detector microservices. nginx handles auth (X-Internal-Token)
and per-key rate limiting; this service does the deep content inspection
that plain nginx config can't: magic-byte verification, extension
allowlisting, payload-size enforcement, and path-traversal confinement -
per shared/json-api-contracts-schema/SCHEMA.md Section 1.

Two upstream detectors, two different request shapes:
  - video-classifier expects a raw multipart file upload.
  - aasist expects a JSON body (job_id/modality/payload) per SCHEMA.md.
Each gets its own validation path below, then a transparent proxy forward.
"""

import base64
import binascii
import logging

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import config, path_safety
from .magic_bytes import sniff_audio_payload, sniff_extension

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway-validator")

app = FastAPI(
    title="AEGIS Gateway Upload Validator",
    description="Magic-byte, size, and path-traversal enforcement for the ingestion gateway.",
    version="0.1.0",
)

_VIDEO_EXTENSIONS = {".mp4", ".mov"}


class AudioDetectorRequest(BaseModel):
    job_id: str = Field(..., min_length=1)
    modality: str
    payload: str = Field(..., min_length=1)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    # Match the {"error": "..."} shape nginx already uses for its 401s, so
    # every layer of the gateway returns errors in one consistent format.
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "Malformed request body", "detail": exc.errors()})


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "service": "gateway-validator"}


@app.post("/validate/video")
async def validate_video(file: UploadFile = File(...)) -> JSONResponse:
    ext = path_safety.safe_extension(file.filename)
    if ext is None:
        raise HTTPException(status_code=400, detail="Missing or unsafe filename")
    if ext not in _VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Extension '{ext}' is not permitted for video uploads (allowed: {sorted(_VIDEO_EXTENSIONS)})",
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file upload")
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {config.MAX_UPLOAD_BYTES} byte upload limit",
        )

    result = sniff_extension(ext, content)
    if not result.valid:
        logger.warning("Rejected spoofed video upload: %s", result.reason)
        raise HTTPException(status_code=415, detail=result.reason)

    try:
        response = await _forward_multipart(config.VIDEO_DETECTOR_URL, file.filename, content)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream detector unreachable: {exc}") from exc

    return JSONResponse(status_code=response.status_code, content=_safe_json(response))


@app.post("/validate/audio")
async def validate_audio(req: AudioDetectorRequest) -> JSONResponse:
    if req.modality != "audio":
        raise HTTPException(status_code=400, detail=f"Expected modality 'audio', got '{req.modality}'")

    raw_payload = req.payload.strip()

    # base64's alphabet includes '/', so a payload can legitimately start
    # with it - a leading slash alone doesn't mean "this is a file path".
    # Try strict base64 decoding first; only treat the payload as a path
    # (and apply path-confinement checks) once that fails. Real filesystem
    # paths contain '.', '_', or unpadded lengths that strict base64 rejects.
    try:
        decoded = base64.b64decode(raw_payload, validate=True)
        is_path = False
    except (binascii.Error, ValueError):
        decoded = None
        is_path = True

    if is_path:
        if not raw_payload.startswith("/") or not path_safety.is_confined_path(
            raw_payload, config.SHARED_VOLUME_ROOT
        ):
            logger.warning("Rejected path-traversal attempt: %s", raw_payload)
            raise HTTPException(
                status_code=400,
                detail=f"Payload path must resolve inside {config.SHARED_VOLUME_ROOT}",
            )
    else:
        if len(decoded) == 0:
            raise HTTPException(status_code=400, detail="Empty audio payload")
        if len(decoded) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Decoded payload exceeds the {config.MAX_UPLOAD_BYTES} byte upload limit",
            )

        result = sniff_audio_payload(decoded)
        if not result.valid:
            logger.warning("Rejected spoofed audio payload: %s", result.reason)
            raise HTTPException(status_code=415, detail=result.reason)

    try:
        response = await _forward_json(config.AUDIO_DETECTOR_URL, req.model_dump())
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream detector unreachable: {exc}") from exc

    return JSONResponse(status_code=response.status_code, content=_safe_json(response))


async def _forward_multipart(url: str, filename: str, content: bytes) -> httpx.Response:
    async with httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_SECONDS) as client:
        return await client.post(url, files={"file": (filename, content)})


async def _forward_json(url: str, body: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_SECONDS) as client:
        return await client.post(url, json=body)


def _safe_json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {"error": "Upstream detector returned a non-JSON response"}
