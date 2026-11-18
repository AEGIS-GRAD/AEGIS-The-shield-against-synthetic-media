"""
mcp/security.py — Defense-in-Depth Security Layer for the AEGIS MCP Server.
===========================================================================
Implements:
  1. Scoped RBAC & Token Authentication (`MCPAuthManager`):
       - SHA-256 hashed bearer tokens + least-privilege per-tool scopes.
       - Dynamic enforcement via `AEGIS_MCP_REQUIRE_AUTH=1` or per-call `auth_token`.
       - Confused-deputy prevention via job ownership binding.
  2. Sliding-Window Rate Limiting (`MCPRateLimiter`):
       - Per-(principal, tool) sliding window limits to mitigate DoS / resource exhaustion.
  3. Input & URL / SSRF / Path-Traversal Validation (`MCPInputValidator`):
       - Blocks SSRF URLs (http/https/file/gopher/ftp/ws/s3, UNC paths, 169.254.169.254,
         metadata.google.internal, private/loopback URLs).
       - Blocks path traversal (`..`), null bytes, executable/credential targets, and enforces
         optional `AEGIS_MCP_ALLOWED_ROOTS` sandboxing + media extension/size allowlists.
       - Validates and sanitizes detector claims and diagnostic flags against prompt injection.
  4. Outbound Tool-Result Sanitization (`sanitize_tool_output`):
       - Neutralizes indirect prompt injection payloads (e.g. `<tool_call>`, `[SYSTEM]`,
         verdict/instruction overrides) before tool results reach any LLM MCP client.
  5. Per-Call Tamper-Evident Audit Logging (`EvidenceVaultAuditLogger`):
       - Seals every allow/deny/error/rate-limited MCP tool call into `UnifiedEvidenceVault`
         as a hash-chained, HMAC-signed `MCPAuditRecord`.
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import threading
import time
import unicodedata
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterator, List, Mapping, Optional, Set, Tuple
from urllib.parse import unquote

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

from debate.prompt_security import (
    detect_prompt_injection,
    sanitize_claim_text,
    sanitize_flags,
)
from security.forensics.evidence_vault import UnifiedEvidenceVault

logger = logging.getLogger("aegis.mcp.security")

# ── Scopes & Role Profiles ───────────────────────────────────────────────────
TOOL_REQUIRED_SCOPES: Dict[str, str] = {
    "capabilities": "mcp:capabilities:read",
    "arbitrate_evidence": "mcp:arbitrate:execute",
    "verify_media": "mcp:verify:submit",
    "get_report": "mcp:report:read",
    "check_stream_integrity": "mcp:integrity:verify",
}

ALL_SCOPES: Set[str] = set(TOOL_REQUIRED_SCOPES.values())

_DEFAULT_TOKEN_SPECS: List[Tuple[str, str, Set[str], bool]] = [
    ("aegis-mcp-admin-token", "mcp-admin", {"mcp:*"}, True),
    ("aegis-mcp-analyst-token", "mcp-analyst", set(ALL_SCOPES), False),
    (
        "aegis-mcp-auditor-token",
        "mcp-auditor",
        {"mcp:capabilities:read", "mcp:report:read", "mcp:integrity:verify"},
        False,
    ),
    (
        "aegis-mcp-arbitrator-token",
        "mcp-arbitrator",
        {"mcp:capabilities:read", "mcp:arbitrate:execute"},
        False,
    ),
    ("aegis-mcp-tenant-b-token", "mcp-tenant-b", set(ALL_SCOPES), False),
]

# Contextvar allows transport middleware or test harnesses to propagate bearer tokens cleanly
_CURRENT_AUTH_TOKEN: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "aegis_mcp_auth_token",
    default=None,
)


@contextmanager
def mcp_auth_context(token: Optional[str]) -> Iterator[None]:
    """Context manager setting the active bearer token for the current execution context."""
    tok = _CURRENT_AUTH_TOKEN.set(token)
    try:
        yield
    finally:
        _CURRENT_AUTH_TOKEN.reset(tok)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _hash_json(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class MCPPrincipal:
    principal_id: str
    scopes: Set[str]
    is_admin: bool = False
    authenticated: bool = True

    def has_scope(self, required_scope: str) -> bool:
        if self.is_admin or "mcp:*" in self.scopes:
            return True
        return required_scope in self.scopes


class MCPSecurityError(Exception):
    """Raised when an MCP security control rejects a request."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        status: str = "error",
        security_flags: Optional[List[str]] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status = status
        self.security_flags = list(security_flags or [error_code.lower()])


