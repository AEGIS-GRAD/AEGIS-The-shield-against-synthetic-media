"""
mTLS Server Prototype (Simulating the AEGIS Ingestion Node)
Owned by: Cyber Team

This server refuses connections from any client that does not present 
a valid certificate signed by our internal AEGIS Root CA.
"""
import socket
import ssl
import os
import sys

HOST = '127.0.0.1'
PORT = 8443

cert_dir = os.path.join(os.path.dirname(__file__), 'certs')
server_cert = os.path.join(cert_dir, 'server.crt')
server_key = os.path.join(cert_dir, 'server.key')
client_ca = os.path.join(cert_dir, 'ca.crt')

if not os.path.exists(server_cert):
    print("Certificates not found. Run generate_certs.sh first.")
    sys.exit(1)

# Configure mTLS Context
context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
context.verify_mode = ssl.CERT_REQUIRED # This line enforces mTLS
context.load_cert_chain(certfile=server_cert, keyfile=server_key)
context.load_verify_locations(cafile=client_ca)

bindsocket = socket.socket()
# Allow port reuse for rapid testing
bindsocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
bindsocket.bind((HOST, PORT))
bindsocket.listen(5)

print(f"[INGESTION SERVER] mTLS Server listening on {HOST}:{PORT}...")
print("[INGESTION SERVER] Awaiting secure camera connections...")

try:
    while True:
        newsocket, fromaddr = bindsocket.accept()
        try:
            # The SSL wrap performs the mTLS handshake
            conn = context.wrap_socket(newsocket, server_side=True)
            cert = conn.getpeercert()
            
            # Print the validated identity of the camera
            subject = dict(x[0] for x in cert['subject'])
            print(f"\n[+] SECURE CONNECTION ESTABLISHED from {fromaddr}")
            print(f"    Camera Identity Verified: {subject.get('commonName')}")
            
            data = conn.recv(1024)
            if data:
                print(f"    Received: {data.decode()}")
                conn.send(b"HTTP/1.1 200 OK\n\nIngestion Successful")
        except ssl.SSLError as e:
            print(f"\n[!] CONNECTION REJECTED: {e}")
        finally:
            try:
                conn.close()
            except:
                pass
except KeyboardInterrupt:
    print("\nShutting down server.")
