# Cybersecurity API Gateway

This folder contains the configuration, upload validator, and testing scripts for the AEGIS ingestion gateway.

## What is this?
The gateway is a two-layer "Security Bouncer" for all incoming traffic before it reaches the backend AI detector microservices:

1. **`api_gateway` (Nginx reverse proxy)** - authentication, per-key rate limiting, and a hard payload-size ceiling.
2. **`gateway_validator` (`validator/`, FastAPI, internal-only)** - deep content inspection that plain Nginx config can't do: magic-byte verification against an explicit file-type allowlist, and path-traversal confinement. Only reachable from `api_gateway` on `aegis_net` - it has no published port.

Together these enforce the constraints in [`shared/json-api-contracts-schema/SCHEMA.md`](../../shared/json-api-contracts-schema/SCHEMA.md) Section 1 (max payload size, extension + magic-byte allowlist, path-traversal prevention). That doc is the source of truth for those limits - don't redefine them here.

## Features
1. **Authentication:** Nginx intercepts all requests and enforces the `X-Internal-Token` header. Missing/invalid key -> instant `401 Unauthorized`.
2. **Per-key rate limiting:** `limit_req_zone` is keyed on `$http_x_internal_token`, not source IP, so each API key gets its own budget (10 req/s, burst 20) instead of everyone behind one NAT sharing a bucket.
3. **Payload size cap:** `client_max_body_size 50m` rejects oversized bodies at the Nginx edge with a `413` before they're even buffered.
4. **Magic-byte + allowlist validation:** `gateway_validator` checks the uploaded content's actual file signature against its declared extension (video) or declared modality (audio) - an executable renamed to `clip.mp4` is rejected with `415`, not forwarded to a detector.
5. **Path-traversal prevention:** client-supplied filenames containing `..`, `/`, or absolute paths are rejected outright (`400`); an internal file-path payload (per the audio JSON contract) must resolve inside `SHARED_VOLUME_ROOT`.
6. **Audit Logging:** Nginx logs every request across the Docker network (Timestamp, Source IP, Endpoint, and Status Code) to standard output.
7. **Routing:** Once validated, the request is forwarded transparently to the real detector (`video-classifier` or `aasist`).

## How it works
`nginx.conf.template` contains the Nginx logic; `docker-compose up` uses `envsubst` to inject `INTERNAL_API_KEY` from your root `.env` file without hardcoding secrets. `/api/video` and `/api/audio` proxy to `gateway_validator`, which in turn proxies clean requests on to the real detector.

`video-classifier` and `aasist` currently use two different request shapes (raw multipart upload vs. a JSON body with a base64/path `payload` field) - `validator/app/main.py` has a dedicated validation path for each. This inconsistency between the two detectors is a known, separate issue outside this gateway's scope (see project notes) - not something fixed here.

## How to Test

**Automated suite (no live containers needed - this is what CI runs):**
```bash
cd validator
pip install -r requirements.txt
pytest tests/ -v
```
Covers valid uploads plus malicious cases: spoofed extensions, disallowed extensions, oversized payloads, path-traversal filenames/payloads, malformed base64, and modality/content mismatches.

**End-to-end smoke test against a running stack** (`docker compose up -d`), from this directory:

**Windows:**
```powershell
.\test_gateway.ps1
```

**Linux/Mac:**
```bash
./test_gateway.sh
```

**Expected Results:**
- **Test 1 (No Key):** `401 Unauthorized`.
- **Test 2 (Oversized Upload):** `413 Payload Too Large`.
- **Test 3 (Spoofed File):** `415 Unsupported Media Type`.
- **Test 4 (Path-Traversal Filename):** `400 Bad Request`.