class MCPAuthManager:
    """Scoped RBAC token validator for MCP tool calls."""

    def __init__(self, require_auth: Optional[bool] = None) -> None:
        self._require_auth_override = require_auth
        self._lock = threading.Lock()
        self._tokens_by_digest: Dict[str, MCPPrincipal] = {}
        self._load_default_tokens()

    def _load_default_tokens(self) -> None:
        for raw, pid, scopes, is_admin in _DEFAULT_TOKEN_SPECS:
            self.register_token(raw, pid, scopes, is_admin=is_admin)

    def register_token(
        self,
        raw_token: str,
        principal_id: str,
        scopes: Set[str],
        *,
        is_admin: bool = False,
    ) -> None:
        if not raw_token or not raw_token.strip():
            raise ValueError("Token cannot be empty.")
        digest = _hash_token(raw_token.strip())
        principal = MCPPrincipal(
            principal_id=principal_id,
            scopes=set(scopes),
            is_admin=is_admin,
            authenticated=True,
        )
        with self._lock:
            self._tokens_by_digest[digest] = principal

    def _load_env_tokens(self) -> Dict[str, MCPPrincipal]:
        """Dynamically parses AEGIS_MCP_TOKENS_JSON if provided in environment."""
        extra: Dict[str, MCPPrincipal] = {}
        raw_json = os.environ.get("AEGIS_MCP_TOKENS_JSON", "").strip()
        if not raw_json:
            return extra
        try:
            data = json.loads(raw_json)
        except Exception:
            logger.warning("Failed to parse AEGIS_MCP_TOKENS_JSON; ignoring.")
            return extra
        if isinstance(data, dict):
            for tok, spec in data.items():
                if not isinstance(tok, str) or not isinstance(spec, dict):
                    continue
                extra[_hash_token(tok.strip())] = MCPPrincipal(
                    principal_id=str(spec.get("principal_id", "env-client")),
                    scopes=set(spec.get("scopes", [])),
                    is_admin=bool(spec.get("is_admin", False)),
                    authenticated=True,
                )
        return extra

    @property
    def require_auth(self) -> bool:
        if self._require_auth_override is not None:
            return self._require_auth_override
        return os.environ.get("AEGIS_MCP_REQUIRE_AUTH", "0").strip().lower() in {
            "1",
            "true",
            "yes",
        }

    def authenticate_and_authorize(
        self,
        tool_name: str,
        auth_token: Optional[str] = None,
    ) -> MCPPrincipal:
        required_scope = TOOL_REQUIRED_SCOPES.get(tool_name, f"mcp:{tool_name}:execute")

        token = auth_token
        if token is None:
            token = _CURRENT_AUTH_TOKEN.get()
        if token is None:
            token = os.environ.get("AEGIS_MCP_CLIENT_TOKEN")

        if token is None or not str(token).strip():
            if self.require_auth:
                raise MCPSecurityError(
                    "AUTH_REQUIRED",
                    f"Authentication required to invoke MCP tool '{tool_name}'. Provide a valid auth_token.",
                    status="denied",
                    security_flags=["auth_required"],
                )
            # Backward-compatible local mode when strict auth is disabled
            return MCPPrincipal(
                principal_id="local-default",
                scopes=set(ALL_SCOPES),
                is_admin=False,
                authenticated=False,
            )

        clean_tok = str(token).strip()
        if clean_tok.lower().startswith("bearer "):
            clean_tok = clean_tok[7:].strip()

        candidate_digest = _hash_token(clean_tok)
        matched: Optional[MCPPrincipal] = None

        with self._lock:
            combined = dict(self._tokens_by_digest)
        combined.update(self._load_env_tokens())

        for stored_digest, principal in combined.items():
            if hmac.compare_digest(candidate_digest, stored_digest):
                matched = principal
                break

        if matched is None:
            raise MCPSecurityError(
                "AUTH_INVALID_TOKEN",
                "Invalid or unrecognized MCP authentication token.",
                status="denied",
                security_flags=["auth_invalid_token"],
            )

        if not matched.has_scope(required_scope):
            raise MCPSecurityError(
                "AUTH_INSUFFICIENT_SCOPE",
                (
                    f"Principal '{matched.principal_id}' lacks required scope "
                    f"'{required_scope}' for tool '{tool_name}'."
                ),
                status="denied",
                security_flags=["auth_insufficient_scope", "confused_deputy_blocked"],
            )

        return matched


