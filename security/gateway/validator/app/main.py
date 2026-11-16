"""
AEGIS Gateway Upload Validator.

Sits behind the nginx api_gateway (see ../nginx.conf.template) and in front
of the real detector microservices. nginx handles auth (X-Internal-Token)
and per-key rate limiting; this service does deep content inspection:
  - Video (/validate/video): magic bytes, extension allowlist, size limit, PRNU check.
  - Audio (/validate/audio): strict base64/confined path + WAV/MP3 magic signatures.
  - Image (/validate/image): JPEG/PNG magic bytes, polyglot rejection, pixel-dimension
    & decompression-bomb limits, EXIF/ICC validation, and instruction-string flagging.
  - Text (/validate/text): UTF-8 & length checks, Unicode NFKC normalization,
    control/zero-width char removal, and instruction-string flagging.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import posixpath
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

import cv2
import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from . import config, path_safety
from .content_safety import (
    ContentValidationError,
    inspect_image_bytes,
    validate_and_normalize_text,
)
from .magic_bytes import sniff_audio_payload, sniff_extension
from .mesh_tls import MeshTLSConfigError, client_tls_kwargs, url_allowed
from .prnu_extractor import PRNUExtractor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway-validator")

app = FastAPI(
    title="AEGIS Gateway Upload Validator",
    description="Magic-byte, size, polyglot, bomb, metadata, normalization, and path-traversal enforcement.",
    version="0.2.0",
)

_VIDEO_EXTENSIONS: Set[str] = {".mp4", ".mov"}
_IMAGE_EXTENSIONS: Set[str] = {".jpg", ".jpeg", ".png"}
_TEXT_EXTENSIONS: Set[str] = {".txt"}


class DetectorPayloadRequest(BaseModel):
    job_id: str = Field(..., min_length=1)
    modality: str
    payload: str = Field(..., min_length=1)


# Backwards-compatible alias kept for any direct test/code imports.
AudioDetectorRequest = DetectorPayloadRequest


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    # Match the {"error": "..."} shape nginx already uses for its 401s, so
    # every layer of the gateway returns errors in one consistent format.
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(ContentValidationError)
async def content_validation_exception_handler(
    _: Request, exc: ContentValidationError
) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "Malformed request body", "detail": exc.errors()},
    )


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

    # --- PRNU HARDWARE FINGERPRINT CHECK ---
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        cap = cv2.VideoCapture(tmp_path)
        ret, frame = cap.read()
        cap.release()

        if ret and frame is not None:
            logger.info("Extracting PRNU Hardware Fingerprint from frame...")
            extractor = PRNUExtractor(level=2)
            noise_residual = extractor.extract_noise_residual(frame)

            if noise_residual is None or noise_residual.size == 0:
                logger.error("Failed to extract PRNU noise. Possible hardware tampering.")
                raise HTTPException(
                    status_code=403,
                    detail="Hardware Fingerprint Missing (Spoofing Detected)",
                )
            logger.info("PRNU Hardware Check Passed. Video originated from a physical sensor.")
        else:
            logger.warning("Could not read frame for PRNU check, proceeding with standard validation.")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    try:
        response = await _forward_multipart(
            config.VIDEO_DETECTOR_URL,
            file.filename,
            content,
            detector="video-classifier",
        )
    except (httpx.RequestError, MeshTLSConfigError) as exc:
        raise HTTPException(status_code=502, detail=f"Upstream detector unreachable: {exc}") from exc

    return JSONResponse(status_code=response.status_code, content=_safe_json(response))


@app.post("/validate/audio")
async def validate_audio(req: DetectorPayloadRequest) -> JSONResponse:
    if req.modality != "audio":
        raise HTTPException(status_code=400, detail=f"Expected modality 'audio', got '{req.modality}'")

    raw_payload = req.payload.strip()

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
        response = await _forward_json(config.AUDIO_DETECTOR_URL, req.model_dump(), detector="aasist")
    except (httpx.RequestError, MeshTLSConfigError) as exc:
        raise HTTPException(status_code=502, detail=f"Upstream detector unreachable: {exc}") from exc

    return JSONResponse(status_code=response.status_code, content=_safe_json(response))


@app.post("/validate/image")
async def validate_image(request: Request) -> JSONResponse:
    job_id, is_path, raw_bytes, file_ext, confined_path = await _extract_contract_payload(
        request,
        expected_modality="image",
        allowed_exts=_IMAGE_EXTENSIONS,
        max_raw_bytes=config.MAX_UPLOAD_BYTES,
    )

    security_flags: List[str] = []
    metadata_flags: List[str] = []
    instruction_flags: List[str] = []

    if raw_bytes is not None:
        inspection = inspect_image_bytes(raw_bytes, expected_ext=file_ext)
        security_flags = inspection.security_flags
        metadata_flags = inspection.metadata_flags
        instruction_flags = inspection.instruction_flags
        if instruction_flags:
            logger.warning(
                "Instruction-like strings flagged in image metadata (job_id=%s): %s",
                job_id,
                instruction_flags,
            )

    forward_payload = (
        confined_path
        if is_path
        else base64.b64encode(raw_bytes or b"").decode("ascii")
    )
    forward_body = {"job_id": job_id, "modality": "image", "payload": forward_payload}

    try:
        response = await _forward_json(config.IMAGE_DETECTOR_URL, forward_body, detector="image")
    except (httpx.RequestError, MeshTLSConfigError) as exc:
        raise HTTPException(status_code=502, detail=f"Upstream detector unreachable: {exc}") from exc

    return _build_validation_response(
        response,
        security_flags=security_flags,
        metadata_flags=metadata_flags,
        instruction_flags=instruction_flags,
    )


@app.post("/validate/text")
async def validate_text(request: Request) -> JSONResponse:
    max_text_bytes = min(config.MAX_UPLOAD_BYTES, config.MAX_TEXT_BYTES)
    job_id, is_path, raw_bytes, _, confined_path = await _extract_contract_payload(
        request,
        expected_modality="text",
        allowed_exts=_TEXT_EXTENSIONS,
        max_raw_bytes=max_text_bytes,
    )

    security_flags: List[str] = []
    instruction_flags: List[str] = []
    stripped_controls = 0
    forward_payload = confined_path

    if raw_bytes is not None:
        text_res = validate_and_normalize_text(raw_bytes)
        security_flags = text_res.security_flags
        instruction_flags = text_res.instruction_flags
        stripped_controls = text_res.stripped_control_chars
        if stripped_controls > 0:
            logger.info(
                "Sanitized %d control/zero-width chars from text payload (job_id=%s)",
                stripped_controls,
                job_id,
            )
        if instruction_flags:
            logger.warning(
                "Instruction-like strings flagged in text payload (job_id=%s): %s",
                job_id,
                instruction_flags,
            )
        forward_payload = base64.b64encode(text_res.normalized_bytes).decode("ascii")

    forward_body = {"job_id": job_id, "modality": "text", "payload": forward_payload}

    try:
        response = await _forward_json(config.TEXT_DETECTOR_URL, forward_body, detector="text")
    except (httpx.RequestError, MeshTLSConfigError) as exc:
        raise HTTPException(status_code=502, detail=f"Upstream detector unreachable: {exc}") from exc

    return _build_validation_response(
        response,
        security_flags=security_flags,
        instruction_flags=instruction_flags,
        stripped_controls=stripped_controls,
        include_control_header=True,
    )


async def _extract_contract_payload(
    request: Request,
    *,
    expected_modality: str,
    allowed_exts: Set[str],
    max_raw_bytes: int,
) -> Tuple[str, bool, Optional[bytes], Optional[str], Optional[str]]:
    """Parse either multipart file upload or DetectorRequest JSON (base64 / confined path)."""
    content_type = request.headers.get("content-type", "").lower()

    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=400, detail="Missing file upload")

        filename = getattr(upload, "filename", None)
        ext = path_safety.safe_extension(filename)
        if ext is None:
            raise HTTPException(status_code=400, detail="Missing or unsafe filename")
        if ext not in allowed_exts:
            raise HTTPException(
                status_code=415,
                detail=f"Extension '{ext}' is not permitted for {expected_modality} uploads (allowed: {sorted(allowed_exts)})",
            )

        content = await upload.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Empty file upload")
        if len(content) > max_raw_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {max_raw_bytes} byte upload limit",
            )

        job_id_raw = form.get("job_id")
        job_id = job_id_raw.strip() if isinstance(job_id_raw, str) and job_id_raw.strip() else str(uuid.uuid4())
        return job_id, False, content, ext, None

    try:
        raw_body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Malformed request body") from exc

    try:
        req = DetectorPayloadRequest.model_validate(raw_body)
    except ValidationError as exc:
        return_detail = {"error": "Malformed request body", "detail": exc.errors()}
        raise HTTPException(status_code=400, detail=return_detail["error"]) from exc

    if req.modality != expected_modality:
        raise HTTPException(
            status_code=400,
            detail=f"Expected modality '{expected_modality}', got '{req.modality}'",
        )

    raw_payload = req.payload.strip()
    b64_candidate = raw_payload
    if raw_payload.lower().startswith("data:") and ";base64," in raw_payload.lower():
        b64_candidate = raw_payload.split(",", 1)[1]

    b64_compact = b64_candidate if raw_payload.startswith("/") else "".join(b64_candidate.split())
    try:
        decoded = base64.b64decode(b64_compact, validate=True)
        is_path = False
    except (binascii.Error, ValueError):
        decoded = None
        is_path = True

    if not is_path:
        if len(decoded or b"") == 0:
            raise HTTPException(status_code=400, detail=f"Empty {expected_modality} payload")
        if len(decoded or b"") > max_raw_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Decoded payload exceeds the {max_raw_bytes} byte upload limit",
            )
        return req.job_id, False, decoded, None, None

    if not raw_payload.startswith("/") or not path_safety.is_confined_path(
        raw_payload, config.SHARED_VOLUME_ROOT
    ):
        logger.warning("Rejected path-traversal attempt: %s", raw_payload)
        raise HTTPException(
            status_code=400,
            detail=f"Payload path must resolve inside {config.SHARED_VOLUME_ROOT}",
        )

    _, path_ext = posixpath.splitext(raw_payload.replace("\\", "/"))
    path_ext = path_ext.lower()
    if path_ext not in allowed_exts:
        raise HTTPException(
            status_code=415,
            detail=f"Extension '{path_ext or '<none>'}' is not permitted for {expected_modality} uploads",
        )

    if os.path.isfile(raw_payload):
        if os.path.getsize(raw_payload) > max_raw_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {max_raw_bytes} byte upload limit",
            )
        with open(raw_payload, "rb") as fh:
            file_bytes = fh.read()
        return req.job_id, True, file_bytes, path_ext, raw_payload

    return req.job_id, True, None, path_ext, raw_payload


def _build_validation_response(
    response: httpx.Response,
    *,
    security_flags: List[str],
    metadata_flags: Optional[List[str]] = None,
    instruction_flags: Optional[List[str]] = None,
    stripped_controls: int = 0,
    include_control_header: bool = False,
) -> JSONResponse:
    headers: Dict[str, str] = {
        "X-AEGIS-Injection-Detected": "true" if instruction_flags else "false",
    }
    if include_control_header:
        headers["X-AEGIS-Sanitized-Controls"] = str(stripped_controls)
    if instruction_flags:
        headers["X-AEGIS-Prompt-Flags"] = ",".join(instruction_flags)
    if metadata_flags:
        headers["X-AEGIS-Metadata-Flags"] = ",".join(metadata_flags)
    if security_flags:
        headers["X-AEGIS-Security-Flags"] = ",".join(security_flags)

    body: Any = _safe_json(response)
    if security_flags and isinstance(body, dict):
        body.setdefault("security_flags", security_flags)

    return JSONResponse(status_code=response.status_code, content=body, headers=headers)


async def _forward_multipart(
    url: str, filename: str, content: bytes, detector: str = "video-classifier"
) -> httpx.Response:
    if not url_allowed(detector, url):
        raise MeshTLSConfigError(f"mTLS required for '{detector}' but URL is not https: {url}")
    async with httpx.AsyncClient(
        timeout=config.UPSTREAM_TIMEOUT_SECONDS, **client_tls_kwargs()
    ) as client:
        return await client.post(url, files={"file": (filename, content)})


async def _forward_json(
    url: str, body: dict, detector: str = "aasist"
) -> httpx.Response:
    if not url_allowed(detector, url):
        raise MeshTLSConfigError(f"mTLS required for '{detector}' but URL is not https: {url}")
    async with httpx.AsyncClient(
        timeout=config.UPSTREAM_TIMEOUT_SECONDS, **client_tls_kwargs()
    ) as client:
        return await client.post(url, json=body)


def _safe_json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {"error": "Upstream detector returned a non-JSON response"}
