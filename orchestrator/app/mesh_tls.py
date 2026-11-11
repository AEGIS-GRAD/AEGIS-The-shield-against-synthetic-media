"""
Service-mesh client TLS for orchestrator -> detector traffic (Month 3, Week 9 Task 6).

Relaxed (default, dev): none of the AEGIS_MESH_* variables are set, client_tls_kwargs()
returns {} and every call behaves exactly as before (plain HTTP, no certificates).

Strict (prod / CI): the compose override sets AEGIS_MESH_CA / AEGIS_MESH_CERT /
AEGIS_MESH_KEY and AEGIS_MESH_DETECTORS. Then:
  * every outgoing connection presents the orchestrator's client certificate and
    verifies the detector against the dedicated mesh CA;
  * detectors listed in AEGIS_MESH_DETECTORS MUST be reached over https:// - a plain
    http:// URL is refused (downgrade protection) rather than silently used;
  * missing/unreadable certificate files raise instead of falling back to plaintext
    (fail closed).
"""

from __future__ import annotations

import os
import ssl
from typing import Any, Dict, Mapping, Optional, Set


class MeshTLSConfigError(RuntimeError):
    """Strict mTLS was requested but is not correctly configured."""


def mesh_detectors(env: Optional[Mapping[str, str]] = None) -> Set[str]:
    env = os.environ if env is None else env
    raw = env.get("AEGIS_MESH_DETECTORS", "")
    return {d.strip() for d in raw.split(",") if d.strip()}


def mesh_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return bool(env.get("AEGIS_MESH_CA") and env.get("AEGIS_MESH_CERT") and env.get("AEGIS_MESH_KEY"))


def client_tls_kwargs(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """httpx.AsyncClient kwargs enabling mutual TLS, or {} when relaxed mode is active."""
    env = os.environ if env is None else env
    if not mesh_enabled(env):
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
    """False when `detector` must use mTLS but `url` is not https (downgrade attempt)."""
    if detector in mesh_detectors(env):
        return url.lower().startswith("https://")
    return True

