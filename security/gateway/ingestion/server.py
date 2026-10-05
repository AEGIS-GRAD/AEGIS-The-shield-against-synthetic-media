import asyncio
import ssl
import json
import os
import sys
import hashlib

# Add paths for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from stream_integrity.stream_validator import StreamValidator

HOST = '127.0.0.1'
PORT = 8443

class LiveHashChainValidator:
    """
    A live streaming adaptation of the offline FrameHashChain from Task 4.
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

async def handle_camera_stream(reader, writer):
    """
    Handles a live incoming camera stream.
    Only called if mTLS handshake succeeds.
    """
    peer_cert = writer.get_extra_info('peercert')
    camera_id = dict(x[0] for x in peer_cert['subject']).get('commonName', 'Unknown')
    print(f"\n[+] SECURE CONNECTION: {camera_id} authenticated via mTLS.")

    # Initialize validators for this specific camera feed
    stream_validator = StreamValidator(fps=30)
    hash_validator = LiveHashChainValidator()

    try:
        while True:
            line = await reader.readline()
            if not line:
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
            
            # TODO: Here we will pass the verified frame downstream to the Orchestrator via queue
            
    except Exception as e:
        print(f"[-] Connection error with {camera_id}: {e}")
    finally:
        print(f"[-] Closed connection to {camera_id}")
        writer.close()
        await writer.wait_closed()

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
    print("[AEGIS GATEWAY] Enforcing SSL.CERT_REQUIRED (mTLS). Awaiting cameras...")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        print("\n[AEGIS GATEWAY] Shutting down.")
