"""
AEGIS RTSP-to-mTLS-Ingestion Bridge Sidecar
==========================================
Reads live frames from an RTSP stream (e.g. MediaMTX simulated or physical IP camera),
computes rolling SHA-256 cryptographic frame hash-chains, and pushes authenticated
frames over mutual TLS (mTLS) to the AEGIS Live Ingestion Gateway (:8443).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import ssl
import time
from pathlib import Path

import cv2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [AEGIS-RTSP-Bridge] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("aegis.rtsp_bridge")

# Force OpenCV FFmpeg backend to use reliable TCP transport for RTSP
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

RTSP_URL = os.environ.get("RTSP_URL", "rtsp://mediamtx:8554/live/camera1")
INGESTION_HOST = os.environ.get("INGESTION_HOST", "aegis_ingestion")
INGESTION_PORT = int(os.environ.get("INGESTION_PORT", "8443"))
CERT_DIR = Path(os.environ.get("CERT_DIR", "/certs"))
TARGET_FPS = float(os.environ.get("TARGET_FPS", "10.0"))
FRAME_WIDTH = int(os.environ.get("FRAME_WIDTH", "320"))
FRAME_HEIGHT = int(os.environ.get("FRAME_HEIGHT", "240"))

GENESIS_HASH = hashlib.sha256(b"AEGIS_GENESIS").hexdigest()


def wait_for_certs(cert_dir: Path, timeout_s: float = 60.0) -> tuple[Path, Path, Path]:
    """Waits for ingestion gateway to provision mTLS certificates."""
    ca_crt = cert_dir / "ca.crt"
    client_crt = cert_dir / "client.crt"
    client_key = cert_dir / "client.key"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if ca_crt.exists() and client_crt.exists() and client_key.exists():
            return ca_crt, client_crt, client_key
        logger.info("Waiting for mTLS certificates in %s...", cert_dir)
        time.sleep(2.0)
    raise FileNotFoundError(f"mTLS certificates not found in {cert_dir} after {timeout_s}s.")


def connect_mtls_ingestion(host: str, port: int, ca_crt: Path, client_crt: Path, client_key: Path) -> ssl.SSLSocket:
    """Establishes an authenticated mTLS TCP socket to the AEGIS Ingestion Gateway."""
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca_crt))
    ctx.load_cert_chain(certfile=str(client_crt), keyfile=str(client_key))
    ctx.check_hostname = False  # Authenticated via internal mesh Root CA

    raw_sock = socket.create_connection((host, port), timeout=10.0)
    tls_sock = ctx.wrap_socket(raw_sock, server_hostname=host)
    logger.info("Connected to AEGIS Ingestion Gateway at %s:%d via mTLS.", host, port)
    return tls_sock


def negotiate_genesis(tls_sock: ssl.SSLSocket, timeout_s: float = 1.5) -> str:
    """Session binding (mirrors security/transport/session_binding.py, inlined because
    this container ships only bridge.py). If the gateway sends a session hello, the hash
    chain starts from a nonce-bound genesis so a recording of this session cannot be
    replayed into another one; otherwise the legacy constant genesis is used."""
    old = tls_sock.gettimeout()
    tls_sock.settimeout(timeout_s)
    buf = b""
    try:
        while not buf.endswith(b"\n") and len(buf) < 4096:
            chunk = tls_sock.recv(1)
            if not chunk:
                break
            buf += chunk
        hello = json.loads(buf.decode("utf-8")) if buf else None
    except (socket.timeout, TimeoutError, OSError, ValueError):
        hello = None
    finally:
        tls_sock.settimeout(old)
    if isinstance(hello, dict) and hello.get("type") == "session_hello" and hello.get("binding") == "v1":
        logger.info("Session binding active (nonce %s...).", str(hello["session_nonce"])[:8])
        material = f"AEGIS_GENESIS|v1|{hello['camera_id']}|{hello['session_nonce']}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()
    return GENESIS_HASH


def open_rtsp_capture(rtsp_url: str) -> cv2.VideoCapture:
    """Opens RTSP stream with retry until the camera feed is publishing."""
    while True:
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                logger.info("RTSP stream opened successfully: %s", rtsp_url)
                return cap
        cap.release()
        logger.info("RTSP stream not ready (%s), retrying in 2s...", rtsp_url)
        time.sleep(2.0)


def run_bridge() -> None:
    ca_crt, client_crt, client_key = wait_for_certs(CERT_DIR)
    frame_interval = 1.0 / max(1.0, TARGET_FPS)

    while True:
        cap = None
        tls_sock = None
        try:
            cap = open_rtsp_capture(RTSP_URL)
            tls_sock = connect_mtls_ingestion(
                INGESTION_HOST, INGESTION_PORT, ca_crt, client_crt, client_key
            )

            current_hash = negotiate_genesis(tls_sock)
            seq = 1
            last_ts_ms = int(time.time() * 1000)

            while True:
                t_start = time.monotonic()
                ret, frame = cap.read()
                if not ret or frame is None:
                    logger.warning("RTSP stream EOF or read error; reconnecting...")
                    break

                resized = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
                ok, encoded = cv2.imencode(".png", resized)
                if not ok:
                    continue
                frame_bytes = encoded.tobytes()

                # Compute rolling SHA-256 hash chain matching LiveHashChainValidator
                hasher = hashlib.sha256()
                hasher.update(current_hash.encode("utf-8"))
                hasher.update(frame_bytes)
                current_hash = hasher.hexdigest()

                now_ms = int(time.time() * 1000)
                if now_ms <= last_ts_ms:
                    now_ms = last_ts_ms + 1
                last_ts_ms = now_ms

                payload = {
                    "sequence_number": seq,
                    "timestamp_ms": now_ms,
                    "frame_data": frame_bytes.hex(),
                    "hash": current_hash,
                    "width": FRAME_WIDTH,
                    "height": FRAME_HEIGHT,
                }
                line = (json.dumps(payload) + "\n").encode("utf-8")
                tls_sock.sendall(line)

                if seq % 30 == 0:
                    logger.info(
                        "Streamed frame seq=%d (%d bytes) hash=%s...",
                        seq,
                        len(frame_bytes),
                        current_hash[:12],
                    )
                seq += 1

                elapsed = time.monotonic() - t_start
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)

        except Exception as exc:
            logger.warning("Bridge loop interrupted (%s); restarting in 3s...", exc)
            time.sleep(3.0)
        finally:
            if cap is not None:
                cap.release()
            if tls_sock is not None:
                try:
                    tls_sock.close()
                except Exception:
                    pass


if __name__ == "__main__":
    run_bridge()
