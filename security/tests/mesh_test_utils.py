"""
Shared harness for the orchestrator -> detector mTLS tests (Week 9 Task 6).

Starts a REAL uvicorn server with the exact TLS settings used by docker-compose.mtls.yml
(--ssl-ca-certs=<mesh_ca> --ssl-cert-reqs=2), so the tests exercise the same enforcement
path as production rather than a mock.
"""

import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI

from security.transport.generate_certs import generate_all_service_certs, generate_mesh_certs


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_pki(directory) -> str:
    """Main AEGIS CA certs (camera etc.) + the dedicated service-mesh CA certs."""
    d = str(directory)
    generate_all_service_certs(d)
    generate_mesh_certs(d)
    return d


def mesh_env(certs_dir: str, service_prefix: str) -> dict:
    """AEGIS_MESH_* environment for a client, e.g. service_prefix='mesh_orchestrator'."""
    return {
        "AEGIS_MESH_CA": str(Path(certs_dir) / "mesh_ca.crt"),
        "AEGIS_MESH_CERT": str(Path(certs_dir) / f"{service_prefix}.crt"),
        "AEGIS_MESH_KEY": str(Path(certs_dir) / f"{service_prefix}.key"),
        "AEGIS_MESH_DETECTORS": "video-classifier,aasist",
    }


def build_detector_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    @app.get("/metrics")
    def metrics():
        return {"ok": True}

    @app.post("/detect")
    def detect(body: dict):
        return {
            "job_id": body.get("job_id", "j"),
            "confidence": 0.12,
            "raw_score": -1.5,
            "latency_ms": 7,
            "model_version": "test-1.0",
            "evidence": {"claim": "authentic", "flags": ["test"]},
        }

    return app


class TLSDetectorServer:
    """uvicorn with client-certificate enforcement, run in a background thread."""

    def __init__(self, certs_dir: str, service_prefix: str = "mesh_detector_video_classifier"):
        self.port = free_port()
        cfg = uvicorn.Config(
            build_detector_app(),
            host="127.0.0.1",
            port=self.port,
            ssl_keyfile=str(Path(certs_dir) / f"{service_prefix}.key"),
            ssl_certfile=str(Path(certs_dir) / f"{service_prefix}.crt"),
            ssl_ca_certs=str(Path(certs_dir) / "mesh_ca.crt"),
            ssl_cert_reqs=ssl.CERT_REQUIRED,
            log_level="error",
        )
        self.server = uvicorn.Server(cfg)
        self.thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        return f"https://localhost:{self.port}"

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)
        if not self.server.started:
            raise RuntimeError("TLS detector test server failed to start")
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)

