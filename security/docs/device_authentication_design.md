# mTLS Transport Architecture (Task 6)

**Problem:** In a live surveillance deployment, the network connection between the CCTV camera and our ingestion server is highly vulnerable. If we don't cryptographically verify the camera's identity, an attacker could unplug the camera, plug in their laptop, and stream a real-time deepfake directly into our system.

**Solution:** Mutual TLS (mTLS) Authentication.

---

### How It Works

Instead of just encrypting the traffic (like standard HTTPS), mTLS forces **both** sides of the connection to mathematically prove their identity before a single byte of video data is transmitted.

1. **The Root CA (Certificate Authority):**
   - We act as our own private Certificate Authority (`ca.crt`).
   - We use the highly-guarded private CA key to sign certificates for trusted hardware (the servers and the cameras).

2. **The Ingestion Server (`mtls_server.py`):**
   - Holds the `server.crt` and `server.key`.
   - **Crucial Rule:** It is strictly configured with `ssl.CERT_REQUIRED`. This means the server will instantly sever any connection attempt from a client that fails to present a valid certificate signed by our Root CA.

3. **The Edge Camera (`mtls_client.py`):**
   - Holds a unique `client.crt` and `client.key`.
   - When connecting to the ingestion server, it presents this certificate during the handshake.
   - Once the server verifies the cryptograhic signature, the secure TLS 1.3 tunnel is established and the camera is authorized to stream video.

### Security Guarantees
* **Anti-Spoofing / Zero Trust:** A hacker on the network cannot pretend to be a camera because they do not possess the private `client.key`. Even if they know the IP and Port, the server drops them instantly.
* **Anti-Eavesdropping:** The transport layer is fully encrypted via TLS 1.3.
* **Key Management:** Private keys (`*.key`) are strictly `.gitignore`'d to ensure they are never leaked to source control (which we just fixed!). In production, they exist only in secure hardware enclaves on the physical devices.
