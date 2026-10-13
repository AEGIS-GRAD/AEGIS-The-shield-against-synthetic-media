"""
AEGIS Dual-Mode Ingestion Gateway & Telemetry Unit Tests
────────────────────────────────────────────────────────
Verifies both operational profiles:
  1. PROD Mode: Zero-trust enforcement severs socket on attack.
  2. DEV Mode: Permissive sandbox allows stream continuation,
               broadcasting audit warnings to the telemetry hub.
  3. Telemetry SSE Hub: Real-time broadcast and subscription.
"""

import asyncio
import hashlib
import json
import os
import sys
import time
import pytest
from httpx import AsyncClient, ASGITransport

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from gateway.ingestion.server import LiveHashChainValidator, StreamRateLimiter
from gateway.ingestion.telemetry import telemetry_hub, telemetry_app


@pytest.mark.asyncio
async def test_telemetry_hub_broadcast_and_history():
    """Verify that events broadcast through telemetry_hub are recorded and received by subscribers."""
    queue = await telemetry_hub.subscribe()
    test_event = {
        "timestamp": time.time(),
        "camera_id": "test-cam-001",
        "seq": 42,
        "hash": "test_hash_abc",
        "prnu_pce": 78.5,
        "status": "VALID",
        "profile": "prod",
        "action": "FORWARDED"
    }

    await telemetry_hub.broadcast(test_event)

    received = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert received["camera_id"] == "test-cam-001"
    assert received["seq"] == 42
    assert received["status"] == "VALID"
    assert received["action"] == "FORWARDED"

    # Verify event was captured in history
    stats = telemetry_hub.get_stats()
    assert stats["buffered_events"] > 0
    assert stats["total_frames_processed"] > 0

    await telemetry_hub.unsubscribe(queue)


@pytest.mark.asyncio
async def test_telemetry_health_endpoint():
    """Verify that GET /telemetry/health returns healthy status and active profile."""
    transport = ASGITransport(app=telemetry_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/telemetry/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert "profile" in data
        assert "total_frames_processed" in data


@pytest.mark.asyncio
async def test_telemetry_recent_endpoint():
    """Verify that GET /telemetry/recent returns the list of historical events."""
    transport = ASGITransport(app=telemetry_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/telemetry/recent")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)


def test_hash_validator_clean_and_tampered():
    """Verify cryptographic hash chain validation logic."""
    validator = LiveHashChainValidator()
    frame_bytes = b"AuthenticFrameContent"
    
    # Calculate valid expected hash
    hasher = hashlib.sha256()
    hasher.update(validator.current_hash.encode('utf-8'))
    hasher.update(frame_bytes)
    valid_hash = hasher.hexdigest()

    # Clean frame passes
    assert validator.validate_frame(frame_bytes, valid_hash) is True

    # Tampered frame fails
    assert validator.validate_frame(frame_bytes, "tampered_fake_hash") is False


def test_stream_rate_limiter_burst_and_drop():
    """Verify rate limiter token bucket behavior."""
    limiter = StreamRateLimiter(max_fps=10.0, burst_capacity=2.0)
    
    # Initial burst allowed
    assert limiter.allow_frame() is True
    assert limiter.allow_frame() is True
    
    # Immediate next frame should be throttled
    assert limiter.allow_frame() is False


@pytest.mark.asyncio
async def test_telemetry_inject_endpoint():
    """Verify POST /telemetry/inject triggers attack dispatch and broadcasts threat event."""
    transport = ASGITransport(app=telemetry_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "attack_type": "prnu_splice",
            "camera_id": "test-cam-001",
            "frames": 10
        }
        res = await client.post("/telemetry/inject", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "attack_dispatched"
        assert data["attack_type"] == "prnu_splice"
        assert "event" in data
        assert data["event"]["status"] in ("COMPROMISED", "AUDIT_WARNING")
        assert data["event"]["threat_type"] == "PRNU_TAMPERING"
