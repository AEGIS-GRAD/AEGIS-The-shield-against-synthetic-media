"""
Week 11 Task 6 — Camera device lifecycle against the real ingestion gateway.

Two gateway processes are started over real mTLS sockets:
  * ``legacy``  — default protocol (AEGIS_SESSION_BINDING=off) with CRL enforcement
  * ``bound``   — AEGIS_SESSION_BINDING=enforce (nonce-bound chain genesis + clock checks)

Ground truth for "accepted" is the gateway's own per-frame metrics sink, which
records only frames that passed every integrity check (VALID), so the tests do
not depend on how quickly TLS alerts reach the client.

Run:  pytest security/tests/test_device_lifecycle.py -v
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
import psutil
import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

from security.transport.device_lifecycle import DeviceCA  # noqa: E402
from security.transport.generate_certs import generate_all_service_certs, generate_cert, save_cert  # noqa: E402
from security.transport.session_binding import LEGACY_GENESIS, client_genesis, read_session_hello  # noqa: E402

CERTS = _REPO / "security" / "transport" / "certs"
SERVER = _REPO / "security" / "gateway" / "ingestion" / "server.py"
UTC = dt.timezone.utc


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Gateway:
    def __init__(self, workdir: Path, binding: str):
        self.port = _free_port()
        self.metrics = workdir / f"metrics_{binding}.jsonl"
        self.crl = workdir / f"crl_{binding}.pem"
        self.log = open(workdir / f"gateway_{binding}.log", "w")
        env = os.environ.copy()
        env.update({
            "AEGIS_SECURITY_PROFILE": "prod", "AEGIS_INGESTION_PORT": str(self.port),
            "AEGIS_DISABLE_TELEMETRY": "1", "AEGIS_SESSION_BINDING": binding,
            "AEGIS_CRL_PATH": str(self.crl), "AEGIS_CRL_POLL_S": "0.3",
            "AEGIS_LIVE_METRICS_PATH": str(self.metrics), "AEGIS_PRNU_CHECK_INTERVAL": "100000",
            "AEGIS_MAX_STREAMS_PER_IP": "50", "AEGIS_MAX_CONCURRENT_STREAMS": "50",
        })
        self.proc = subprocess.Popen([sys.executable, str(SERVER)], env=env, cwd=str(_REPO),
                                     stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.25)
        raise RuntimeError("gateway did not start")

    def valid_frames(self, local_port: int) -> int:
        """Frames from one client connection that passed every gateway check."""
        time.sleep(0.6)
        n = 0
        if self.metrics.exists():
            for line in self.metrics.read_text().splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("stream") == f"127.0.0.1:{local_port}" and "event" not in row:
                    n += 1
        return n

    def events(self, local_port: int, kind: str) -> int:
        time.sleep(0.3)
        if not self.metrics.exists():
            return 0
        return sum(1 for l in self.metrics.read_text().splitlines()
                   if f'"127.0.0.1:{local_port}"' in l and f'"event":"{kind}"' in l)

    def stop(self) -> None:
        try:
            for c in psutil.Process(self.proc.pid).children(recursive=True):
                c.kill()
        except psutil.Error:
            pass
        self.proc.kill()
        self.proc.wait(timeout=10)
        self.log.close()


@pytest.fixture(scope="module")
def workdir(tmp_path_factory):
    if not (CERTS / "ca.key").exists():
        generate_all_service_certs(str(CERTS))
    return tmp_path_factory.mktemp("lifecycle")


@pytest.fixture(scope="module")
def ca(workdir) -> DeviceCA:
    ca_cert = x509.load_pem_x509_certificate((CERTS / "ca.crt").read_bytes())
    ca_key = serialization.load_pem_private_key((CERTS / "ca.key").read_bytes(), password=None)
    return DeviceCA(ca_cert, ca_key, workdir / "ca_state")


@pytest.fixture(scope="module")
def legacy_gw(workdir):
    gw = Gateway(workdir, "off")
    yield gw
    gw.stop()


@pytest.fixture(scope="module")
def bound_gw(workdir):
    gw = Gateway(workdir, "enforce")
    yield gw
    gw.stop()


FRAMES = []
for i in range(12):
    img = np.random.default_rng(i).integers(0, 255, (48, 64, 3), dtype=np.uint8)
    FRAMES.append(cv2.imencode(".jpg", img)[1].tobytes())


class Session:
    """One camera connection. Returns what was sent so a test can replay it."""

    def __init__(self, port: int, crt: Path, key: Path):
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(CERTS / "ca.crt"))
        ctx.load_cert_chain(str(crt), str(key))
        ctx.check_hostname = False
        self.error: Optional[str] = None
        self.sent_lines: List[bytes] = []
        self.hello = None
        try:
            raw = socket.create_connection(("127.0.0.1", port), timeout=5)
            self.sock = ctx.wrap_socket(raw, server_hostname="localhost")
            self.local_port = self.sock.getsockname()[1]
        except (ssl.SSLError, OSError) as exc:
            self.sock, self.local_port, self.error = None, -1, f"handshake: {exc}"

    def stream(self, n: int = 10, bound: bool = False, ts_offset_ms: int = 0, fps: float = 25.0,
               replay: Optional[List[bytes]] = None) -> "Session":
        if self.sock is None:
            return self
        genesis = LEGACY_GENESIS
        if bound:
            self.hello = read_session_hello(self.sock)
            genesis = client_genesis(self.hello)
        lines = replay or []
        if replay is None:
            h, t0 = genesis, int(time.time() * 1000)
            for seq in range(1, n + 1):
                frame = FRAMES[seq % len(FRAMES)]
                h = hashlib.sha256(h.encode() + frame).hexdigest()
                ts = t0 + int((seq - 1) * 1000 / fps) + ts_offset_ms
                lines.append((json.dumps({"sequence_number": seq, "timestamp_ms": ts, "frame_data": frame.hex(),
                                          "hash": h, "width": 64, "height": 48}) + "\n").encode())
        try:
            for line in lines:
                self.sock.sendall(line)
                self.sent_lines.append(line)
                time.sleep(1.0 / fps)
            time.sleep(0.3)
        except (ssl.SSLError, OSError) as exc:
            self.error = f"send: {exc}"
        return self

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass


def _rogue_identity(tmp: Path):
    rogue_ca_key, rogue_ca, subj = generate_cert("Rogue CA", is_ca=True)
    k, c, _ = generate_cert("cam-rogue", issuer_name=subj, issuer_key=rogue_ca_key)
    save_cert(str(tmp), "rogue", k, c)
    return tmp / "rogue.crt", tmp / "rogue.key"


# ─────────────────────────────────────────────────────────────────────────────
# Issuance and validity
# ─────────────────────────────────────────────────────────────────────────────
def test_enrolled_camera_is_accepted(ca, legacy_gw):
    crt, key, _ = ca.issue_camera("cam-enrolled")
    s = Session(legacy_gw.port, crt, key).stream(10)
    s.close()
    assert legacy_gw.valid_frames(s.local_port) == 10


def test_camera_from_rogue_ca_is_rejected(legacy_gw, workdir):
    crt, key = _rogue_identity(workdir)
    s = Session(legacy_gw.port, crt, key).stream(5)
    s.close()
    assert legacy_gw.valid_frames(s.local_port) == 0


def test_expired_camera_certificate_is_rejected(ca, legacy_gw):
    crt, key, _ = ca.issue_camera("cam-expired", valid_days=1, not_before=dt.datetime.now(UTC) - dt.timedelta(days=5))
    s = Session(legacy_gw.port, crt, key).stream(5)
    s.close()
    assert legacy_gw.valid_frames(s.local_port) == 0


def test_not_yet_valid_certificate_is_rejected(ca, legacy_gw):
    """A camera provisioned by a CA host whose clock runs a day fast."""
    crt, key, _ = ca.issue_camera("cam-future", not_before=dt.datetime.now(UTC) + dt.timedelta(days=1))
    s = Session(legacy_gw.port, crt, key).stream(5)
    s.close()
    assert legacy_gw.valid_frames(s.local_port) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Revocation and rotation (CRL)
# ─────────────────────────────────────────────────────────────────────────────
def test_revocation_is_enforced_once_crl_published(ca, legacy_gw):
    stolen_crt, stolen_key, stolen_serial = ca.issue_camera("cam-stolen")
    other_crt, other_key, _ = ca.issue_camera("cam-other")
    ca.revoke(stolen_serial, reason="key_compromise")

    # Before a CRL exists the gateway has no way to know (the pre-Week-11 behaviour).
    s = Session(legacy_gw.port, stolen_crt, stolen_key).stream(5)
    s.close()
    assert legacy_gw.valid_frames(s.local_port) == 5

    ca.write_crl(path=legacy_gw.crl)
    time.sleep(1.5)  # gateway polls every 0.3 s
    s = Session(legacy_gw.port, stolen_crt, stolen_key).stream(5)
    s.close()
    assert legacy_gw.valid_frames(s.local_port) == 0
    ok = Session(legacy_gw.port, other_crt, other_key).stream(5)
    ok.close()
    assert legacy_gw.valid_frames(ok.local_port) == 5


def test_revocation_severs_an_already_open_session(ca, legacy_gw):
    crt, key, serial = ca.issue_camera("cam-live-revoke")
    s = Session(legacy_gw.port, crt, key)
    t = threading.Thread(target=s.stream, kwargs={"n": 150, "fps": 25})
    t.start()
    time.sleep(1.5)
    ca.revoke(serial, reason="key_compromise")
    ca.write_crl(path=legacy_gw.crl)
    t.join(timeout=15)
    s.close()
    accepted = legacy_gw.valid_frames(s.local_port)
    assert 10 < accepted < 120, f"session should be cut shortly after revocation (accepted {accepted}/150)"


def test_rotation_overlap_then_supersede(ca, legacy_gw):
    old_crt, old_key, old_serial = ca.issue_camera("cam-rotating")
    new_crt, new_key, _ = ca.renew_camera("cam-rotating")
    for crt, key in ((old_crt, old_key), (new_crt, new_key)):
        s = Session(legacy_gw.port, crt, key).stream(5)
        s.close()
        assert legacy_gw.valid_frames(s.local_port) == 5, "both certs valid during the overlap window"
    ca.revoke(old_serial, reason="superseded")
    ca.write_crl(path=legacy_gw.crl)
    time.sleep(1.5)
    s_old = Session(legacy_gw.port, old_crt, old_key).stream(5)
    s_old.close()
    s_new = Session(legacy_gw.port, new_crt, new_key).stream(5)
    s_new.close()
    assert legacy_gw.valid_frames(s_old.local_port) == 0
    assert legacy_gw.valid_frames(s_new.local_port) == 5


# ─────────────────────────────────────────────────────────────────────────────
# Cross-session replay
# ─────────────────────────────────────────────────────────────────────────────
def test_cross_session_replay_succeeds_on_legacy_protocol(ca, legacy_gw):
    crt, key, _ = ca.issue_camera("cam-replay-legacy")
    first = Session(legacy_gw.port, crt, key).stream(10)
    first.close()
    assert legacy_gw.valid_frames(first.local_port) == 10
    time.sleep(1.0)
    replay = Session(legacy_gw.port, crt, key).stream(replay=list(first.sent_lines))
    replay.close()
    assert legacy_gw.valid_frames(replay.local_port) == 10, "legacy protocol accepts a verbatim replay"


def test_cross_session_replay_rejected_with_session_binding(ca, bound_gw):
    crt, key, _ = ca.issue_camera("cam-replay-bound")
    first = Session(bound_gw.port, crt, key).stream(10, bound=True)
    first.close()
    assert first.hello is not None and len(first.hello["session_nonce"]) == 32
    assert bound_gw.valid_frames(first.local_port) == 10
    replay = Session(bound_gw.port, crt, key)
    replay.hello = read_session_hello(replay.sock)  # attacker reads the new hello but cannot re-hash old frames' chain
    replay.stream(replay=list(first.sent_lines))
    replay.close()
    assert bound_gw.valid_frames(replay.local_port) == 0


def test_legacy_client_is_refused_by_bound_gateway(ca, bound_gw):
    """Migration requirement: every client must speak the hello before enforcement."""
    crt, key, _ = ca.issue_camera("cam-old-firmware")
    s = Session(bound_gw.port, crt, key).stream(5, bound=False)
    s.close()
    assert bound_gw.valid_frames(s.local_port) == 0


def test_rtsp_bridge_negotiates_binding(ca, bound_gw):
    spec = importlib.util.spec_from_file_location("aegis_bridge", _REPO / "security" / "gateway" / "rtsp_bridge" / "bridge.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    crt, key, _ = ca.issue_camera("cam-bridge")
    s = Session(bound_gw.port, crt, key)
    genesis = bridge.negotiate_genesis(s.sock)
    assert genesis != bridge.GENESIS_HASH
    s.close()


# ─────────────────────────────────────────────────────────────────────────────
# Clock skew
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("offset_ms,expect_valid", [(400, 6), (-1500, 6), (10 * 60 * 1000, 0), (-30_000, 0)])
def test_clock_skew_handling_with_session_binding(ca, bound_gw, offset_ms, expect_valid):
    crt, key, _ = ca.issue_camera(f"cam-skew-{offset_ms}")
    s = Session(bound_gw.port, crt, key).stream(6, bound=True, ts_offset_ms=offset_ms)
    s.close()
    assert bound_gw.valid_frames(s.local_port) == expect_valid
    if expect_valid == 0:
        assert bound_gw.events(s.local_port, "CLOCK_SKEW") >= 1


def test_clock_skew_invisible_on_legacy_protocol(ca, legacy_gw):
    """Without binding the gateway never compares camera time to its own clock."""
    crt, key, _ = ca.issue_camera("cam-skew-legacy")
    s = Session(legacy_gw.port, crt, key).stream(6, ts_offset_ms=10 * 60 * 1000)
    s.close()
    assert legacy_gw.valid_frames(s.local_port) == 6


def test_crl_expiry_fails_closed(ca, workdir):
    """An expired CRL must stop all cameras (fail-closed), not silently disable revocation."""
    from cryptography.hazmat.primitives import hashes

    crl_path = workdir / "expired_crl.pem"
    now = dt.datetime.now(UTC)
    expired = (x509.CertificateRevocationListBuilder().issuer_name(ca.ca_cert.subject)
               .last_update(now - dt.timedelta(hours=2)).next_update(now - dt.timedelta(hours=1))
               .sign(ca.ca_key, hashes.SHA256()))
    crl_path.write_bytes(expired.public_bytes(serialization.Encoding.PEM))
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH, cafile=str(CERTS / "ca.crt"))
    ctx.load_verify_locations(cafile=str(crl_path))
    ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
    crt, key, _ = ca.issue_camera("cam-crl-expiry")
    store = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(CERTS / "ca.crt"))
    store.load_cert_chain(str(crt), str(key))
    store.check_hostname = False
    ctx.load_cert_chain(str(CERTS / "server.crt"), str(CERTS / "server.key"))
    ctx.verify_mode = ssl.CERT_REQUIRED
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    result = {}

    def serve():
        conn, _ = srv.accept()
        try:
            ctx.wrap_socket(conn, server_side=True).close()
            result["server"] = "accepted"
        except ssl.SSLError as exc:
            result["server"] = str(exc)

    t = threading.Thread(target=serve)
    t.start()
    try:
        c = store.wrap_socket(socket.create_connection(("127.0.0.1", port)), server_hostname="localhost")
        c.recv(1)
    except (ssl.SSLError, OSError):
        pass
    t.join(timeout=5)
    srv.close()
    assert "expired" in result.get("server", "").lower()
