import os
import sys
import ssl
import json
import time
import socket
import asyncio
import hashlib
import threading
import subprocess

# Add paths for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

HOST = '127.0.0.1'
PORT = 8443

def run_server():
    server_script = os.path.join(os.path.dirname(__file__), '..', 'gateway', 'ingestion', 'server.py')
    return subprocess.Popen([sys.executable, server_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def test_live_ingestion():
    print("=========================================================")
    print("  AEGIS LIVE INGESTION GATEWAY E2E TEST (Tasks 1 & 3)  ")
    print("=========================================================\n")

    print("[SYSTEM] Booting Ingestion Server in background...")
    server_proc = run_server()
    time.sleep(2) # Wait for server to bind port
    
    cert_dir = os.path.join(os.path.dirname(__file__), '..', 'transport', 'certs')
    client_cert = os.path.join(cert_dir, 'client.crt')
    client_key = os.path.join(cert_dir, 'client.key')
    ca_cert = os.path.join(cert_dir, 'ca.crt')

    context_valid = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
    context_valid.load_cert_chain(certfile=client_cert, keyfile=client_key)
    context_valid.check_hostname = False

    # Create a rogue context (no client cert)
    context_rogue = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
    context_rogue.check_hostname = False

    print("\n[TEST 1] Task 3: Attempting UNAUTHENTICATED (Rogue) Connection...")
    try:
        sock_rogue = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn_rogue = context_rogue.wrap_socket(sock_rogue, server_hostname=HOST)
        conn_rogue.connect((HOST, PORT))
        conn_rogue.sendall(b"TEST")
        data = conn_rogue.recv(1024)
        if not data:
            print("  [OK] Server closed the connection immediately (mTLS enforcement).")
        else:
            print("  [FATAL] Server accepted an unauthenticated connection! Defenses failed.")
            server_proc.kill()
            sys.exit(1)
    except ssl.SSLError as e:
        print("  [OK] Server instantly REJECTED unauthenticated connection via mTLS!")
    except Exception as e:
        print(f"  [OK] Connection blocked: {e}")

    print("\n[TEST 2] Task 3: Connecting Camera to Ingestion Server via mTLS...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn = context_valid.wrap_socket(sock, server_hostname=HOST)
        conn.connect((HOST, PORT))
        print("  [OK] Secure connection established! Server accepted our certificate.")
    except Exception as e:
        print(f"  [FATAL] Failed to connect: {e}")
        server_proc.kill()
        sys.exit(1)

    print("\n[TEST 3] Task 1: Sending Valid Stream Frames...")
    genesis_hash = hashlib.sha256(b"AEGIS_GENESIS").hexdigest()
    
    frame_1_bytes = b"Frame_1_Data"
    h1 = hashlib.sha256()
    h1.update(genesis_hash.encode('utf-8'))
    h1.update(frame_1_bytes)
    hash_1 = h1.hexdigest()

    payload_1 = {
        "sequence_number": 1,
        "timestamp_ms": 33,
        "frame_data": frame_1_bytes.hex(),
        "hash": hash_1
    }
    
    try:
        conn.sendall((json.dumps(payload_1) + "\n").encode('utf-8'))
        print("  [OK] Sent Frame 1 successfully.")
        time.sleep(0.5)
    except Exception as e:
        print(f"  [FATAL] Failed to send frame: {e}")

    print("\n[TEST 4] Task 1: Simulating Splicing Attack (Hash Mismatch)...")
    payload_2 = {
        "sequence_number": 2,
        "timestamp_ms": 66,
        "frame_data": b"DEEPFAKE_FRAME_DATA".hex(),
        "hash": "fake_hash_string"
    }

    conn.sendall((json.dumps(payload_2) + "\n").encode('utf-8'))
    print("  [>] Sent Malicious Frame 2.")
    time.sleep(1) 

    print("\n[TEST 5] Task 1: Validating Server Incident Response...")
    conn.settimeout(2.0)
    try:
        data = conn.recv(1024)
        if data == b'':
            print("  [OK] Server instantly SEVERED the TCP connection after catching the attack!")
        else:
            print("  [FATAL] Server did not sever the connection (received data or stayed open)!")
            server_proc.kill()
            sys.exit(1)
    except socket.timeout:
        print("  [FATAL] Server allowed transmission after an attack! The defenses failed (connection stayed open).")
        server_proc.kill()
        sys.exit(1)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        print("  [OK] Server instantly SEVERED the TCP connection after catching the attack!")

    print("\n=========================================================")
    print("  ALL INGESTION GATEWAY TESTS PASSED.  ")
    print("=========================================================")
    
    server_proc.kill()

if __name__ == "__main__":
    test_live_ingestion()
