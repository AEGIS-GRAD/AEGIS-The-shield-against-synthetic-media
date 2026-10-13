import os
import sys
import ssl
import json
import time
import socket
import hashlib
import subprocess
import pytest
import cv2
import numpy as np

from security.forensics.prnu import (
    PRNUExtractor,
    LivePRNUValidator,
    register_camera_baseline,
    get_camera_baseline
)

HOST = '127.0.0.1'
PORT = 8443


@pytest.fixture
def prnu_extractor():
    return PRNUExtractor(level=2, wavelet="db4")


def test_prnu_pce_correlation(prnu_extractor):
    """
    Test that the Peak-to-Correlation Energy (PCE) correctly matches
    a frame to its camera baseline, and rejects frames from other cameras.
    """
    # 1. Simulate Camera A's authentic hardware fingerprint (baseline)
    np.random.seed(42)
    camera_a_baseline = np.random.normal(0, 5, (256, 256)).astype(np.float32)

    # Simulate a frame taken from Camera A (baseline + some temporary thermal noise)
    frame_a_residual = camera_a_baseline + np.random.normal(0, 10, (256, 256)).astype(np.float32)

    # 2. Simulate Camera B's hardware fingerprint
    np.random.seed(99)
    camera_b_baseline = np.random.normal(0, 5, (256, 256)).astype(np.float32)

    # 3. Test Authentic Match (Camera A frame vs Camera A baseline)
    pce_authentic = prnu_extractor.compute_pce(frame_a_residual, camera_a_baseline)
    
    # 4. Test Spoof/Deepfake (Camera A frame vs Camera B baseline)
    pce_spoof = prnu_extractor.compute_pce(frame_a_residual, camera_b_baseline)

    # The authentic match should have a massively higher PCE score than the spoof
    assert pce_authentic > pce_spoof
    assert pce_authentic > 100.0  # Authentic PCE is typically very high
    assert pce_spoof < 50.0       # Spoof PCE is typically very low


def test_live_prnu_validator_enrolled_baseline():
    """Test LivePRNUValidator when an enrolled camera baseline is registered."""
    validator = LivePRNUValidator(level=2, wavelet="db4", pce_threshold=50.0, target_shape=(240, 320))
    
    np.random.seed(101)
    enrolled_base = np.random.normal(0, 4, (240, 320)).astype(np.float32)
    validator.enroll_baseline("cam-enrolled", enrolled_base)
    
    # Authentic frame: image with matching sensor noise
    auth_frame = np.full((240, 320, 3), 128, dtype=np.uint8)
    auth_noise = enrolled_base + np.random.normal(0, 2, (240, 320))
    auth_frame = np.clip(auth_frame.astype(np.float32) + auth_noise[:, :, None], 0, 255).astype(np.uint8)
    
    is_valid, pce, err = validator.verify_frame("cam-enrolled", auth_frame, seq=1)
    assert is_valid is True
    assert pce > 50.0
    assert err is None
    
    # Foreign frame: image with foreign sensor noise
    foreign_base = np.random.normal(0, 4, (240, 320)).astype(np.float32)
    foreign_frame = np.full((240, 320, 3), 128, dtype=np.uint8)
    foreign_frame = np.clip(foreign_frame.astype(np.float32) + foreign_base[:, :, None], 0, 255).astype(np.uint8)
    
    is_valid_f, pce_f, err_f = validator.verify_frame("cam-enrolled", foreign_frame, seq=2)
    assert is_valid_f is False
    assert pce_f < 50.0
    assert "below threshold" in err_f


def test_live_prnu_validator_bootstrap_mode():
    """Test LivePRNUValidator dynamic baseline bootstrapping over first N frames."""
    validator = LivePRNUValidator(level=2, wavelet="db4", bootstrap_frames=5, target_shape=(240, 320))
    
    np.random.seed(202)
    sensor_noise = np.random.normal(0, 4, (240, 320)).astype(np.float32)
    
    # Feed frames 1 to 4: should report BOOTSTRAPPING
    for i in range(1, 5):
        frame = np.full((240, 320, 3), 100 + i * 10, dtype=np.uint8)
        frame = np.clip(frame.astype(np.float32) + sensor_noise[:, :, None], 0, 255).astype(np.uint8)
        ok, score, status = validator.verify_frame("cam-dynamic", frame, seq=i)
        assert ok is True
        assert "BOOTSTRAPPING" in status
        
    # Frame 5: triggers baseline establishment
    frame_5 = np.full((240, 320, 3), 150, dtype=np.uint8)
    frame_5 = np.clip(frame_5.astype(np.float32) + sensor_noise[:, :, None], 0, 255).astype(np.uint8)
    ok_5, score_5, status_5 = validator.verify_frame("cam-dynamic", frame_5, seq=5)
    assert ok_5 is True
    assert status_5 == "BASELINE_ESTABLISHED"
    
    # Frame 6: authentic frame verified against newly established baseline
    frame_6 = np.full((240, 320, 3), 160, dtype=np.uint8)
    frame_6 = np.clip(frame_6.astype(np.float32) + sensor_noise[:, :, None], 0, 255).astype(np.uint8)
    ok_6, pce_6, err_6 = validator.verify_frame("cam-dynamic", frame_6, seq=6)
    assert ok_6 is True
    assert pce_6 > 50.0
    assert err_6 is None


