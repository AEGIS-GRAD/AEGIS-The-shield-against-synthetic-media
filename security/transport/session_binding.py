"""
AEGIS camera session binding — Week 11 Task 6
=============================================

Closes the cross-session replay gap in the live ingestion protocol.

The legacy protocol starts every session's hash chain at the constant
``SHA-256("AEGIS_GENESIS")``, restarts ``sequence_number`` at 1 and (for some
clients) uses relative timestamps. A stream captured from a camera yesterday
therefore re-validates frame-for-frame when replayed today by anything holding
that camera's certificate (a compromised camera, a stolen key, a man-in-the-
middle box on the camera side of the TLS tunnel).

With ``AEGIS_SESSION_BINDING=enforce`` the gateway sends a hello line right
after the mTLS handshake::

    {"type": "session_hello", "binding": "v1", "camera_id": "...",
     "session_nonce": "<128-bit hex>", "server_time_ms": 1794855280123}

and the chain genesis becomes ``SHA-256("AEGIS_GENESIS|v1|<camera_id>|<nonce>")``.
A recording from any other session fails at its first frame. Absolute
``timestamp_ms`` values are also checked against the gateway clock
(``AEGIS_MAX_CLOCK_SKEW_MS``, default 2000 ms), which catches skewed or
time-shifted cameras and replays that rewrite timestamps.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import socket
import time
from dataclasses import dataclass
from typing import Optional, Tuple

LEGACY_GENESIS = hashlib.sha256(b"AEGIS_GENESIS").hexdigest()
BINDING_VERSION = "v1"


def session_genesis(camera_id: str, session_nonce: str) -> str:
    return hashlib.sha256(f"AEGIS_GENESIS|{BINDING_VERSION}|{camera_id}|{session_nonce}".encode("utf-8")).hexdigest()


def new_session_hello(camera_id: str) -> Tuple[dict, str]:
    nonce = secrets.token_hex(16)
    hello = {
        "type": "session_hello",
        "binding": BINDING_VERSION,
        "camera_id": camera_id,
        "session_nonce": nonce,
        "server_time_ms": int(time.time() * 1000),
    }
    return hello, session_genesis(camera_id, nonce)


def read_session_hello(sock, timeout_s: float = 1.5) -> Optional[dict]:
    """Client side: returns the gateway's hello if one arrives, else None (legacy gateway)."""
    old = sock.gettimeout()
    sock.settimeout(timeout_s)
    buf = b""
    try:
        while not buf.endswith(b"\n") and len(buf) < 4096:
            chunk = sock.recv(1)
            if not chunk:
                break
            buf += chunk
    except (socket.timeout, TimeoutError, OSError):
        return None
    finally:
        sock.settimeout(old)
    try:
        msg = json.loads(buf.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return msg if isinstance(msg, dict) and msg.get("type") == "session_hello" else None


def client_genesis(hello: Optional[dict]) -> str:
    if hello and hello.get("binding") == BINDING_VERSION:
        return session_genesis(hello["camera_id"], hello["session_nonce"])
    return LEGACY_GENESIS


@dataclass
class ClockCheck:
    """Absolute-time check for frames in a bound session."""

    max_skew_ms: int = 2000

    def skew(self, timestamp_ms: int, now_ms: Optional[int] = None) -> int:
        return int(timestamp_ms) - int(now_ms if now_ms is not None else time.time() * 1000)

    def violation(self, timestamp_ms: int, now_ms: Optional[int] = None) -> Optional[int]:
        s = self.skew(timestamp_ms, now_ms)
        return s if abs(s) > self.max_skew_ms else None
