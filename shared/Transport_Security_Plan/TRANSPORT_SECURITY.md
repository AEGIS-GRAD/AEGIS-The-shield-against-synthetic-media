# AEGIS — Transport Security Plan

**Status:** Design document — not yet implemented
**Owner:** Cybersecurity Team
**Related requirement:** SR-02 (Secure transport), from Chapter 1 Section 7 threat model
**Sprint task:** "Design (not yet implement) the transport security plan"

---

## 1. Purpose

This document defines how inter-service communication in AEGIS will be secured as the
system grows beyond a single local Docker Compose deployment. It exists to make the
transport-security decision explicit and reviewable *before* the network topology in
Task 2 (containerize and network-isolate the detector services) is locked in — retrofitting
security after the architecture is fixed is harder and easier to get wrong.

This is a **design note**, not an implementation. Nothing described here needs to be built
this sprint.

## 2. What "Transport Security" Covers

Two separate properties, often solved together:

1. **Encryption** — traffic between services can't be read by anyone sitting on the
   network path between them.
2. **Mutual identity verification** — each service can prove to the other *who it is*,
   not just that the connection is encrypted. A normal HTTPS website only proves the
   *server's* identity to the client; mutual TLS (mTLS) proves *both directions*, so a
   detector service can also confirm the caller is really the gateway and not an impostor.

This maps directly to threat-model rows already on record: the network-level attacker
(intercept/reroute/replay on the camera and service path) and the general spoofing/
tampering categories under STRIDE.

## 3. Current State (Now — Local Docker Compose)

### 3.1 Active Services on `aegis_net`

Since the initial draft of this document, the Docker Compose stack has grown
substantially. The full set of services running on the internal `aegis_net` bridge
network as of the current sprint is:

| Service | Container | Exposed port (host) | Role |
|---|---|---|---|
| `api_gateway` | `aegis_api_gateway` | `8081` | Nginx reverse proxy + API-key enforcement |
| `gateway_validator` | `aegis_gateway_validator` | *(internal only)* | Deep file inspection (magic bytes, extension allowlist) |
| `orchestrator` | `aegis_orchestrator` | `8000` | Dispatch fan-out to all detectors |
| `web` | `aegis_web` | `3000` | Next.js frontend |
| `detector_video_classifier` | `aegis_detector_video_classifier` | `8001` | EfficientNet-B0 video deepfake detector |
| `detector_aasist` | `aegis_detector_aasist` | `8002` | AASIST audio deepfake detector |
| `detector_rppg` | `aegis_detector_rppg` | `8003` | rPPG physiological liveness detector |
| `detector_syncnet` | `aegis_detector_syncnet` | `8004` | SyncNet audio-visual sync detector |
| `mediamtx` | `aegis_mediamtx` | `8554` (RTSP), `1935` (RTMP), `8888` (HLS) | Live camera stream relay |
| `wazuh_agent` | `aegis_wazuh_agent` | *(internal only)* | SIEM log collection / rule matching |
| `engine` | `aegis_engine` | *(internal only)* | Edge model inference (MobileNetV3-Small) |
| `prometheus` *(telemetry profile)* | `aegis_prometheus` | `9090` | Metrics scraping |
| `grafana` *(telemetry profile)* | `aegis_grafana` | `3001` | Metrics dashboard |

### 3.2 Security Controls Currently Active

- **API-key authentication** is enforced by the `api_gateway` (Nginx) on every inbound
  request. The key is injected via the `INTERNAL_API_KEY` environment variable and
  checked before any request is proxied to internal services.
- **`gateway_validator`** performs deep upload inspection (magic-byte checks, file
  extension allowlist, path-confinement) that plain Nginx configuration cannot do.
  It is internal-only — no host port is exposed, reachable only from `api_gateway`
  on `aegis_net`.
- **Docker network isolation**: all containers communicate on the `aegis_net` bridge
  network, which is not reachable from the public internet. The only externally
  reachable surfaces are the ports explicitly mapped in `docker-compose.yml`.
- **Wazuh agent** provides SIEM-style log collection and anomaly detection across
  services, with custom decoders/rules mounted from `./security`.

### 3.3 New Network Surface: MediaMTX (Live Camera Feed)

A significant addition since the original draft is **MediaMTX**, the RTSP/RTMP/HLS
stream relay. This introduces a new trust boundary concern:

- The webcam feed (and any external camera) is ingested over RTSP (port `8554`) or
  RTMP (port `1935`), which are **plain-text protocols by default** — no encryption.
- If the camera source is on the same machine as the Docker host (e.g., a laptop
  webcam), this is low risk: traffic never leaves the host.
- If an external camera device (e.g., an IP camera or a Jetson board) pushes a stream
  to MediaMTX over a real network, the stream can be intercepted. RTSP-over-TLS
  (`rtsps://`) or RTMP-over-TLS (`rtmps://`) is the correct mitigation in that case.
- **Current decision:** MediaMTX runs without TLS for the same reason as the rest of
  the stack — the trust boundary is the local Docker host, not the network. If/when
  an external camera is used over a real network, MediaMTX must be reconfigured for
  RTSP-over-TLS before the final demo.

### 3.4 Port Exposure Notes

Several detector ports (`8001`–`8004`) are **directly exposed to the host** for AI team
testing convenience. This bypasses the API gateway (authentication, rate-limiting,
logging). Each of these services carries the following notice in `docker-compose.yml`:

