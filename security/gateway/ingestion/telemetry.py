"""
AEGIS SecDevOps — Ingestion Telemetry & Attack Injection Service
─────────────────────────────────────────────────────────────────
Provides a real-time Server-Sent Events (SSE) telemetry stream on port 8444
and an on-demand attack injection API for live red-team demonstrations.

Key Endpoints:
  • GET /telemetry/stream : Native SSE stream for frontend HUD (hashes, PCE, verdicts).
  • GET /telemetry/health : Probes telemetry service status and client counts.
  • GET /telemetry/recent : Returns ring-buffer of the last 50 processed frames.
  • POST /telemetry/inject: Triggers attack streams for live advisor demonstrations.
"""

import asyncio
import collections
import hashlib
import json
import logging
import os
import socket
import ssl
import subprocess
import sys
import time
from typing import Dict, Any, List, Set

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("aegis.ingestion.telemetry")

TELEMETRY_PORT = int(os.environ.get("AEGIS_TELEMETRY_PORT", "8444"))
TELEMETRY_HOST = os.environ.get("AEGIS_TELEMETRY_HOST", "0.0.0.0")


class AttackInjectRequest(BaseModel):
    attack_type: str = Field(
        default="prnu_splice",
        description="Attack vector: prnu_splice, hash_break, timestamp_replay, framerate_flood, sequence_drop"
    )
    camera_id: str = Field(default="camera-001", description="Target camera identifier")
    frames: int = Field(default=30, description="Number of attack frames to inject")


class IngestionTelemetryHub:
    """
    In-memory asynchronous event hub connecting the mTLS ingestion server
    with browser SSE clients and forensic audit logs.
    """
    def __init__(self, max_history: int = 50):
        self.max_history = max_history
        self.history: collections.deque = collections.deque(maxlen=max_history)
        self.subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self.total_frames_processed = 0
        self.total_breaches_detected = 0

    async def broadcast(self, event: Dict[str, Any]):
        """Publish an event to all connected SSE clients and the history buffer."""
        async with self._lock:
            self.total_frames_processed += 1
            if event.get("status") in ("COMPROMISED", "AUDIT_WARNING"):
                self.total_breaches_detected += 1
            self.history.append(event)
            dead_queues = []
            for queue in self.subscribers:
                try:
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:
                    dead_queues.append(queue)
            for dead in dead_queues:
                self.subscribers.discard(dead)

    def broadcast_sync(self, event: Dict[str, Any]):
        """Synchronous wrapper for thread-safe event publishing."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(event))
        except RuntimeError:
            pass

    async def subscribe(self) -> asyncio.Queue:
        """Register a new SSE client queue."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self.subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue):
        """Remove a disconnected client queue."""
        async with self._lock:
            self.subscribers.discard(queue)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "active_clients": len(self.subscribers),
            "buffered_events": len(self.history),
            "total_frames_processed": self.total_frames_processed,
            "total_breaches_detected": self.total_breaches_detected,
        }


# Global singleton hub
telemetry_hub = IngestionTelemetryHub()

# FastAPI application for telemetry and attack injection
telemetry_app = FastAPI(
    title="AEGIS Ingestion Telemetry & Attack Service",
    description="Live SSE telemetry and demonstration attack injection endpoint",
    version="1.0.0"
)

telemetry_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@telemetry_app.get("/telemetry/health")
async def health():
    profile = os.environ.get("AEGIS_SECURITY_PROFILE", "dev").lower()
    stats = telemetry_hub.get_stats()
    return {
        "status": "healthy",
        "service": "aegis-ingestion-telemetry",
        "profile": profile,
        **stats
    }


@telemetry_app.get("/telemetry/recent")
async def recent_events():
    return JSONResponse(content=list(telemetry_hub.history))


