"""
mTLS Client Prototype (Simulating an Edge Camera)
Owned by: Cyber Team

This client presents its cryptographic identity (certificate) to the server
before streaming video data. If it tries to connect without a valid cert,
the server drops the connection instantly.
"""
import socket
import ssl
import os
import sys
import time

HOST = '127.0.0.1'
PORT = 8443

cert_dir = os.path.join(os.path.dirname(__file__), 'certs')
client_cert = os.path.join(cert_dir, 'client.crt')
client_key = os.path.join(cert_dir, 'client.key')
server_ca = os.path.join(cert_dir, 'ca.crt')

if len(sys.argv) > 1 and sys.argv[1] == "--rogue":
    print("[CAMERA] Running as ROGUE camera (no certificate)...")
    use_cert = False
else:
    print("[CAMERA] Running as AUTHENTICATED camera...")
    use_cert = True

context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=server_ca)

if use_cert:
    context.load_cert_chain(certfile=client_cert, keyfile=client_key)

# We ignore hostname check for this local loopback prototype
context.check_hostname = False 

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
conn = context.wrap_socket(sock, server_hostname=HOST)

try:
    print(f"[CAMERA] Attempting mTLS Handshake with {HOST}:{PORT}...")
    conn.connect((HOST, PORT))
    
    server_cert = conn.getpeercert()
    server_subject = dict(x[0] for x in server_cert['subject'])
    
    print(f"\n[+] mTLS HANDSHAKE SUCCESSFUL!")
    print(f"    Server Identity Verified: {server_subject.get('commonName')}")
    
    print("\n[CAMERA] Streaming data...")
    conn.send(b"[DATA] Simulated Video Stream Frame #001")
    
    response = conn.recv(1024)
    print(f"[CAMERA] Server Response: {response.decode()}")
    
except ssl.SSLError as e:
    print(f"\n[!] mTLS HANDSHAKE FAILED: The server rejected us! Error: {e}")
except Exception as e:
    print(f"\n[!] Connection error: {e}")
finally:
    conn.close()