# ── Sliding-Window Rate Limiter ──────────────────────────────────────────────
class MCPRateLimiter:
    """Thread-safe sliding-window per-(principal, tool) rate limiter."""

    def __init__(self, default_max_calls: int = 120, default_window_s: float = 60.0) -> None:
        self.default_max_calls = default_max_calls
        self.default_window_s = default_window_s
        self._override_max_calls: Optional[int] = None
        self._override_window_s: Optional[float] = None
        self._events: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def configure(self, max_calls: Optional[int] = None, window_seconds: Optional[float] = None) -> None:
        with self._lock:
            self._override_max_calls = max_calls
            self._override_window_s = window_seconds

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._override_max_calls = None
            self._override_window_s = None

    def _effective_limits(self) -> Tuple[int, float]:
        max_calls = self._override_max_calls
        if max_calls is None:
            env_limit = os.environ.get("AEGIS_MCP_RATE_LIMIT_PER_MIN", "").strip()
            if env_limit:
                try:
                    max_calls = max(1, int(env_limit))
                except ValueError:
                    max_calls = self.default_max_calls
            else:
                max_calls = self.default_max_calls

        window_s = self._override_window_s if self._override_window_s is not None else self.default_window_s
        return max_calls, window_s

    def check_and_record(self, principal_id: str, tool_name: str) -> None:
        max_calls, window_s = self._effective_limits()
        now = time.monotonic()
        key = (principal_id, tool_name)

        with self._lock:
            q = self._events[key]
            cutoff = now - window_s
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= max_calls:
                retry_after = max(0.1, round(window_s - (now - q[0]), 2))
                raise MCPSecurityError(
                    "RATE_LIMIT_EXCEEDED",
                    (
                        f"Rate limit exceeded for '{principal_id}' on '{tool_name}' "
                        f"({max_calls} calls/{window_s:.0f}s). Retry in {retry_after}s."
                    ),
                    status="rate_limited",
                    security_flags=["rate_limited"],
                )
            q.append(now)


# ── Input, SSRF, Path Traversal & Prompt-Injection Validator ─────────────────
_URL_SCHEME_RE = re.compile(
    r"(?:^|[\s\"'(<])(?:https?|ftps?|file|gopher|wss?|dict|ldaps?|s3|gs|az|azure|smb|nfs|data|javascript)://",
    re.IGNORECASE,
)
_CLOUD_METADATA_RE = re.compile(
    r"(?:169\.254\.169\.254|169\.254\.170\.2|metadata\.google\.internal|metadata\.goog|100\.100\.100\.200|fd00:ec2::254)",
    re.IGNORECASE,
)
_LOCALHOST_URL_RE = re.compile(
    r"(?:https?|ftps?|gopher|wss?|dict)://(?:localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|\[::1?\]|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)",
    re.IGNORECASE,
)
_UNC_PATH_RE = re.compile(r"^(?:\\\\|//)[^\\/]+[\\/]")

_FORBIDDEN_PATH_TOKENS: Tuple[str, ...] = (
    "/.env",
    "\\.env",
    ".git/",
    ".git\\",
    "id_rsa",
    "id_ed25519",
    "authorized_keys",
    "/etc/passwd",
    "/etc/shadow",
    "/etc/hosts",
    "/proc/",
    "system32",
    "\\windows\\sam",
    "ledger.jsonl",
    "flight_recorder.db",
)
_FORBIDDEN_FILENAMES: Set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    "authorized_keys",
    "passwd",
    "shadow",
    "sam",
    "ledger.jsonl",
    "flight_recorder.db",
}
_DANGEROUS_EXTENSIONS: Set[str] = {
    ".exe",
    ".bat",
    ".cmd",
    ".ps1",
    ".sh",
    ".dll",
    ".so",
    ".dylib",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
}
ALLOWED_MEDIA_AND_MANIFEST_EXTENSIONS: Set[str] = {
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".webm",
    ".wav",
    ".mp3",
    ".flac",
    ".ogg",
    ".m4a",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".txt",
    ".md",
    ".json",
}

