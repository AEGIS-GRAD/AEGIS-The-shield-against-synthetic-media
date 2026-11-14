from __future__ import annotations
import asyncio
import os
from typing import List
import httpx
from models import DetectorResult, DetectorEvidence

from circuit_breaker import CircuitBreaker, CircuitBreakerOpenException
try:
    from mesh_tls import client_tls_kwargs, mesh_enabled, mesh_strict, url_allowed
except ImportError:
    from orchestrator.app.mesh_tls import client_tls_kwargs, mesh_enabled, mesh_strict, url_allowed

INTERNAL_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")


def _resolve_internal_token() -> str:
    """Resolves internal shared token in relaxed dev mode (prefers INTERNAL_API_KEY)."""
    return (
        os.environ.get("INTERNAL_API_KEY")
        or os.environ.get("INTERNAL_API_TOKEN")
        or INTERNAL_TOKEN
    )

_breakers = {}

# Per-detector circuit breaker thresholds
DETECTOR_CIRCUIT_BREAKER_CONFIGS: dict[str, dict] = {
    "video-classifier": {
        "failure_threshold": 3,
        "recovery_timeout_sec": 5.0,
        "latency_threshold_sec": 15.0,
    },
    "rppg": {
        "failure_threshold": 3,
        "recovery_timeout_sec": 5.0,
        "latency_threshold_sec": 15.0,
    },
    "aasist": {
        "failure_threshold": 3,
        "recovery_timeout_sec": 5.0,
        "latency_threshold_sec": 2.0,
    },
    "syncnet": {
        "failure_threshold": 3,
        "recovery_timeout_sec": 5.0,
        "latency_threshold_sec": 20.0,
    },
    "fusion": {
        "failure_threshold": 5,
        "recovery_timeout_sec": 3.0,
        "latency_threshold_sec": 1.0,
    },
    "detector_image": {
        "failure_threshold": 3,
        "recovery_timeout_sec": 10.0,
        "latency_threshold_sec": 5.0,
    },
    "detector_text": {
        "failure_threshold": 3,
        "recovery_timeout_sec": 5.0,
        "latency_threshold_sec": 2.0,
    },
}


def _get_breaker(detector: str) -> CircuitBreaker:
    if detector not in _breakers:
        cfg = DETECTOR_CIRCUIT_BREAKER_CONFIGS.get(
            detector,
            {"failure_threshold": 3, "recovery_timeout_sec": 5.0, "latency_threshold_sec": 5.0},
        )
        _breakers[detector] = CircuitBreaker(name=detector, **cfg)
    return _breakers[detector]


def _service_url(detector_name: str) -> str:
    normalized = detector_name.replace("-", "_")
    env_key = f"DETECTOR_{normalized.upper()}_URL"
    alias_key = f"DETECTOR_{normalized.removeprefix('detector_').upper()}_URL"
    default_service = normalized if normalized.startswith("detector_") else f"detector_{normalized}"
    scheme = "https" if (mesh_enabled() or mesh_strict()) else "http"
    return (
        os.environ.get(env_key)
        or (os.environ.get(alias_key) if alias_key != env_key else None)
        or f"{scheme}://{default_service}:8000"
    )


async def _call_one(client: httpx.AsyncClient, detector: str, job_id: str, modality: str, file_path: str) -> DetectorResult:
    url = f"{_service_url(detector)}/detect"
    if not url_allowed(detector, url):
        # Strict mesh mode: refuse to downgrade an mTLS detector to plaintext HTTP.
        return DetectorResult(
            detector=detector, status="failed", job_id=job_id,
            error=f"mTLS required for '{detector}' but URL is not https: {url}",
        )
    body = {"job_id": job_id, "modality": modality, "payload": file_path}
    # In mTLS mesh mode, authentication is cryptographic client cert; shared X-Internal-Token is removed.
    token = "" if (mesh_enabled() or mesh_strict()) else _resolve_internal_token()
    headers = {"X-Internal-Token": token} if token else {}
    breaker = _get_breaker(detector)

    try:
        resp = await breaker.call_async(client.post, url, json=body, headers=headers, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()

        required = ["job_id", "confidence", "raw_score", "latency_ms", "model_version", "evidence"]
        missing = [f for f in required if f not in data]
        if missing:
            return DetectorResult(
                detector=detector, status="failed", job_id=job_id,
                error=f"Response missing required fields: {missing}"
            )

        evidence_data = data["evidence"]
        return DetectorResult(
            detector=detector,
            status="ok",
            job_id=data["job_id"],
            confidence=data["confidence"],
            raw_score=data["raw_score"],
            latency_ms=data["latency_ms"],
            ram_usage_mb=data.get("ram_usage_mb"),
            vram_usage_mb=data.get("vram_usage_mb"),
            model_version=data["model_version"],
            evidence=DetectorEvidence(claim=evidence_data["claim"], flags=evidence_data.get("flags", [])),
        )
    except CircuitBreakerOpenException as exc:
        return DetectorResult(detector=detector, status="failed", job_id=job_id, error=f"Circuit OPEN: {str(exc)}")
    except Exception as exc:
        return DetectorResult(detector=detector, status="failed", job_id=job_id, error=str(exc))


async def call_all_detectors(detectors: List[str], job_id: str, modality: str, file_path: str) -> List[DetectorResult]:
    # {} in relaxed/dev mode (unchanged behaviour); mutual-TLS context in strict mode.
    async with httpx.AsyncClient(**client_tls_kwargs()) as client:
        tasks = [_call_one(client, d, job_id, modality, file_path) for d in detectors]
        return await asyncio.gather(*tasks)