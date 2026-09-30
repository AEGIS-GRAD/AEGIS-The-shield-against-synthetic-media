import subprocess
import time
import os
import sys

# Paths
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
server_script = os.path.join(base_dir, 'transport', 'mtls_server.py')
client_script = os.path.join(base_dir, 'transport', 'mtls_client.py')

print("Starting mTLS Server in background...")
server_proc = subprocess.Popen([sys.executable, server_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

# Give server time to bind
time.sleep(2)

print("\n--- TEST 1: Authentic Camera (With Certificate) ---")
client_proc = subprocess.run([sys.executable, client_script], capture_output=True, text=True)
print(client_proc.stdout)
if client_proc.stderr:
    print("STDERR:", client_proc.stderr)

print("\n--- TEST 2: Rogue Hacker (No Certificate) ---")
rogue_proc = subprocess.run([sys.executable, client_script, "--rogue"], capture_output=True, text=True)
print(rogue_proc.stdout)
if rogue_proc.stderr:
    print("STDERR:", rogue_proc.stderr)

print("\nShutting down server...")
server_proc.terminate()
try:
    server_out, server_err = server_proc.communicate(timeout=2)
    print("\n--- SERVER LOGS ---")
    print(server_out)
    if server_err:
        print("SERVER STDERR:", server_err)
except subprocess.TimeoutExpired:
    server_proc.kill()
