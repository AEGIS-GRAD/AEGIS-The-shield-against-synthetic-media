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

HOST = '127.0.0.1'
PORT = 8443

# DoS Hardening Parameters (Configurable via environment variables)
MAX_CONCURRENT_STREAMS = int(os.environ.get("AEGIS_MAX_CONCURRENT_STREAMS", "20"))
MAX_STREAMS_PER_IP = int(os.environ.get("AEGIS_MAX_STREAMS_PER_IP", "5"))
STREAM_IDLE_TIMEOUT = float(os.environ.get("AEGIS_STREAM_IDLE_TIMEOUT", "10.0"))
MAX_STREAM_FPS = float(os.environ.get("AEGIS_MAX_STREAM_FPS", "60.0"))
BURST_CAPACITY = float(os.environ.get("AEGIS_STREAM_BURST_CAPACITY", "30.0"))


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
    rate_limiter = StreamRateLimiter(max_fps=MAX_STREAM_FPS, burst_capacity=BURST_CAPACITY)

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
                print(f"[!] DoS DEFENSE: Frame flood detected on {camera_id} (exceeded {MAX_STREAM_FPS} fps cap). Shedding connection.")
                break
            
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
                print(f"[!] INTEGRITY COMPROMISED (Network Attack) on {camera_id}:")
                for a in anomalies:
                    print(f"    -> {a.kind}: {a.detail}")
                print(f"[*] SEVERING CONNECTION to {camera_id}")
                break # Drop connection instantly
                
            # 2. Validate Cryptographic Hash Chain (Catch Deepfake Splicing)
            if not hash_validator.validate_frame(frame_bytes, expected_hash):
                print(f"[!] INTEGRITY COMPROMISED (Splicing Attack) on {camera_id}: Hash mismatch at seq {seq}")
                print(f"[*] Expected Hash: {expected_hash}")
                print(f"[*] Server Calculated Hash (from client frame): {hash_validator.current_hash}")
                print(f"[*] SEVERING CONNECTION to {camera_id}")
                break # Drop connection instantly
                
            print(f"[OK] Frame {seq} mathematically verified from {camera_id}.")
            
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

    # Configure zero-trust mTLS context
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(certfile=server_cert, keyfile=server_key)
    context.load_verify_locations(cafile=client_ca)

    server = await asyncio.start_server(
        handle_camera_stream, HOST, PORT, ssl=context, limit=1024 * 1024 * 10 # 10 MB limit for huge frame payloads
    )

    print(f"[AEGIS GATEWAY] Asynchronous Ingestion Server starting on {HOST}:{PORT}")
    print(f"[AEGIS GATEWAY] DoS Hardened: Concurrency Cap={MAX_CONCURRENT_STREAMS}, Max/IP={MAX_STREAMS_PER_IP}, Max FPS={MAX_STREAM_FPS}")
    print("[AEGIS GATEWAY] Enforcing SSL.CERT_REQUIRED (mTLS). Awaiting cameras...")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        print("\n[AEGIS GATEWAY] Shutting down.")
