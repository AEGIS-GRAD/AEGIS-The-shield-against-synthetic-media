"""
Service-mesh TLS / mTLS helper for AEGIS orchestrator (Week 9 Task 6 -> Week 10 Task 1).

Relaxed (default, dev): neither AEGIS_MESH_STRICT nor AEGIS_MESH_CA/CERT/KEY are set;
client_tls_kwargs() returns {} and every internal call behaves as plain HTTP for friction-free dev.

Strict (prod / CI overlay): docker-compose.mtls.yml sets AEGIS_MESH_STRICT=1 alongside
AEGIS_MESH_CA, AEGIS_MESH_CERT, AEGIS_MESH_KEY, and AEGIS_MESH_DETECTORS. Then:
  * every internal connection (all detectors, judge service, telemetry, internal LLM bridge)
    presents the service's mesh client certificate and verifies peers against `mesh_ca`;
  * any plaintext http:// internal or LLM/Judge URL is refused (downgrade protection);
  * missing or unreadable certificate files fail closed by raising MeshTLSConfigError;
  * shared INTERNAL_API_KEY plain-HTTP headers are suppressed in strict mTLS mode.
"""

from __future__ import annotations

import os
import ssl
from typing import Any, Dict, Mapping, Optional, Set
from urllib.parse import urlparse


class MeshTLSConfigError(RuntimeError):
    """Strict mTLS was requested but is not correctly configured."""


_INTERNAL_LLM_BRIDGE_HOSTS = {
    "llm_bridge",
    "aegis_llm_bridge",
    "judge",
    "aegis_judge",
    "debate",
    "aegis_debate",
    "localhost",
    "127.0.0.1",
}


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


def _build_mtls_context(ca: str, cert: Optional[str] = None, key: Optional[str] = None) -> ssl.SSLContext:
    checks = [("CA", ca)]
    if cert or key:
        checks.extend([("client cert", cert or ""), ("client key", key or "")])
    for label, path in checks:
        if not path or not os.path.isfile(path):
            raise MeshTLSConfigError(f"AEGIS_MESH {label} file not found: {path}")

    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca)
    if cert and key:
        ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def client_tls_kwargs(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """httpx Client/AsyncClient kwargs enabling mutual TLS, or {} when relaxed mode is active."""
    env = os.environ if env is None else env
    if not mesh_enabled(env):
        if mesh_strict(env):
            raise MeshTLSConfigError(
                "AEGIS_MESH_STRICT is enabled but AEGIS_MESH_CA/CERT/KEY are not configured"
            )
        return {}

    ctx = _build_mtls_context(env["AEGIS_MESH_CA"], env["AEGIS_MESH_CERT"], env["AEGIS_MESH_KEY"])
    return {"verify": ctx}


def url_allowed(service_name: str, url: str, env: Optional[Mapping[str, str]] = None) -> bool:
    """False when `service_name` requires mTLS (or full strict mesh is enabled) and URL is not https."""
    env = os.environ if env is None else env
    if mesh_strict(env) or service_name in mesh_detectors(env):
        return url.lower().startswith("https://")
    return True


def llm_tls_kwargs(url: str, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """
    Returns httpx TLS kwargs for orchestrator/debate -> LLM bridge or external LLM traffic.
    Refuses plaintext http:// when strict mesh/mTLS is enabled, attaches mTLS client certs
    when communicating with an internal LLM bridge or when AEGIS_LLM_MTLS=1, and enforces
    TLS 1.2+ for public HTTPS providers.
    """
    env = os.environ if env is None else env
    strict_llm = mesh_strict(env) or mesh_enabled(env) or _is_truthy(env.get("AEGIS_LLM_STRICT"))

    if not url.lower().startswith("https://"):
        if strict_llm:
            raise MeshTLSConfigError(
                f"Plaintext http:// refused for LLM/Judge traffic in strict TLS mode: {url}"
            )
        return {}

    llm_ca = env.get("AEGIS_LLM_CA")
    llm_cert = env.get("AEGIS_LLM_CERT")
    llm_key = env.get("AEGIS_LLM_KEY")
    if llm_ca or llm_cert or llm_key:
        if not llm_ca:
            raise MeshTLSConfigError("AEGIS_LLM_CA must be configured alongside AEGIS_LLM_CERT/KEY")
        return {"verify": _build_mtls_context(llm_ca, llm_cert, llm_key)}

    host = (urlparse(url).hostname or "").lower()
    use_mesh_for_llm = _is_truthy(env.get("AEGIS_LLM_MTLS")) or (
        mesh_enabled(env) and host in _INTERNAL_LLM_BRIDGE_HOSTS
    )
    if use_mesh_for_llm:
        if not mesh_enabled(env):
            raise MeshTLSConfigError(
                "AEGIS_LLM_MTLS is enabled but AEGIS_MESH_CA/CERT/KEY are missing"
            )
        return client_tls_kwargs(env)

    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return {"verify": ctx}
