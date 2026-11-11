"""
Service-mesh TLS / mTLS helper for gateway-validator (mirrors orchestrator/app/mesh_tls.py).

Relaxed (default, dev): neither AEGIS_MESH_STRICT nor AEGIS_MESH_CA/CERT/KEY are set;
client_tls_kwargs() returns {} and every internal call behaves as plain HTTP for friction-free dev.

Strict (prod / CI overlay): docker-compose.mtls.yml sets AEGIS_MESH_STRICT=1 alongside
AEGIS_MESH_CA, AEGIS_MESH_CERT, AEGIS_MESH_KEY, and AEGIS_MESH_DETECTORS. Then:
  * outgoing calls to detector microservices present the gateway validator client cert
    and verify servers against `mesh_ca`;
  * plaintext http:// detector URLs are refused (downgrade protection);
  * missing certificate files fail closed.
"""

from __future__ import annotations

import os
import ssl
from typing import Any, Dict, Mapping, Optional, Set


class MeshTLSConfigError(RuntimeError):
    """Strict mTLS was requested but is not correctly configured."""


def _is_truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def mesh_detectors(env: Optional[Mapping[str, str]] = None) -> Set[str]:
    env = os.environ if env is None else env
    raw = env.get("AEGIS_MESH_DETECTORS", "")
    return {d.strip() for d in raw.split(",") if d.strip()}


def mesh_strict(env: Optional[Mapping[str, str]] = None) -> bool:
    """True when full-mesh strict mTLS enforcement is requested across all services."""
    env = os.environ if env is None else env
    detectors = mesh_detectors(env)
    return _is_truthy(env.get("AEGIS_MESH_STRICT")) or "*" in detectors or "all" in detectors


def mesh_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return bool(env.get("AEGIS_MESH_CA") and env.get("AEGIS_MESH_CERT") and env.get("AEGIS_MESH_KEY"))


def client_tls_kwargs(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """httpx Client/AsyncClient kwargs enabling mutual TLS, or {} when relaxed mode is active."""
    env = os.environ if env is None else env
    if not mesh_enabled(env):
        if mesh_strict(env):
            raise MeshTLSConfigError(
                "AEGIS_MESH_STRICT is enabled but AEGIS_MESH_CA/CERT/KEY are not configured"
            )
        return {}

    ca, cert, key = env["AEGIS_MESH_CA"], env["AEGIS_MESH_CERT"], env["AEGIS_MESH_KEY"]
    for label, path in (("CA", ca), ("client cert", cert), ("client key", key)):
        if not os.path.isfile(path):
            raise MeshTLSConfigError(f"AEGIS_MESH {label} file not found: {path}")

    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca)
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return {"verify": ctx}


def url_allowed(detector: str, url: str, env: Optional[Mapping[str, str]] = None) -> bool:
    """False when `detector` requires mTLS (or full strict mesh is enabled) and URL is not https."""
    env = os.environ if env is None else env
    if mesh_strict(env) or detector in mesh_detectors(env):
        return url.lower().startswith("https://")
    return True
