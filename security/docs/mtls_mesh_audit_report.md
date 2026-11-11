# AEGIS Full-Mesh mTLS Connection Audit Report

- **Generated At (UTC):** `2026-11-11T11:53:48.924239+00:00`
- **Overall Result:** **PASS (Zero Plaintext Inter-Service Traffic)** (70/70 checks passed)

## Audit Summary Table

| Category | Service / Target | Check | Result | Detail |
| :--- | :--- | :--- | :---: | :--- |
| `compose` | `detector_video_classifier` | Host ports closed | **PASS** | 0 host ports published |
| `compose` | `detector_video_classifier` | mTLS listener enforced | **PASS** | uvicorn mTLS flags enforced (--ssl-cert-reqs=2, mesh_ca.crt) |
| `compose` | `detector_video_classifier` | Shared INTERNAL_API_KEY fallback removed | **PASS** | INTERNAL_API_KEY='', AEGIS_MESH_STRICT='1' |
| `compose` | `detector_aasist` | Host ports closed | **PASS** | 0 host ports published |
| `compose` | `detector_aasist` | mTLS listener enforced | **PASS** | uvicorn mTLS flags enforced (--ssl-cert-reqs=2, mesh_ca.crt) |
| `compose` | `detector_aasist` | Shared INTERNAL_API_KEY fallback removed | **PASS** | INTERNAL_API_KEY='', AEGIS_MESH_STRICT='1' |
| `compose` | `detector_rppg` | Host ports closed | **PASS** | 0 host ports published |
| `compose` | `detector_rppg` | mTLS listener enforced | **PASS** | uvicorn mTLS flags enforced (--ssl-cert-reqs=2, mesh_ca.crt) |
| `compose` | `detector_rppg` | Shared INTERNAL_API_KEY fallback removed | **PASS** | INTERNAL_API_KEY='', AEGIS_MESH_STRICT='1' |
| `compose` | `detector_syncnet` | Host ports closed | **PASS** | 0 host ports published |
| `compose` | `detector_syncnet` | mTLS listener enforced | **PASS** | uvicorn mTLS flags enforced (--ssl-cert-reqs=2, mesh_ca.crt) |
| `compose` | `detector_syncnet` | Shared INTERNAL_API_KEY fallback removed | **PASS** | INTERNAL_API_KEY='', AEGIS_MESH_STRICT='1' |
| `compose` | `gateway_validator` | mTLS listener enforced | **PASS** | uvicorn mTLS flags enforced (--ssl-cert-reqs=2, mesh_ca.crt) |
| `compose` | `gateway_validator` | HTTPS enforced for VIDEO_DETECTOR_URL | **PASS** | https://aegis_detector_video_classifier:8000/detect |
| `compose` | `gateway_validator` | HTTPS enforced for AUDIO_DETECTOR_URL | **PASS** | https://aegis_detector_aasist:8000/detect |
| `compose` | `orchestrator` | Strict mesh mode active | **PASS** | AEGIS_MESH_STRICT='1' |
| `compose` | `orchestrator` | HTTPS enforced for DETECTOR_VIDEO_CLASSIFIER_URL | **PASS** | https://detector_video_classifier:8000 |
| `compose` | `orchestrator` | HTTPS enforced for DETECTOR_AASIST_URL | **PASS** | https://detector_aasist:8000 |
| `compose` | `orchestrator` | HTTPS enforced for DETECTOR_RPPG_URL | **PASS** | https://detector_rppg:8000 |
| `compose` | `orchestrator` | HTTPS enforced for DETECTOR_SYNCNET_URL | **PASS** | https://detector_syncnet:8000 |
| `compose` | `orchestrator` | HTTPS enforced for DETECTOR_IMAGE_URL | **PASS** | https://detector_image:8000 |
| `compose` | `orchestrator` | HTTPS enforced for DETECTOR_TEXT_URL | **PASS** | https://detector_text:8000 |
| `compose` | `orchestrator` | HTTPS enforced for PROMETHEUS_URL | **PASS** | https://prometheus:9090 |
| `compose` | `prometheus` | Host port 9090 closed | **PASS** | 0 host ports published |
| `prometheus` | `aegis_detector_aasist` | HTTPS mutual-TLS scraping configured | **PASS** | scheme=https, cert_file=/mesh/mesh_prometheus.crt |
| `prometheus` | `aegis_detector_video_classifier` | HTTPS mutual-TLS scraping configured | **PASS** | scheme=https, cert_file=/mesh/mesh_prometheus.crt |
| `prometheus` | `aegis_detector_rppg` | HTTPS mutual-TLS scraping configured | **PASS** | scheme=https, cert_file=/mesh/mesh_prometheus.crt |
| `prometheus` | `aegis_detector_syncnet` | HTTPS mutual-TLS scraping configured | **PASS** | scheme=https, cert_file=/mesh/mesh_prometheus.crt |
| `prometheus` | `web_server` | RequireAndVerifyClientCert configured | **PASS** | client_auth_type=RequireAndVerifyClientCert |
| `nginx` | `api_gateway` | Upstream mTLS to gateway_validator enforced | **PASS** | proxy_pass https:// + proxy_ssl_verify on + mesh_api_gateway cert |
| `port_closure` | `127.0.0.1:8001` | Legacy plaintext detector port closed | **PASS** | port 127.0.0.1:8001 unreachable / refused |
| `port_closure` | `127.0.0.1:8002` | Legacy plaintext detector port closed | **PASS** | port 127.0.0.1:8002 unreachable / refused |
| `port_closure` | `127.0.0.1:8003` | Legacy plaintext detector port closed | **PASS** | port 127.0.0.1:8003 unreachable / refused |
| `port_closure` | `127.0.0.1:8004` | Legacy plaintext detector port closed | **PASS** | port 127.0.0.1:8004 unreachable / refused |
| `live_probe` | `video-classifier` | Plaintext HTTP rejected (:53482) | **PASS** | plaintext HTTP rejected (RemoteProtocolError) |
| `live_probe` | `video-classifier` | TLS without client cert rejected (:53482) | **PASS** | unauthenticated TLS rejected (ReadError) |
| `live_probe` | `video-classifier` | Non-mesh CA cert rejected (:53482) | **PASS** | wrong-CA camera cert rejected (RemoteProtocolError) |
| `live_probe` | `video-classifier` | Authorized mesh mTLS accepted (:53482) | **PASS** | mTLS verified (TLSv1.3, HTTP 200) |
| `live_probe` | `aasist` | Plaintext HTTP rejected (:53491) | **PASS** | plaintext HTTP rejected (RemoteProtocolError) |
| `live_probe` | `aasist` | TLS without client cert rejected (:53491) | **PASS** | unauthenticated TLS rejected (RemoteProtocolError) |
| `live_probe` | `aasist` | Non-mesh CA cert rejected (:53491) | **PASS** | wrong-CA camera cert rejected (RemoteProtocolError) |
| `live_probe` | `aasist` | Authorized mesh mTLS accepted (:53491) | **PASS** | mTLS verified (TLSv1.3, HTTP 200) |
| `live_probe` | `rppg` | Plaintext HTTP rejected (:53499) | **PASS** | plaintext HTTP rejected (RemoteProtocolError) |
| `live_probe` | `rppg` | TLS without client cert rejected (:53499) | **PASS** | unauthenticated TLS rejected (RemoteProtocolError) |
| `live_probe` | `rppg` | Non-mesh CA cert rejected (:53499) | **PASS** | wrong-CA camera cert rejected (RemoteProtocolError) |
| `live_probe` | `rppg` | Authorized mesh mTLS accepted (:53499) | **PASS** | mTLS verified (TLSv1.3, HTTP 200) |
| `live_probe` | `syncnet` | Plaintext HTTP rejected (:53507) | **PASS** | plaintext HTTP rejected (RemoteProtocolError) |
| `live_probe` | `syncnet` | TLS without client cert rejected (:53507) | **PASS** | unauthenticated TLS rejected (RemoteProtocolError) |
| `live_probe` | `syncnet` | Non-mesh CA cert rejected (:53507) | **PASS** | wrong-CA camera cert rejected (RemoteProtocolError) |
| `live_probe` | `syncnet` | Authorized mesh mTLS accepted (:53507) | **PASS** | mTLS verified (TLSv1.3, HTTP 200) |
| `live_probe` | `image` | Plaintext HTTP rejected (:53515) | **PASS** | plaintext HTTP rejected (RemoteProtocolError) |
| `live_probe` | `image` | TLS without client cert rejected (:53515) | **PASS** | unauthenticated TLS rejected (ReadError) |
| `live_probe` | `image` | Non-mesh CA cert rejected (:53515) | **PASS** | wrong-CA camera cert rejected (RemoteProtocolError) |
| `live_probe` | `image` | Authorized mesh mTLS accepted (:53515) | **PASS** | mTLS verified (TLSv1.3, HTTP 200) |
| `live_probe` | `text` | Plaintext HTTP rejected (:53524) | **PASS** | plaintext HTTP rejected (RemoteProtocolError) |
| `live_probe` | `text` | TLS without client cert rejected (:53524) | **PASS** | unauthenticated TLS rejected (RemoteProtocolError) |
| `live_probe` | `text` | Non-mesh CA cert rejected (:53524) | **PASS** | wrong-CA camera cert rejected (RemoteProtocolError) |
| `live_probe` | `text` | Authorized mesh mTLS accepted (:53524) | **PASS** | mTLS verified (TLSv1.3, HTTP 200) |
| `live_probe` | `gateway-validator` | Plaintext HTTP rejected (:53533) | **PASS** | plaintext HTTP rejected (RemoteProtocolError) |
| `live_probe` | `gateway-validator` | TLS without client cert rejected (:53533) | **PASS** | unauthenticated TLS rejected (ReadError) |
| `live_probe` | `gateway-validator` | Non-mesh CA cert rejected (:53533) | **PASS** | wrong-CA camera cert rejected (RemoteProtocolError) |
| `live_probe` | `gateway-validator` | Authorized mesh mTLS accepted (:53533) | **PASS** | mTLS verified (TLSv1.3, HTTP 200) |
| `live_probe` | `judge` | Plaintext HTTP rejected (:53541) | **PASS** | plaintext HTTP rejected (RemoteProtocolError) |
| `live_probe` | `judge` | TLS without client cert rejected (:53541) | **PASS** | unauthenticated TLS rejected (RemoteProtocolError) |
| `live_probe` | `judge` | Non-mesh CA cert rejected (:53541) | **PASS** | wrong-CA camera cert rejected (RemoteProtocolError) |
| `live_probe` | `judge` | Authorized mesh mTLS accepted (:53541) | **PASS** | mTLS verified (TLSv1.3, HTTP 200) |
| `live_probe` | `llm-bridge` | Plaintext HTTP rejected (:53549) | **PASS** | plaintext HTTP rejected (RemoteProtocolError) |
| `live_probe` | `llm-bridge` | TLS without client cert rejected (:53549) | **PASS** | unauthenticated TLS rejected (RemoteProtocolError) |
| `live_probe` | `llm-bridge` | Non-mesh CA cert rejected (:53549) | **PASS** | wrong-CA camera cert rejected (RemoteProtocolError) |
| `live_probe` | `llm-bridge` | Authorized mesh mTLS accepted (:53549) | **PASS** | mTLS verified (TLSv1.3, HTTP 200) |
