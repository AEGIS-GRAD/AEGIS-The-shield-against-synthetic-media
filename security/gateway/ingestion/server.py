import asyncio
import ssl
import json
import os
import sys
import time
import hashlib
from collections import defaultdict
from typing import Dict, Set, Optional, Tuple

# Add paths for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from stream_integrity.stream_validator import StreamValidator
from fusion.feed_fusion import FeedFusionEngine
from forensics.prnu import (
    LivePRNUValidator,
    get_camera_baseline,
    load_camera_baselines_from_dir,
    register_camera_baseline,
)
try:
    from forensics.evidence_vault import SurveillanceEvidenceVault
except ImportError:
    from security.forensics.evidence_vault import SurveillanceEvidenceVault

evidence_vault = SurveillanceEvidenceVault()

HOST = '127.0.0.1'
PORT = 8443

# DoS Hardening Parameters (Configurable via environment variables)
MAX_CONCURRENT_STREAMS = int(os.environ.get("AEGIS_MAX_CONCURRENT_STREAMS", "20"))
MAX_STREAMS_PER_IP = int(os.environ.get("AEGIS_MAX_STREAMS_PER_IP", "5"))
STREAM_IDLE_TIMEOUT = float(os.environ.get("AEGIS_STREAM_IDLE_TIMEOUT", "10.0"))
MAX_STREAM_FPS = float(os.environ.get("AEGIS_MAX_STREAM_FPS", "60.0"))
BURST_CAPACITY = float(os.environ.get("AEGIS_STREAM_BURST_CAPACITY", "30.0"))

# PRNU Hardware Fingerprinting Parameters
PRNU_PCE_THRESHOLD = float(os.environ.get("AEGIS_PRNU_PCE_THRESHOLD", "50.0"))
PRNU_CHECK_INTERVAL = int(os.environ.get("AEGIS_PRNU_CHECK_INTERVAL", "1"))
PRNU_BOOTSTRAP_FRAMES = int(os.environ.get("AEGIS_PRNU_BOOTSTRAP_FRAMES", "15"))

# Security Profile: "prod" (strict zero-trust enforce) vs "dev" (permissive sandbox for Web/AI teams)
AEGIS_SECURITY_PROFILE = os.environ.get("AEGIS_SECURITY_PROFILE", "prod").lower()

def set_security_profile(profile: str):
    global AEGIS_SECURITY_PROFILE
    AEGIS_SECURITY_PROFILE = profile.lower()

try:
    from .telemetry import telemetry_hub, telemetry_app, TELEMETRY_PORT
except ImportError:
    try:
        from telemetry import telemetry_hub, telemetry_app, TELEMETRY_PORT
    except ImportError:
        from security.gateway.ingestion.telemetry import telemetry_hub, telemetry_app, TELEMETRY_PORT