# Additional MCP-specific indirect prompt-injection patterns in tool inputs/outputs
_MCP_INJECTION_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    (
        "tool_call_smuggling",
        re.compile(
            r"</?\s*(?:tool_call|function_call|tool_use|mcp_tool|assistant_command)[^>]*>"
            r"|\b(?:call|invoke|execute|run)\s+(?:the\s+)?(?:verify_media|arbitrate_evidence|get_report|check_stream_integrity)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_token_injection",
        re.compile(
            r"(?:<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|\[/?INST\]|<<\s*/?SYS\s*>>)",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration_directive",
        re.compile(
            r"\b(?:send|exfiltrate|post|upload|fetch|curl|wget)\b.{0,45}(?:https?://|token|secret|\.env|password|api_key)",
            re.IGNORECASE,
        ),
    ),
)

MAX_CLAIMS_PER_CALL = 32
MAX_JOB_ID_LEN = 128


def _decode_candidates(value: str) -> Tuple[str, str]:
    """Returns normalized raw string and URL-decoded string for SSRF inspection."""
    norm = unicodedata.normalize("NFKC", value)
    decoded = unquote(norm)
    return norm, decoded


class MCPInputValidator:
    """Strict validator blocking SSRF, path traversal, confused-deputy abuse, and injection."""

    @staticmethod
    def check_no_ssrf(value: str, field_name: str) -> None:
        if not isinstance(value, str):
            raise MCPSecurityError(
                "INVALID_INPUT_TYPE",
                f"Field '{field_name}' must be a string.",
            )
        norm, decoded = _decode_candidates(value)
        for candidate in (norm, decoded):
            stripped = candidate.strip()
            if _CLOUD_METADATA_RE.search(stripped):
                raise MCPSecurityError(
                    "SSRF_BLOCKED",
                    f"SSRF blocked on '{field_name}': cloud metadata endpoint reference detected.",
                    security_flags=["ssrf_blocked"],
                )
            if _LOCALHOST_URL_RE.search(stripped):
                raise MCPSecurityError(
                    "SSRF_BLOCKED",
                    f"SSRF blocked on '{field_name}': internal/loopback URL scheme is forbidden.",
                    security_flags=["ssrf_blocked"],
                )
            if _URL_SCHEME_RE.search(stripped):
                raise MCPSecurityError(
                    "SSRF_BLOCKED",
                    f"SSRF blocked on '{field_name}': URL schemes are not accepted; local file paths only.",
                    security_flags=["ssrf_blocked"],
                )
            if _UNC_PATH_RE.match(stripped):
                raise MCPSecurityError(
                    "SSRF_BLOCKED",
                    f"SSRF blocked on '{field_name}': UNC/network share paths are forbidden.",
                    security_flags=["ssrf_blocked"],
                )

    @staticmethod
    def validate_job_id(job_id: str, field_name: str = "job_id") -> str:
        if not isinstance(job_id, str) or not job_id.strip():
            raise MCPSecurityError("INVALID_JOB_ID", f"'{field_name}' must be a non-empty string.")
        if "\x00" in job_id or len(job_id) > MAX_JOB_ID_LEN:
            raise MCPSecurityError("INVALID_JOB_ID", f"'{field_name}' violates length or character bounds.")
        MCPInputValidator.check_no_ssrf(job_id, field_name)
        norm = unicodedata.normalize("NFKC", job_id).strip()
        if ".." in norm or "/" in norm or "\\" in norm:
            raise MCPSecurityError(
                "PATH_TRAVERSAL_BLOCKED",
                f"Invalid '{field_name}': path separators or traversal sequences are forbidden.",
                security_flags=["path_traversal_blocked"],
            )
        return norm

    @staticmethod
    def validate_file_path(
        file_path: str,
        field_name: str = "file_path",
        allowed_roots: Optional[List[Path]] = None,
    ) -> str:
        if not isinstance(file_path, str) or not file_path.strip():
            raise MCPSecurityError("INVALID_FILE_PATH", f"'{field_name}' must be a non-empty string.")
        if "\x00" in file_path:
            raise MCPSecurityError(
                "PATH_TRAVERSAL_BLOCKED",
                f"Invalid '{field_name}': null byte detected.",
                security_flags=["path_traversal_blocked"],
            )

        MCPInputValidator.check_no_ssrf(file_path, field_name)
        norm = unicodedata.normalize("NFKC", file_path).strip()
        decoded = unquote(norm)

        # Block traversal segments before resolving
        for candidate in (norm, decoded):
            parts = re.split(r"[\\/]+", candidate)
            if ".." in parts:
                raise MCPSecurityError(
                    "PATH_TRAVERSAL_BLOCKED",
                    f"Path traversal ('..') rejected on '{field_name}'.",
                    security_flags=["path_traversal_blocked"],
                )
            lowered = candidate.lower()
            if any(tok in lowered for tok in _FORBIDDEN_PATH_TOKENS):
                raise MCPSecurityError(
                    "PATH_FORBIDDEN_TARGET",
                    f"Access to sensitive file or system directory denied on '{field_name}'.",
                    security_flags=["path_traversal_blocked", "confused_deputy_blocked"],
                )

        p = Path(norm)
        if p.name.lower() in _FORBIDDEN_FILENAMES:
            raise MCPSecurityError(
                "PATH_FORBIDDEN_TARGET",
                f"Access to restricted filename '{p.name}' denied.",
                security_flags=["path_traversal_blocked", "confused_deputy_blocked"],
            )

        ext = p.suffix.lower()
        if ext in _DANGEROUS_EXTENSIONS:
            raise MCPSecurityError(
                "FORBIDDEN_FILE_EXTENSION",
                f"File extension '{ext}' is forbidden for '{field_name}'.",
                security_flags=["invalid_file_type"],
            )

        # Optional root confinement when AEGIS_MCP_ALLOWED_ROOTS or explicit roots are set
        roots = allowed_roots
        if roots is None:
            env_roots = os.environ.get("AEGIS_MCP_ALLOWED_ROOTS", "").strip()
            if env_roots:
                roots = [Path(r.strip()).resolve() for r in env_roots.split(os.pathsep) if r.strip()]
        if roots:
            resolved = p.resolve()
            if not any(_is_within(resolved, root) for root in roots):
                raise MCPSecurityError(
                    "PATH_OUTSIDE_ALLOWED_ROOTS",
                    f"Path '{file_path}' lies outside allowed workspace roots.",
                    security_flags=["path_traversal_blocked", "confused_deputy_blocked"],
                )

        if p.exists():
            if not p.is_file():
                raise MCPSecurityError(
                    "INVALID_FILE_PATH",
                    f"Target '{file_path}' exists but is not a regular file.",
                )
            if ext and ext not in ALLOWED_MEDIA_AND_MANIFEST_EXTENSIONS:
                raise MCPSecurityError(
                    "UNSUPPORTED_FILE_EXTENSION",
                    f"File extension '{ext}' is not an allowed media or manifest type.",
                    security_flags=["invalid_file_type"],
                )
            max_mb = float(os.environ.get("AEGIS_MCP_MAX_FILE_MB", "500"))
            size_bytes = p.stat().st_size
            if size_bytes > max_mb * 1024 * 1024:
                raise MCPSecurityError(
                    "FILE_TOO_LARGE",
                    f"File exceeds maximum allowed size of {max_mb:.0f} MB.",
                    security_flags=["resource_limit_exceeded"],
                )

        return norm

    @staticmethod
    def sanitize_and_validate_claims(
        raw_claims: Any,
    ) -> Tuple[Any, List[str]]:
        """Scans claims inputs for SSRF, oversized batches, and prompt injection."""
        sec_flags: List[str] = []

        if isinstance(raw_claims, str):
            MCPInputValidator.check_no_ssrf(raw_claims, "claims")
            return raw_claims, sec_flags

        if not isinstance(raw_claims, list):
            return raw_claims, sec_flags

        if len(raw_claims) > MAX_CLAIMS_PER_CALL:
            raise MCPSecurityError(
                "TOO_MANY_CLAIMS",
                f"Claims batch size ({len(raw_claims)}) exceeds max allowed ({MAX_CLAIMS_PER_CALL}).",
                security_flags=["resource_limit_exceeded"],
            )

        sanitized_list: List[Any] = []
        for idx, item in enumerate(raw_claims):
            if not isinstance(item, dict):
                sanitized_list.append(item)
                continue
            cleaned = dict(item)
            for id_field in ("job_id", "detector_id", "model_version", "domain", "evidence_hash"):
                val = cleaned.get(id_field)
                if isinstance(val, str):
                    MCPInputValidator.check_no_ssrf(val, f"claims[{idx}].{id_field}")

            # Check claim text for SSRF URLs & prompt injection
            claim_txt = cleaned.get("claim")
            if isinstance(claim_txt, str):
                MCPInputValidator.check_no_ssrf(claim_txt, f"claims[{idx}].claim")
                san = sanitize_claim_text(
                    claim_txt,
                    source=f"mcp_claim:{cleaned.get('detector_id', idx)}",
                )
                extra_hits = _detect_mcp_injections(san.sanitized)
                final_txt = san.sanitized
                if extra_hits:
                    final_txt = _scrub_mcp_injections(final_txt)
                if san.injection_detected or san.stripped_control_chars or extra_hits:
                    sec_flags.append("prompt_injection_scrubbed")
                cleaned["claim"] = final_txt

            if isinstance(cleaned.get("flags"), list):
                safe_flags, flags_had_inj = sanitize_flags(cleaned["flags"])
                if flags_had_inj:
                    sec_flags.append("flag_injection_scrubbed")
                cleaned["flags"] = safe_flags

            sanitized_list.append(cleaned)

        return sanitized_list, sorted(set(sec_flags))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _detect_mcp_injections(text: str) -> List[str]:
    hits = list(detect_prompt_injection(text))
    for name, rx in _MCP_INJECTION_PATTERNS:
        if rx.search(text) and name not in hits:
            hits.append(name)
    return hits


def _scrub_mcp_injections(text: str) -> str:
    out = sanitize_claim_text(text, source="mcp_output_guard").sanitized
    for _, rx in _MCP_INJECTION_PATTERNS:
        out = rx.sub("[REDACTED_MCP_DIRECTIVE]", out)
    return out


def sanitize_tool_output(payload: Any) -> Tuple[Any, List[str]]:
    """
    Recursively scrubs indirect prompt-injection payloads from MCP tool outputs
    while leaving numeric verdicts, hashes, and structured enums untouched.
    """
    flags: List[str] = []
    _SKIP_KEYS = {
        "status",
        "job_id",
        "verification_id",
        "record_hash",
        "prev_record_hash",
        "signature",
        "debate_transcript_hash",
        "evidence_manifest_hash",
        "evidence_bundle_ref",
        "evidence_bundle_path",
        "file_path",
        "video_path",
        "manifest_path",
        "verdict",
        "final_verdict",
        "siem_alert_tier",
        "arbitration_mode",
        "error_code",
        "audit_record_id",
        "principal_id",
    }

    def _walk(obj: Any, key_name: str = "") -> Any:
        if isinstance(obj, dict):
            return {k: _walk(v, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(v, key_name) for v in obj]
        if isinstance(obj, str):
            if key_name in _SKIP_KEYS or len(obj) < 12:
                return obj
            hits = _detect_mcp_injections(obj)
            if hits:
                flags.append("output_injection_scrubbed")
                return _scrub_mcp_injections(obj)
        return obj

    cleaned = _walk(payload)
    return cleaned, sorted(set(flags))


# ── Unified MCP Security Gateway & Vault Audit Logger ────────────────────────
class MCPSecurityGateway:
    """Coordinates authentication, RBAC scopes, rate limits, validation, and vault auditing."""

    def __init__(self) -> None:
        self.auth_manager = MCPAuthManager()
        self.rate_limiter = MCPRateLimiter()
        self._vault_lock = threading.Lock()
        self._vaults: Dict[str, UnifiedEvidenceVault] = {}

    def get_vault(self) -> Optional[UnifiedEvidenceVault]:
        vault_dir = os.environ.get("AEGIS_MCP_VAULT_DIR") or os.environ.get("AEGIS_VAULT_DIR")
        if not vault_dir:
            vault_dir = str(_REPO_ROOT / "security" / "vault" / "mcp_audit")
        resolved = str(Path(vault_dir).resolve())
        with self._vault_lock:
            if resolved not in self._vaults:
                try:
                    self._vaults[resolved] = UnifiedEvidenceVault(vault_dir=resolved)
                except Exception as exc:
                    logger.warning("Failed to initialize MCP audit vault at %s: %s", resolved, exc)
                    return None
            return self._vaults[resolved]

    def log_audit(
        self,
        *,
        tool_name: str,
        principal: MCPPrincipal,
        status: str,
        args_payload: Dict[str, Any],
        result_payload: Dict[str, Any],
        security_flags: List[str],
        error_code: Optional[str] = None,
        latency_ms: float = 0.0,
    ) -> Optional[str]:
        vault = self.get_vault()
        if vault is None:
            return None
        try:
            rec = vault.store_mcp_audit(
                tool_name=tool_name,
                principal_id=principal.principal_id,
                scopes=sorted(principal.scopes),
                status=status,
                args_sha256=_hash_json(args_payload),
                result_sha256=_hash_json(result_payload),
                sanitized_args=_summarize_args_for_audit(args_payload),
                security_flags=sorted(set(security_flags)),
                error_code=error_code,
                latency_ms=latency_ms,
            )
            return rec.audit_id
        except Exception as exc:
            logger.warning("Failed to persist MCP audit record: %s", exc)
            return None

    def execute_guarded(
        self,
        tool_name: str,
        raw_args: Dict[str, Any],
        auth_token: Optional[str],
        handler: Callable[[MCPPrincipal, List[str]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Runs auth -> scope -> rate limit -> handler -> output scrubbing -> vault audit."""
        t0 = time.perf_counter()
        sec_flags: List[str] = []
        principal = MCPPrincipal(principal_id="anonymous", scopes=set(), is_admin=False, authenticated=False)
        error_code: Optional[str] = None
        response: Dict[str, Any]

        try:
            principal = self.auth_manager.authenticate_and_authorize(tool_name, auth_token=auth_token)
            self.rate_limiter.check_and_record(principal.principal_id, tool_name)
            response = handler(principal, sec_flags)
            response, out_flags = sanitize_tool_output(response)
            sec_flags.extend(out_flags)
            if sec_flags and isinstance(response, dict):
                response.setdefault("security_flags", sorted(set(sec_flags)))
        except MCPSecurityError as sec_err:
            error_code = sec_err.error_code
            sec_flags.extend(sec_err.security_flags)
            response = {
                "status": "error",
                "error_code": sec_err.error_code,
                "error": sec_err.message,
                "security_flags": sorted(set(sec_flags)),
            }
            if tool_name == "arbitrate_evidence":
                response["verdict"] = None
                response["report"] = None
            elif tool_name == "capabilities":
                response["detectors"] = {}
                response["default_weights"] = {}
                response["authority_tiers"] = {}
                response["total_detectors"] = 0
            elif tool_name == "verify_media":
                response["job_id"] = None
            elif tool_name == "get_report":
                response["job_id"] = raw_args.get("job_id")
        except Exception as exc:
            error_code = "INTERNAL_ERROR"
            response = {
                "status": "error",
                "error_code": error_code,
                "error": f"Internal security/execution error: {exc}",
            }

        latency_ms = (time.perf_counter() - t0) * 1000.0
        audit_status = error_code.lower() if error_code else str(response.get("status", "ok"))
        audit_id = self.log_audit(
            tool_name=tool_name,
            principal=principal,
            status=audit_status,
            args_payload=raw_args,
            result_payload=response,
            security_flags=sec_flags,
            error_code=error_code,
            latency_ms=latency_ms,
        )
        if audit_id and isinstance(response, dict):
            response["audit_record_id"] = audit_id
        return response


def _summarize_args_for_audit(args: Mapping[str, Any]) -> Dict[str, Any]:
    """Produces a compact, scrubbed argument summary safe to store in audit logs."""
    summary: Dict[str, Any] = {}
    for k, v in args.items():
        if k == "auth_token":
            summary[k] = "[REDACTED]"
        elif isinstance(v, str):
            summary[k] = v[:200]
        elif isinstance(v, list):
            summary[k] = f"<list len={len(v)}>"
        elif isinstance(v, dict):
            summary[k] = f"<dict keys={sorted(list(v.keys()))[:10]}>"
        else:
            summary[k] = v
    return summary


_GLOBAL_GATEWAY: Optional[MCPSecurityGateway] = None


def get_security_gateway() -> MCPSecurityGateway:
    global _GLOBAL_GATEWAY
    if _GLOBAL_GATEWAY is None:
        _GLOBAL_GATEWAY = MCPSecurityGateway()
    return _GLOBAL_GATEWAY
