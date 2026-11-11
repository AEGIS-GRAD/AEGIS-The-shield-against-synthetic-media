"""
TLS / mTLS transport helper for AEGIS Debate & Judge LLM traffic (Week 10 Task 1).

Keeps the `debate/` package self-contained (zero cross-imports from `orchestrator/`) while
enforcing identical transport guarantees:
  * In strict mode (AEGIS_MESH_STRICT=1 or AEGIS_LLM_STRICT=1 or AEGIS_MESH_* active),
    plaintext http:// URLs are refused to prevent evidence/prompt leakage or MitM downgrade.
  * When communicating with an internal LLM bridge proxy (or when AEGIS_LLM_MTLS=1 or
    AEGIS_LLM_CA/CERT/KEY are configured), constructs an mTLS SSLContext requiring TLSv1.2+.
  * For public HTTPS providers (e.g. OpenRouter), enforces TLSv1.2+ with hostname verification.
"""

from __future__ import annotations

import os
import ssl
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse


class JudgeTLSConfigError(RuntimeError):
    """Strict TLS/mTLS was requested for Judge/LLM traffic but is misconfigured."""


_INTERNAL_BRIDGE_HOSTS = {
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


def _build_ssl_context(ca: str, cert: Optional[str] = None, key: Optional[str] = None) -> ssl.SSLContext:
    checks = [("CA", ca)]
    if cert or key:
        checks.extend([("client cert", cert or ""), ("client key", key or "")])
    for label, path in checks:
        if not path or not os.path.isfile(path):
            raise JudgeTLSConfigError(f"LLM/Judge TLS {label} file not found: {path}")

    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca)
    if cert and key:
        ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def llm_tls_kwargs(url: str, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Returns httpx client TLS kwargs for Judge/LLM outbound HTTP calls."""
    env = os.environ if env is None else env
    mesh_on = bool(env.get("AEGIS_MESH_CA") and env.get("AEGIS_MESH_CERT") and env.get("AEGIS_MESH_KEY"))
    strict = _is_truthy(env.get("AEGIS_MESH_STRICT")) or _is_truthy(env.get("AEGIS_LLM_STRICT")) or mesh_on

    if not url.lower().startswith("https://"):
        if strict:
            raise JudgeTLSConfigError(f"Plaintext http:// refused for LLM traffic in strict TLS mode: {url}")
        return {}

    llm_ca = env.get("AEGIS_LLM_CA")
    llm_cert = env.get("AEGIS_LLM_CERT")
    llm_key = env.get("AEGIS_LLM_KEY")
    if llm_ca or llm_cert or llm_key:
        if not llm_ca:
            raise JudgeTLSConfigError("AEGIS_LLM_CA must be configured alongside AEGIS_LLM_CERT/KEY")
        return {"verify": _build_ssl_context(llm_ca, llm_cert, llm_key)}

    host = (urlparse(url).hostname or "").lower()
    if _is_truthy(env.get("AEGIS_LLM_MTLS")) or (mesh_on and host in _INTERNAL_BRIDGE_HOSTS):
        if not mesh_on:
            raise JudgeTLSConfigError("AEGIS_LLM_MTLS is enabled but AEGIS_MESH_CA/CERT/KEY are missing")
        return {
            "verify": _build_ssl_context(
                env["AEGIS_MESH_CA"], env["AEGIS_MESH_CERT"], env["AEGIS_MESH_KEY"]
            )
        }

    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return {"verify": ctx}

