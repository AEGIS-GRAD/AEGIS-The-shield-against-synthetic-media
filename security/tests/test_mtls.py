import subprocess
import time
import os
import sys
import pytest


def test_mtls_handshake():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    server_script = os.path.join(base_dir, 'transport', 'mtls_server.py')
    client_script = os.path.join(base_dir, 'transport', 'mtls_client.py')

    print("Starting mTLS Server in background...")
    server_proc = subprocess.Popen([sys.executable, server_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    try:
        # Give server time to bind
        time.sleep(2)

        print("\n--- TEST 1: Authentic Camera (With Certificate) ---")
        client_proc = subprocess.run([sys.executable, client_script], capture_output=True, text=True)
        print(client_proc.stdout)
        assert client_proc.returncode == 0, f"Authentic camera failed: {client_proc.stderr}"

        print("\n--- TEST 2: Rogue Hacker (No Certificate) ---")
        rogue_proc = subprocess.run([sys.executable, client_script, "--rogue"], capture_output=True, text=True)
        print(rogue_proc.stdout)
        # Rogue client must fail or have connection closed/severed by server
        out_lower = (rogue_proc.stdout + rogue_proc.stderr).lower()
        assert rogue_proc.returncode != 0 or any(kw in out_lower for kw in ["error", "closed", "fail", "reject", "denied", "reset"])

    finally:
        server_proc.terminate()
        try:
            server_proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            server_proc.kill()


if __name__ == "__main__":
    test_mtls_handshake()