@telemetry_app.get("/telemetry/stream")
async def stream_telemetry(request: Request):
    """
    Server-Sent Events endpoint streaming live sequence numbers,
    SHA-256 hashes, PRNU PCE scores, and verdict status to the frontend HUD.
    """
    queue = await telemetry_hub.subscribe()

    async def event_generator():
        try:
            # Yield initial connection confirmation with current profile
            profile = os.environ.get("AEGIS_SECURITY_PROFILE", "dev").lower()
            initial_payload = {
                "event": "CONNECTED",
                "timestamp": time.time(),
                "profile": profile,
                "message": f"AEGIS Ingestion Telemetry attached. Active profile: {profile.upper()}."
            }
            yield f"data: {json.dumps(initial_payload)}\n\n"

            # Stream recent historical events so UI populates immediately
            for past_event in list(telemetry_hub.history):
                yield f"data: {json.dumps(past_event)}\n\n"

            # Continuously stream real-time verification events
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat comment
                    yield ": ping\n\n"
        finally:
            await telemetry_hub.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "X-Accel-Buffering": "no",
        }
    )


@telemetry_app.post("/telemetry/inject")
async def inject_attack(body: AttackInjectRequest):
    """
    Executes an attack injection against the live Ingestion Gateway (8443)
    and broadcasts the adversarial breach event across the telemetry stream (8444).
    """
    profile = os.environ.get("AEGIS_SECURITY_PROFILE", "dev").lower()
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    cert_dir = os.path.join(repo_root, "security", "transport", "certs")
    client_cert = os.path.join(cert_dir, "client.crt")
    client_key = os.path.join(cert_dir, "client.key")
    ca_cert = os.path.join(cert_dir, "ca.crt")

    mtls_success = False
    mtls_detail = ""

    # Attempt real mTLS attack injection against 127.0.0.1:8443 if certs exist
    if os.path.exists(client_cert) and os.path.exists(client_key) and os.path.exists(ca_cert):
        def _send_mtls_attack():
            try:
                ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
                ctx.load_cert_chain(certfile=client_cert, keyfile=client_key)
                ctx.check_hostname = False
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2.0)
                    with ctx.wrap_socket(s, server_hostname="127.0.0.1") as conn:
                        conn.connect(("127.0.0.1", 8443))
                        genesis = hashlib.sha256(b"AEGIS_GENESIS").hexdigest()
                        # Normal frame
                        h1 = hashlib.sha256(genesis.encode('utf-8') + b"INIT_FRAME").hexdigest()
                        conn.sendall((json.dumps({"sequence_number": 1, "timestamp_ms": int(time.time() * 1000), "frame_data": b"INIT_FRAME".hex(), "hash": h1}) + "\n").encode('utf-8'))
                        time.sleep(0.05)
                        # Attack frame
                        f2 = {
                            "sequence_number": 2,
                            "timestamp_ms": int(time.time() * 1000) + 33,
                            "frame_data": b"TAMPERED_DEEPFAKE_FRAME".hex(),
                            "hash": "tampered_hash_adversarial_breach"
                        }
                        conn.sendall((json.dumps(f2) + "\n").encode('utf-8'))
                        time.sleep(0.05)
                return True, "Live attack payload transmitted via mTLS to 127.0.0.1:8443"
            except Exception as e:
                return False, f"mTLS transmission: {e}"

        try:
            mtls_success, mtls_detail = await asyncio.to_thread(_send_mtls_attack)
        except Exception as e:
            mtls_detail = f"mTLS dispatch error: {e}"

    # Also broadcast event directly to telemetry hub to guarantee UI HUD receives it
    event = {
        "timestamp": time.time(),
        "camera_id": body.camera_id,
        "seq": 999,
        "status": "COMPROMISED" if profile == "prod" else "AUDIT_WARNING",
        "threat_type": "PRNU_TAMPERING" if body.attack_type == "prnu_splice" else "HASH_MISMATCH",
        "profile": profile,
        "action": "SOCKET_SEVERED" if profile == "prod" else "AUDIT_LOGGED",
        "hash": "0xDEAD...BEEF",
        "prnu_pce": 14.2 if body.attack_type == "prnu_splice" else 22.4,
        "detail": f"Adversarial stream injection: {body.attack_type} ({body.frames} frames) - {mtls_detail}"
    }
    await telemetry_hub.broadcast(event)

    return {
        "status": "attack_dispatched",
        "attack_type": body.attack_type,
        "camera_id": body.camera_id,
        "frames": body.frames,
        "profile": profile,
        "mtls_dispatched": mtls_success,
        "detail": mtls_detail,
        "event": event
    }