> *MUST BE REMOVED IN PRODUCTION to enforce routing through Nginx.*

This is a known, accepted deviation from the transport security model during development.
It must be resolved before any public or multi-machine demo deployment.

### 3.5 Decision: No mTLS at This Stage

Traffic between containers on `aegis_net` is **not encrypted**. There is no
attacker-reachable path between services at this stage (single-host deployment).
The API-key authentication layer and the `gateway_validator` inspection layer are the
active controls right now. This is judged sufficient because the trust boundary is
the Docker host itself, not the network.

This decision is explicitly scoped as provisional — see Section 5.

## 4. Future State — Options for When the System Leaves Local Compose

Once AEGIS moves beyond one machine (e.g., detector services on separate hosts, or a
real edge-deployment scenario with camera feeds arriving from outside the local
network), the trust boundary changes and transport security becomes necessary, not
optional.

### Option A — Mutual TLS (mTLS) between services

- Each service holds a private key and a certificate signed by a project-internal
  Certificate Authority (CA).
- Every service-to-service call is encrypted, and both sides verify the other's
  certificate before accepting the connection.
- **Pros:** Well-understood, works with plain Docker/Compose or lightweight
  orchestration, no new infrastructure component required, directly maps to SR-02 and
  SR-11 (key management) that already exist in the threat model.
- **Cons:** Certificate issuance, distribution, and rotation must be handled manually or
  scripted — this is real ongoing operational work, not a one-time setup.
- **Fit for this project:** Good — matches the team's size and timeline. This is the
  recommended default if/when the system needs to leave local Compose.

### Option B — Service Mesh (e.g., Istio, Linkerd)

- A dedicated infrastructure layer that automatically injects mTLS, identity, and
  traffic policy between services, without each service handling certificates itself.
- **Pros:** Removes per-service certificate handling; adds observability (traffic
  metrics, retries) as a side benefit.
- **Cons:** Meaningful new infrastructure to learn, deploy, and maintain (typically
  requires Kubernetes or a comparable orchestrator) — disproportionate for a system of
  AEGIS's current size (4 detector services plus a gateway, relay, and SIEM agent).
- **Fit for this project:** Not recommended for the graduation-project timeline. Worth
  naming as the natural next step *if* AEGIS were to continue past graduation into a
  larger, production-shaped deployment.

## 5. Recommendation

- **Now (Compose-local, single host):** No transport encryption — rely on Docker's
  internal network isolation plus API-key authentication at the gateway and deep file
  inspection at `gateway_validator`.
- **Before any multi-machine or external-camera demo:** Enable RTSP-over-TLS on
  MediaMTX for all camera streams that traverse a real network. Remove the direct
  host-port mappings on detector services (`8001`–`8004`) so all traffic routes
  through the API gateway.
- **If/when services move to separate hosts or a real edge deployment:** Adopt
  **Option A (mTLS)**, using a small project-internal CA. This is the smallest step
  that closes the gap identified in SR-02, without pulling in infrastructure (a
  service mesh) the team doesn't have time to operate.
- **Explicitly out of scope for this graduation cycle:** Service mesh deployment.
  Documented here as a known future path, not a planned deliverable — consistent
  with how other advanced items (full hash-chaining, production PRNU) were scoped out
  in `Graduation_Project.docx §1.5`.

## 6. Anticipated Direction and Open Question for Supervisor Review

**Current expectation:** the team anticipates the final demo will involve some form of
multi-machine deployment (e.g., a separate device simulating a camera/edge feed talking
to the detection system over a real network), rather than staying entirely on one
laptop. If confirmed, this means **Option A (mTLS) is expected to move from
"documented" to "implemented"** before the final defense, not stay design-only.
MediaMTX RTSP-over-TLS would also need to be enabled at that point.

**What is not yet decided:** the exact topology — which machines will be available
(team laptops? a shared lab machine? an actual edge device such as a Jetson board?),
how many hosts are involved, and whether the "camera" side is a real device or a
simulated feed from another machine. This directly affects implementation details
(e.g., how the internal CA and certificates are distributed, whether a lightweight
edge device can handle TLS overhead, and whether MediaMTX needs RTSP-over-TLS or
RTMP-over-TLS depending on the camera client protocol).

**Until this is resolved:** the mTLS design in Section 4 (Option A) is written to be
topology-agnostic — it does not assume a specific number of hosts or a specific
device type — so no work here needs to be redone once the hardware question is
answered. Implementation (certificate generation, distribution, and integration into
each service) is deferred until the topology is confirmed.

---

## 7. Changelog

| Date | Change |
|---|---|
| Initial draft | Original design document written. Stack described as: gateway + video-classifier + audio-aasist. |
| Oct 2026 update | Expanded Section 3 to reflect full Docker Compose stack (5 detector microservices, MediaMTX RTSP/RTMP/HLS relay, Wazuh SIEM agent, gateway_validator deep inspection layer, Prometheus + Grafana telemetry profile). Added Section 3.3 (MediaMTX new network surface and TLS requirement), Section 3.4 (port exposure known deviation), and Section 3.5 (explicit mTLS decision statement). Updated Option B service count. Updated Recommendation to include pre-demo MediaMTX TLS step. |

---

*This document satisfies the sprint deliverable "Design (not yet implement) the
transport security plan." No implementation work is required from this document; the
next action is supervisor review and a decision on the open question in Section 6.*
