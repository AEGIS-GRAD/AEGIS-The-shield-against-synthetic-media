"""
AEGIS Streaming Ingestion DoS Hardening Tests
Owned by: Cybersecurity Team
Verifies that the live streaming ingestion gateway enforces connection caps,
per-IP quotas, token-bucket frame rate limits, and sheds load gracefully under flood attacks.
"""
import asyncio
import os
import sys
import ssl
import json
import time
import socket
import pytest
import subprocess

# Add root paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from security.gateway.ingestion.server import (
    StreamRateLimiter,
    StreamConnectionManager,
    HOST,
    PORT,
)


# ---------------------------------------------------------------------------
# Test Suite 1: Stream Rate Limiter (Token Bucket)
# ---------------------------------------------------------------------------

def test_stream_rate_limiter_allows_nominal_traffic():
    """Nominal frame traffic within allowable FPS must always pass."""
    limiter = StreamRateLimiter(max_fps=30.0, burst_capacity=10.0)
    for _ in range(5):
        assert limiter.allow_frame() is True


def test_stream_rate_limiter_sheds_frame_flood():
    """A sudden blast of 1,000 frames beyond burst capacity must be shed."""
    burst_cap = 15.0
    limiter = StreamRateLimiter(max_fps=30.0, burst_capacity=burst_cap)
    
    # Consume entire burst
    allowed = 0
    for _ in range(int(burst_cap)):
        if limiter.allow_frame():
            allowed += 1
            
    assert allowed == int(burst_cap)
    
    # Immediate subsequent frames without time elapsed must be denied
    denied_count = 0
    for _ in range(50):
        if not limiter.allow_frame():
            denied_count += 1
            
    assert denied_count > 0, "Rate limiter failed to shed frame flood!"


# ---------------------------------------------------------------------------
# Test Suite 2: Connection Manager Concurrency Caps
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connection_manager_global_cap():
    """Global concurrency ceiling must reject connections exceeding limit."""
    mgr = StreamConnectionManager(max_global_streams=3, max_per_ip=10)
    
    ok1, _ = await mgr.acquire("conn_1", "192.168.1.1")
    ok2, _ = await mgr.acquire("conn_2", "192.168.1.2")
    ok3, _ = await mgr.acquire("conn_3", "192.168.1.3")
    
    assert ok1 and ok2 and ok3
    
    # 4th connection should be shed
    ok4, reason = await mgr.acquire("conn_4", "192.168.1.4")
    assert ok4 is False
    assert "GLOBAL_CAP_EXCEEDED" in reason
    
    # Release one connection and verify recovery
    await mgr.release("conn_1", "192.168.1.1")
    ok5, _ = await mgr.acquire("conn_5", "192.168.1.4")
    assert ok5 is True


@pytest.mark.asyncio
async def test_connection_manager_per_ip_cap():
    """A single rogue IP cannot monopolize stream slots."""
    mgr = StreamConnectionManager(max_global_streams=20, max_per_ip=2)
    
    ok1, _ = await mgr.acquire("stream_1", "10.0.0.99")
    ok2, _ = await mgr.acquire("stream_2", "10.0.0.99")
    assert ok1 and ok2
    
    # 3rd connection from the same IP must be rejected
    ok3, reason = await mgr.acquire("stream_3", "10.0.0.99")
    assert ok3 is False
    assert "PER_IP_CAP_EXCEEDED" in reason
    
    # Different IP can still connect
    ok_other, _ = await mgr.acquire("stream_x", "10.0.0.100")
    assert ok_other is True


# ---------------------------------------------------------------------------
# Test Suite 3: Live Ingestion Server Load Shedding & Resilience
# ---------------------------------------------------------------------------

def test_live_server_flood_load_shedding():
    """
    Spawns live ingestion server with a low cap and simulates a connection flood.
    Verifies that excess streams are shed cleanly and server remains healthy.
    """
    env = os.environ.copy()
    env["AEGIS_MAX_CONCURRENT_STREAMS"] = "2"
    env["AEGIS_MAX_STREAMS_PER_IP"] = "5"
    
    server_script = os.path.join(os.path.dirname(__file__), '..', 'gateway', 'ingestion', 'server.py')
    server_proc = subprocess.Popen([sys.executable, server_script], env=env)
    time.sleep(2) # Give server time to bind
    
    cert_dir = os.path.join(os.path.dirname(__file__), '..', 'transport', 'certs')
    client_cert = os.path.join(cert_dir, 'client.crt')
    client_key = os.path.join(cert_dir, 'client.key')
    ca_cert = os.path.join(cert_dir, 'ca.crt')

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
    context.load_cert_chain(certfile=client_cert, keyfile=client_key)
    context.check_hostname = False

    active_sockets = []
    rejections = 0
    total_connections_attempted = 4

    try:
        for i in range(total_connections_attempted):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            conn = context.wrap_socket(sock, server_hostname=HOST)
            try:
                conn.connect((HOST, PORT))
                time.sleep(0.15)  # Allow server callback to process acquire()
                # Check if server accepted or immediately sent rejection / closed
                conn.setblocking(False)
                try:
                    data = conn.recv(1024)
                    if b"GLOBAL_CAP_EXCEEDED" in data or data == b'':
                        rejections += 1
                        conn.close()
                    else:
                        conn.setblocking(True)
                        active_sockets.append(conn)
                except (BlockingIOError, ssl.SSLWantReadError):
                    # No rejection data sent; socket remains open and accepted
                    conn.setblocking(True)
                    active_sockets.append(conn)
            except Exception:
                rejections += 1

        print(f"\n[FLOOD TEST] Active streams accepted: {len(active_sockets)}")
        print(f"[FLOOD TEST] Streams shed gracefully: {rejections}")
        
        # Max concurrent was set to 2, so at least 2 out of 4 must be shed
        assert len(active_sockets) <= 2, f"Server accepted {len(active_sockets)} connections (cap was 2)!"
        assert rejections >= 2, f"Server failed to shed excess load! Rejections: {rejections}"
        print("  [OK] Server enforced connection cap and shed excess flood load!")

    finally:
        for s in active_sockets:
            try:
                s.close()
            except Exception:
                pass
        server_proc.kill()