def test_live_prnu_validator_non_image_payload_safety():
    """Verify non-image test payloads (e.g. plain strings) pass safely without crash."""
    validator = LivePRNUValidator()
    ok, score, msg = validator.verify_frame("cam-dummy", b"DUMMY_STRING_PAYLOAD", seq=1)
    assert ok is True
    assert score == -1.0
    assert msg == "NON_IMAGE_PAYLOAD"


def test_live_prnu_validator_sampling_interval():
    """Verify check_interval skips intermediate frames to conserve line-rate CPU."""
    validator = LivePRNUValidator(check_interval=3, target_shape=(240, 320))
    base = np.random.normal(0, 4, (240, 320)).astype(np.float32)
    validator.enroll_baseline("cam-interval", base)
    
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    
    # Frame 1: count=1, 1 % 3 != 0 -> skip
    ok1, score1, msg1 = validator.verify_frame("cam-interval", frame, seq=1)
    assert ok1 is True and msg1 == "INTERVAL_SKIP"
    
    # Frame 2: count=2, 2 % 3 != 0 -> skip
    ok2, score2, msg2 = validator.verify_frame("cam-interval", frame, seq=2)
    assert ok2 is True and msg2 == "INTERVAL_SKIP"
    
    # Frame 3: count=3, 3 % 3 == 0 -> checked
    ok3, score3, msg3 = validator.verify_frame("cam-interval", frame, seq=3)
    assert msg3 != "INTERVAL_SKIP"


def test_continuous_prnu_stream_monitoring_e2e():
    """
    E2E Ingestion Pipeline Test:
    Simulates a live streaming camera where an attacker forges a SHA-256 hash
    chain to perfectly match spliced frames from a foreign camera sensor.
    Verifies that the Ingestion Gateway catches the PRNU sensor mismatch (PCE < 50.0)
    and severs the TCP connection immediately.
    """
    server_script = os.path.join(os.path.dirname(__file__), '..', 'gateway', 'ingestion', 'server.py')
    server_proc = subprocess.Popen([sys.executable, server_script])
    time.sleep(2) # Give server time to bind and preload baselines
    
    cert_dir = os.path.join(os.path.dirname(__file__), '..', 'transport', 'certs')
    client_cert = os.path.join(cert_dir, 'client.crt')
    client_key = os.path.join(cert_dir, 'client.key')
    ca_cert = os.path.join(cert_dir, 'ca.crt')

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
    context.load_cert_chain(certfile=client_cert, keyfile=client_key)
    context.check_hostname = False

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3.0)
    conn = context.wrap_socket(sock, server_hostname=HOST)

    try:
        conn.connect((HOST, PORT))
        
        # Load authentic and spliced frames from fixtures
        fixtures_dir = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'tampered_streams')
        clean_path = os.path.join(fixtures_dir, 'clean', 'stream.mkv')
        splice_path = os.path.join(fixtures_dir, 'prnu_splice', 'stream.mkv')
        
        cap_clean = cv2.VideoCapture(clean_path)
        cap_splice = cv2.VideoCapture(splice_path)
        
        current_hash = hashlib.sha256(b"AEGIS_GENESIS").hexdigest()
        
        # Stream 3 authentic frames: both Hash Chain and PRNU should pass
        for seq in range(1, 4):
            ret, frame = cap_clean.read()
            assert ret, f"Failed to read clean frame {seq}"
            
            frame_bytes = frame.tobytes()
            hasher = hashlib.sha256()
            hasher.update(current_hash.encode('utf-8'))
            hasher.update(frame_bytes)
            current_hash = hasher.hexdigest()
            
            payload = {
                "sequence_number": seq,
                "timestamp_ms": seq * 33,
                "frame_data": frame_bytes.hex(),
                "hash": current_hash,
                "width": 320,
                "height": 240
            }
            conn.sendall((json.dumps(payload) + "\n").encode('utf-8'))
            time.sleep(0.05)
            
        # Frame 4: INJECT FOREIGN SENSOR FRAME (PRNU Splice)
        # We craft a FORGED HASH that matches the spliced frame bytes perfectly
        # If the server only checked hash-chains, this frame would PASS.
        for _ in range(20):
            cap_splice.read()
        ret_s, spliced_frame = cap_splice.read()
        assert ret_s, "Failed to read spliced frame"
        
        spliced_bytes = spliced_frame.tobytes()
        hasher = hashlib.sha256()
        hasher.update(current_hash.encode('utf-8'))
        hasher.update(spliced_bytes)
        forged_matching_hash = hasher.hexdigest()
        
        payload_spliced = {
            "sequence_number": 4,
            "timestamp_ms": 4 * 33,
            "frame_data": spliced_bytes.hex(),
            "hash": forged_matching_hash, # Cryptographically valid for this frame!
            "width": 320,
            "height": 240
        }
        conn.sendall((json.dumps(payload_spliced) + "\n").encode('utf-8'))
        time.sleep(0.5)
        
        # Verify the server severed the connection due to PRNU mismatch
        connection_severed = False
        try:
            data = conn.recv(1024)
            if data == b'':
                connection_severed = True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            connection_severed = True
        except socket.timeout:
            connection_severed = False
            
        assert connection_severed is True, (
            "Server failed to sever connection on foreign sensor PRNU splice!"
        )
        
        cap_clean.release()
        cap_splice.release()
        
    finally:
        try:
            conn.close()
        except Exception:
            pass
        server_proc.kill()

