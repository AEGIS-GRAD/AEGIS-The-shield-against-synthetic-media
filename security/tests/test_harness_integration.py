import os
import sys
import ssl
import csv
import json
import time
import socket
import asyncio
import hashlib
import threading
import subprocess
import cv2

# Add paths for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

HOST = '127.0.0.1'
PORT = 8443

def run_server():
    server_script = os.path.join(os.path.dirname(__file__), '..', 'gateway', 'ingestion', 'server.py')
    return subprocess.Popen([sys.executable, server_script])

def read_clean_hashes(scenario_dir):
    """
    Simulates the true camera hardware. The camera hardware always signs the
    true, un-tampered frames. We generate the 'true' hashes from the clean reference stream.
    """
    reference_path = os.path.join(os.path.dirname(scenario_dir), 'clean', 'stream.mkv')
    cap = cv2.VideoCapture(reference_path)
    current_hash = hashlib.sha256(b"AEGIS_GENESIS").hexdigest()
    hashes = []
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        
        hasher = hashlib.sha256()
        hasher.update(current_hash.encode('utf-8'))
        hasher.update(frame.tobytes())
        current_hash = hasher.hexdigest()
        hashes.append(current_hash)
        
    cap.release()
    return hashes

def stream_scenario(scenario_name, index_row, context, clean_hashes):
    print(f"\n[SCENARIO] {scenario_name}")
    print(f"  -> Description: {index_row['description']}")
    
    scenario_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'eval', 'fixtures', 'tampered_streams', scenario_name)
    stream_path = os.path.join(scenario_dir, 'stream.mkv')
    manifest_path = os.path.join(scenario_dir, 'manifest.csv')
    
    # Read manifest for sequence numbers and timestamps
    manifest = []
    with open(manifest_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            manifest.append(row)
            
    cap = cv2.VideoCapture(stream_path)
    
    # Connect
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        conn = context.wrap_socket(sock, server_hostname=HOST)
        conn.connect((HOST, PORT))
    except Exception as e:
        print(f"  [ERROR] Could not connect: {e}")
        return False

    frame_idx = 0
    connection_severed = False
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        if frame_idx >= len(manifest):
            break
            
        row = manifest[frame_idx]
        seq = int(row['sequence_number'])
        ts = int(row['timestamp_ms'])
        
        # The attached hash is the TRUE camera hash.
        # If the frame was tampered, the frame data won't match this hash on the server.
        expected_hash = clean_hashes[frame_idx]
        
        payload = {
            "sequence_number": seq,
            "timestamp_ms": ts,
            "frame_data": frame.tobytes().hex(),
            "hash": expected_hash
        }
        
        try:
            conn.sendall((json.dumps(payload) + "\n").encode('utf-8'))
            
            # Check if server severed connection
            try:
                # Non-blocking check
                conn.setblocking(False)
                data = conn.recv(1024)
                if data == b'':
                    connection_severed = True
                    break
                conn.setblocking(True)
            except (BlockingIOError, ssl.SSLWantReadError):
                conn.setblocking(True)
                pass # Connection still open
                
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            connection_severed = True
            break
            
        frame_idx += 1
        time.sleep(0.01) # Small delay to not overwhelm the loop
        
    cap.release()
    try:
        conn.close()
    except:
        pass
    
    if scenario_name == 'clean':
        if connection_severed:
            print("  [FAIL] Server falsely rejected the clean stream!")
            return False
        else:
            print("  [OK] Server successfully accepted the entire clean stream.")
            return True
    else:
        if connection_severed:
            print(f"  [OK] Server successfully CAUGHT the attack and severed connection at frame {frame_idx}.")
            return True
        else:
            print("  [FAIL] Server FAILED to catch the attack. Connection stayed open.")
            return False

def test_harness_integration():
    print("=========================================================")
    print("  AEGIS LIVE INGESTION GATEWAY vs OFFICIAL ATTACK HARNESS  ")
    print("=========================================================\n")

    print("[SYSTEM] Booting Ingestion Server in background...")
    server_proc = run_server()
    time.sleep(2) 
    
    cert_dir = os.path.join(os.path.dirname(__file__), '..', 'transport', 'certs')
    client_cert = os.path.join(cert_dir, 'client.crt')
    client_key = os.path.join(cert_dir, 'client.key')
    ca_cert = os.path.join(cert_dir, 'ca.crt')

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
    context.load_cert_chain(certfile=client_cert, keyfile=client_key)
    context.check_hostname = False

    index_path = os.path.join(os.path.dirname(__file__), '..', '..', 'eval', 'fixtures', 'tampered_streams', 'index.csv')
    if not os.path.exists(index_path):
        print("[FATAL] Attack fixtures not found. Run eval/scripts/generate_attack_streams.py first.")
        server_proc.kill()
        sys.exit(1)

    print("[SYSTEM] Generating true hardware hashes from clean reference stream...")
    clean_hashes = read_clean_hashes(os.path.join(os.path.dirname(__file__), '..', '..', 'eval', 'fixtures', 'tampered_streams', 'clean'))

    all_passed = True
    with open(index_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            passed = stream_scenario(row['scenario'], row, context, clean_hashes)
            if not passed:
                all_passed = False

    print("\n=========================================================")
    if all_passed:
        print("  ALL HARNESS SCENARIOS SUCCESSFULLY DEFEATED!  ")
    else:
        print("  SOME ATTACKS BYPASSED THE GATEWAY.  ")
    print("=========================================================")
    
    server_proc.kill()
    if not all_passed:
        sys.exit(1)

if __name__ == "__main__":
    test_harness_integration()