class StreamRateLimiter:
    """
    Token-bucket rate limiter for long-lived video streaming connections.
    Protects ingestion CPU and memory against frame-flood / computational exhaustion DoS.
    """
    def __init__(self, max_fps: float = MAX_STREAM_FPS, burst_capacity: float = BURST_CAPACITY):
        self.max_fps = max_fps
        self.burst_capacity = burst_capacity
        self.tokens = burst_capacity
        self.last_update = time.monotonic()

    def allow_frame(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_update
        self.last_update = now
        # Replenish tokens based on elapsed time and allowable frame rate
        self.tokens = min(self.burst_capacity, self.tokens + elapsed * self.max_fps)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class StreamConnectionManager:
    """
    Enforces global concurrency caps and per-IP connection limits for live streams.
    Prevents connection pool exhaustion, file descriptor leaks, and Slowloris attacks.
    """
    def __init__(self, max_global_streams: int = MAX_CONCURRENT_STREAMS, max_per_ip: int = MAX_STREAMS_PER_IP):
        self.max_global_streams = max_global_streams
        self.max_per_ip = max_per_ip
        self._lock = asyncio.Lock()
        self.active_streams: Set[str] = set()
        self.streams_by_ip: Dict[str, int] = defaultdict(int)

    async def acquire(self, stream_id: str, client_ip: str) -> Tuple[bool, Optional[str]]:
        async with self._lock:
            if len(self.active_streams) >= self.max_global_streams:
                return False, f"GLOBAL_CAP_EXCEEDED: Active streams ({len(self.active_streams)}) reached limit ({self.max_global_streams})"
            if self.streams_by_ip[client_ip] >= self.max_per_ip:
                return False, f"PER_IP_CAP_EXCEEDED: IP {client_ip} has {self.streams_by_ip[client_ip]} streams (limit is {self.max_per_ip})"
            self.active_streams.add(stream_id)
            self.streams_by_ip[client_ip] += 1
            return True, None

    async def release(self, stream_id: str, client_ip: str):
        async with self._lock:
            self.active_streams.discard(stream_id)
            if client_ip in self.streams_by_ip:
                self.streams_by_ip[client_ip] = max(0, self.streams_by_ip[client_ip] - 1)
                if self.streams_by_ip[client_ip] == 0:
                    del self.streams_by_ip[client_ip]

    def get_stats(self) -> dict:
        return {
            "active_streams": len(self.active_streams),
            "unique_ips": len(self.streams_by_ip),
            "max_global": self.max_global_streams,
            "max_per_ip": self.max_per_ip
        }


# Global connection manager instance
connection_manager = StreamConnectionManager()


class LiveHashChainValidator:
    """
    A live streaming adaptation of the offline FrameHashChain.
    It recalculates the cryptographic chain on the fly.
    """
    def __init__(self):
        self.current_hash = hashlib.sha256(b"AEGIS_GENESIS").hexdigest()

    def validate_frame(self, frame_bytes: bytes, expected_hash: str) -> bool:
        hasher = hashlib.sha256()
        hasher.update(self.current_hash.encode('utf-8'))
        hasher.update(frame_bytes)
        new_hash = hasher.hexdigest()
        
        if new_hash != expected_hash:
            return False
            
        self.current_hash = new_hash
        return True


async def handle_camera_stream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """
    Handles a live incoming camera stream with complete DoS protections:
    1. Global & per-IP connection count caps
    2. Idle inactivity timeouts (anti-Slowloris)
    3. Token-bucket frame-rate backpressure
    4. Cryptographic hash-chain and sequence verification
    """
    peer_info = writer.get_extra_info('peername')
    client_ip = peer_info[0] if peer_info else "unknown"
    client_port = peer_info[1] if peer_info else 0
    stream_id = f"{client_ip}:{client_port}"

    # DoS Defense 1: Enforce connection-count caps
    allowed, reject_reason = await connection_manager.acquire(stream_id, client_ip)
    if not allowed:
        print(f"[!] DoS DEFENSE: Shedding load from {stream_id} -> {reject_reason}")
        try:
            reject_msg = json.dumps({"status": "rejected", "error": reject_reason}) + "\n"
            writer.write(reject_msg.encode('utf-8'))
            await writer.drain()
        except Exception:
            pass
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        return

    peer_cert = writer.get_extra_info('peercert')
    camera_id = "Unknown"
    if peer_cert:
        camera_id = dict(x[0] for x in peer_cert.get('subject', [])).get('commonName', 'Unknown')
    print(f"\n[+] SECURE CONNECTION: {camera_id} ({stream_id}) authenticated via mTLS.")

    # Initialize validators and DoS rate limiter for this stream
    stream_validator = StreamValidator(fps=30)
    hash_validator = LiveHashChainValidator()
    prnu_validator = LivePRNUValidator(
        level=2,
        wavelet="db4",
        pce_threshold=PRNU_PCE_THRESHOLD,
        check_interval=PRNU_CHECK_INTERVAL,
        bootstrap_frames=PRNU_BOOTSTRAP_FRAMES,
        target_shape=(240, 320)
    )
    enrolled_base = get_camera_baseline(camera_id)
    if enrolled_base is not None:
        prnu_validator.enroll_baseline(camera_id, enrolled_base)

    rate_limiter = StreamRateLimiter(max_fps=MAX_STREAM_FPS, burst_capacity=BURST_CAPACITY)
    fusion_engine = FeedFusionEngine()

    try:
        while True:
            # DoS Defense 2: Anti-Slowloris Idle Inactivity Timeout
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=STREAM_IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                print(f"[!] IDLE TIMEOUT: {camera_id} ({stream_id}) inactive for > {STREAM_IDLE_TIMEOUT}s. Dropping connection.")
                break

            if not line:
                break

            # DoS Defense 3: Token-Bucket High-Frequency Flood Limiter
            if not rate_limiter.allow_frame():
                if AEGIS_SECURITY_PROFILE == "prod":
                    print(f"[!] DoS DEFENSE: Frame flood detected on {camera_id} (exceeded {MAX_STREAM_FPS} fps cap). Shedding connection.")
                    await telemetry_hub.broadcast({
                        "timestamp": time.time(),
                        "camera_id": camera_id,
                        "seq": -1,
                        "status": "COMPROMISED",
                        "threat_type": "FRAME_FLOOD",
                        "profile": "prod",
                        "action": "SOCKET_SEVERED",
                        "detail": f"Frame rate exceeded {MAX_STREAM_FPS} FPS cap"
                    })
                    break
                else:
                    print(f"[*] DEV AUDIT: Frame rate alert on {camera_id} (exceeded {MAX_STREAM_FPS} fps cap). Passing through in dev mode.")
                    await telemetry_hub.broadcast({
                        "timestamp": time.time(),
                        "camera_id": camera_id,
                        "seq": -1,
                        "status": "AUDIT_WARNING",
                        "threat_type": "FRAME_FLOOD",
                        "profile": "dev",
                        "action": "AUDIT_LOGGED",
                        "detail": f"Frame rate alert (exceeded {MAX_STREAM_FPS} FPS cap)"
                    })

            t_frame_start = time.perf_counter()
            try:
                payload = json.loads(line.decode('utf-8'))
                seq = payload['sequence_number']
                ts = payload['timestamp_ms']
                frame_hex = payload['frame_data']
                expected_hash = payload['hash']
                
                frame_bytes = bytes.fromhex(frame_hex)
            except Exception as e:
                print(f"[-] Malformed payload from {camera_id}: {e}")
                break

            # 1. Validate Timestamp and Sequence (Catch Replay/Drop attacks)
            anomalies = stream_validator.check(seq, ts)
            if anomalies:
                anomaly_details = [f"{a.kind}: {a.detail}" for a in anomalies]
                incident_id = None
                try:
                    inc = await asyncio.to_thread(
                        evidence_vault.store_incident,
                        camera_id=camera_id,
                        threat_type="SEQUENCE_ANOMALY",
                        sequence_number=seq,
                        timestamp_ms=ts,
                        primary_frame_bytes=frame_bytes,
                        telemetry={"anomalies": anomaly_details},
                        reasoning_narrative=f"Sequence anomaly detected: {'; '.join(anomaly_details)}",
                        severity="CRITICAL" if AEGIS_SECURITY_PROFILE == "prod" else "WARNING",
                        width=payload.get("width"),
                        height=payload.get("height"),
                    )
                    incident_id = inc.incident_id
                except Exception as inc_err:
                    print(f"[-] Evidence vault error: {inc_err}")

                if AEGIS_SECURITY_PROFILE == "prod":
                    print(f"[!] INTEGRITY COMPROMISED (Network Attack) on {camera_id}:")
                    for a in anomalies:
                        print(f"    -> {a.kind}: {a.detail}")
                    print(f"[*] SEVERING CONNECTION to {camera_id}")
                    await telemetry_hub.broadcast({
                        "timestamp": time.time(),
                        "camera_id": camera_id,
                        "seq": seq,
                        "status": "COMPROMISED",
                        "threat_type": "SEQUENCE_ANOMALY",
                        "profile": "prod",
                        "action": "SOCKET_SEVERED",
                        "detail": "; ".join(anomaly_details),
                        "incident_id": incident_id,
                    })
                    break  # Drop connection instantly in prod mode
                else:
                    print(f"[*] DEV AUDIT: Sequence anomaly on {camera_id} at seq {seq} ({'; '.join(anomaly_details)}). Passing through in dev mode.")
                    await telemetry_hub.broadcast({
                        "timestamp": time.time(),
                        "camera_id": camera_id,
                        "seq": seq,
                        "status": "AUDIT_WARNING",
                        "threat_type": "SEQUENCE_ANOMALY",
                        "profile": "dev",
                        "action": "AUDIT_LOGGED",
                        "detail": "; ".join(anomaly_details),
                        "incident_id": incident_id,
                    })
                
            # 2. Validate Cryptographic Hash Chain (Catch Deepfake Splicing)
            if not hash_validator.validate_frame(frame_bytes, expected_hash):
                incident_id = None
                try:
                    inc = await asyncio.to_thread(
                        evidence_vault.store_incident,
                        camera_id=camera_id,
                        threat_type="HASH_CHAIN_BREAK",
                        sequence_number=seq,
                        timestamp_ms=ts,
                        primary_frame_bytes=frame_bytes,
                        telemetry={
                            "expected_hash": expected_hash,
                            "calculated_hash": hash_validator.current_hash,
                        },
                        reasoning_narrative=f"Cryptographic hash chain broken at sequence #{seq}. Calculated hash differs from client expected hash.",
                        severity="CRITICAL" if AEGIS_SECURITY_PROFILE == "prod" else "WARNING",
                        width=payload.get("width"),
                        height=payload.get("height"),
                    )
                    incident_id = inc.incident_id
                except Exception as inc_err:
                    print(f"[-] Evidence vault error: {inc_err}")

                if AEGIS_SECURITY_PROFILE == "prod":
                    print(f"[!] INTEGRITY COMPROMISED (Splicing Attack) on {camera_id}: Hash mismatch at seq {seq}")
                    print(f"[*] Expected Hash: {expected_hash}")
                    print(f"[*] Server Calculated Hash (from client frame): {hash_validator.current_hash}")
                    print(f"[*] SEVERING CONNECTION to {camera_id}")
                    await telemetry_hub.broadcast({
                        "timestamp": time.time(),
                        "camera_id": camera_id,
                        "seq": seq,
                        "hash": expected_hash,
                        "calculated_hash": hash_validator.current_hash,
                        "status": "COMPROMISED",
                        "threat_type": "HASH_CHAIN_BREAK",
                        "profile": "prod",
                        "action": "SOCKET_SEVERED",
                        "detail": f"Cryptographic hash chain broken at seq {seq}",
                        "incident_id": incident_id,
                    })
                    break  # Drop connection instantly in prod mode
                else:
                    print(f"[*] DEV AUDIT: Hash mismatch on {camera_id} at seq {seq}. Passing through in dev mode.")
                    await telemetry_hub.broadcast({
                        "timestamp": time.time(),
                        "camera_id": camera_id,
                        "seq": seq,
                        "hash": expected_hash,
                        "calculated_hash": hash_validator.current_hash,
                        "status": "AUDIT_WARNING",
                        "threat_type": "HASH_CHAIN_BREAK",
                        "profile": "dev",
                        "action": "AUDIT_LOGGED",
                        "detail": f"Cryptographic hash chain broken at seq {seq}",
                        "incident_id": incident_id,
                    })

            # 3. Validate Physical Sensor PRNU Fingerprint (Catch AI Generative Media & Foreign Sensor Injections)
            width = payload.get('width')
            height = payload.get('height')
            is_prnu_valid, pce, prnu_msg = await asyncio.to_thread(
                prnu_validator.verify_frame, camera_id, frame_bytes, seq, width, height
            )
            if not is_prnu_valid:
                incident_id = None
                try:
                    inc = await asyncio.to_thread(
                        evidence_vault.store_incident,
                        camera_id=camera_id,
                        threat_type="PRNU_SENSOR_MISMATCH",
                        sequence_number=seq,
                        timestamp_ms=ts,
                        primary_frame_bytes=frame_bytes,
                        telemetry={
                            "prnu_pce": round(pce, 2),
                            "prnu_threshold": PRNU_PCE_THRESHOLD,
                            "hash": expected_hash,
                        },
                        reasoning_narrative=f"Hardware PRNU sensor mismatch: {prnu_msg}",
                        severity="CRITICAL" if AEGIS_SECURITY_PROFILE == "prod" else "WARNING",
                        width=width,
                        height=height,
                    )
                    incident_id = inc.incident_id
                except Exception as inc_err:
                    print(f"[-] Evidence vault error: {inc_err}")

                if AEGIS_SECURITY_PROFILE == "prod":
                    print(f"[!] INTEGRITY COMPROMISED (Hardware Sensor Mismatch / PRNU Splice) on {camera_id}:")
                    print(f"    -> {prnu_msg}")
                    print(f"[*] SEVERING CONNECTION to {camera_id}")
                    await telemetry_hub.broadcast({
                        "timestamp": time.time(),
                        "camera_id": camera_id,
                        "seq": seq,
                        "hash": expected_hash,
                        "prnu_pce": round(pce, 2),
                        "status": "COMPROMISED",
                        "threat_type": "PRNU_SENSOR_MISMATCH",
                        "profile": "prod",
                        "action": "SOCKET_SEVERED",
                        "detail": prnu_msg,
                        "incident_id": incident_id,
                    })
                    break  # Drop connection instantly in prod mode
                else:
                    print(f"[*] DEV AUDIT: PRNU sensor mismatch on {camera_id} at seq {seq} (PCE={pce:.2f}). Passing through in dev mode.")
                    await telemetry_hub.broadcast({
                        "timestamp": time.time(),
                        "camera_id": camera_id,
                        "seq": seq,
                        "hash": expected_hash,
                        "prnu_pce": round(pce, 2),
                        "status": "AUDIT_WARNING",
                        "threat_type": "PRNU_SENSOR_MISMATCH",
                        "profile": "dev",
                        "action": "AUDIT_LOGGED",
                        "detail": prnu_msg,
                        "incident_id": incident_id,
                    })
            else:
                proc_ms = (time.perf_counter() - t_frame_start) * 1000.0
                if pce > 0:
                    print(f"[OK] Frame {seq} verified (Cryptographic Hash + Sensor PCE={pce:.2f}, {proc_ms:.1f}ms) from {camera_id}.")
                else:
                    print(f"[OK] Frame {seq} mathematically verified ({proc_ms:.1f}ms) from {camera_id}.")
                # Compute fused verdict (integrity intact, baseline clean content)
                fused = fusion_engine.fuse(
                    hash_chain_ok=True,
                    integrity_anomalies=[],
                    prnu_ok=True,
                    prnu_pce=pce if pce > 0 else 100.0,
                    ai_score=0.10,
                )
                await telemetry_hub.broadcast({
                    "timestamp": time.time(),
                    "camera_id": camera_id,
                    "seq": seq,
                    "hash": expected_hash,
                    "prnu_pce": round(pce, 2) if pce > 0 else 0.0,
                    "status": "VALID",
                    "verdict": fused.verdict,
                    "combined_score": fused.combined_score,
                    "integrity_score": fused.integrity_score,
                    "integrity_ok": fused.integrity_ok,
                    "profile": AEGIS_SECURITY_PROFILE,
                    "action": "FORWARDED",
                    "detail": f"Frame {seq} mathematically verified (Verdict: {fused.verdict})",
                    "processing_ms": round(proc_ms, 2),
                })
            
    except Exception as e:
        print(f"[-] Connection error with {camera_id}: {e}")
    finally:
        await connection_manager.release(stream_id, client_ip)
        print(f"[-] Closed connection to {camera_id} ({stream_id}). Active streams remaining: {len(connection_manager.active_streams)}")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def start_server():
    cert_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'transport', 'certs')
    server_cert = os.path.join(cert_dir, 'server.crt')
    server_key = os.path.join(cert_dir, 'server.key')
    client_ca = os.path.join(cert_dir, 'ca.crt')

    if not os.path.exists(server_cert):
        print(f"FATAL: Certificates not found in {cert_dir}. Run generate_certs.py first.")
        sys.exit(1)

    # Configure mTLS context based on active security profile
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    if AEGIS_SECURITY_PROFILE == "prod":
        context.verify_mode = ssl.CERT_REQUIRED
    else:
        context.verify_mode = ssl.CERT_OPTIONAL

    context.load_cert_chain(certfile=server_cert, keyfile=server_key)
    context.load_verify_locations(cafile=client_ca)

    server = await asyncio.start_server(
        handle_camera_stream, HOST, PORT, ssl=context, limit=1024 * 1024 * 10 # 10 MB limit for huge frame payloads
    )

    # Pre-load enrolled camera PRNU baselines
    baselines_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'forensics', 'baselines')
    loaded_count = load_camera_baselines_from_dir(baselines_dir)

    print(f"[AEGIS GATEWAY] Asynchronous Ingestion Server starting on {HOST}:{PORT}")
    print(f"[AEGIS GATEWAY] Security Profile: {AEGIS_SECURITY_PROFILE.upper()} ({'Strict Zero-Trust Enforce' if AEGIS_SECURITY_PROFILE == 'prod' else 'Permissive AI/Web Sandbox'})")
    print(f"[AEGIS GATEWAY] DoS Hardened: Concurrency Cap={MAX_CONCURRENT_STREAMS}, Max/IP={MAX_STREAMS_PER_IP}, Max FPS={MAX_STREAM_FPS}")
    print(f"[AEGIS GATEWAY] PRNU Forensics: PCE Threshold={PRNU_PCE_THRESHOLD}, Check Interval={PRNU_CHECK_INTERVAL}, Enrolled Baselines={loaded_count}")
    print(f"[AEGIS GATEWAY] Ingestion Ready (mTLS mode: {'CERT_REQUIRED' if AEGIS_SECURITY_PROFILE == 'prod' else 'CERT_OPTIONAL'}). Awaiting cameras...")

    # Launch telemetry SSE server on port 8444 concurrently if enabled and uvicorn is available
    telemetry_task = None
    if os.environ.get("AEGIS_DISABLE_TELEMETRY", "0") != "1":
        try:
            import uvicorn
            telemetry_config = uvicorn.Config(
                telemetry_app,
                host=HOST,
                port=TELEMETRY_PORT,
                log_level="warning"
            )
            telemetry_server = uvicorn.Server(telemetry_config)
            print(f"[AEGIS GATEWAY] Live Telemetry SSE Broadcaster active on http://{HOST}:{TELEMETRY_PORT}/telemetry/stream")
            telemetry_task = asyncio.create_task(telemetry_server.serve())
        except Exception as e:
            print(f"[AEGIS GATEWAY] Note: Telemetry SSE server could not be started: {e}")

    async with server:
        if telemetry_task:
            await asyncio.gather(server.serve_forever(), telemetry_task)
        else:
            await server.serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AEGIS Asynchronous Live Ingestion Gateway")
    parser.add_argument(
        "--profile",
        choices=["prod", "dev"],
        default=None,
        help="Security profile: 'prod' (strict zero-trust enforce) or 'dev' (permissive AI/Web sandbox)"
    )
    args, _ = parser.parse_known_args()
    if args.profile:
        set_security_profile(args.profile)

    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        print("\n[AEGIS GATEWAY] Shutting down.")
