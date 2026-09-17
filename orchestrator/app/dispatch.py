from __future__ import annotations
import asyncio
import os
from typing import List
import httpx
from models import DetectorResult, DetectorEvidence

from circuit_breaker import CircuitBreaker, CircuitBreakerOpenException

_DEFAULT_BASE = "http://{service}:8000"
INTERNAL_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")

_breakers = {}

def _get_breaker(detector: str) -> CircuitBreaker:
    if detector not in _breakers:
        _breakers[detector] = CircuitBreaker(name=detector, failure_threshold=3, recovery_timeout_sec=5.0)
    return _breakers[detector]


def _service_url(detector_name: str) -> str:
    env_key = f"DETECTOR_{detector_name.upper().replace('-', '_')}_URL"
    return os.environ.get(env_key, _DEFAULT_BASE.format(service=detector_name))


async def _call_one(client: httpx.AsyncClient, detector: str, job_id: str, modality: str, file_path: str) -> DetectorResult:
    url = f"{_service_url(detector)}/detect"
    body = {"job_id": job_id, "modality": modality, "payload": file_path}
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
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
    async with httpx.AsyncClient() as client:
        tasks = [_call_one(client, d, job_id, modality, file_path) for d in detectors]
        return await asyncio.gather(*tasks)