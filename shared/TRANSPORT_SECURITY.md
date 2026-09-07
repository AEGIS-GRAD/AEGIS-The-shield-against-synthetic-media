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

- All services (gateway, video-classifier, audio-aasist) run as containers on a single
  Docker host, communicating over an internal Compose network.
- Traffic between containers on this internal network is **not exposed to the public
  internet or any external network** — there is no attacker-reachable path between
  services at this stage.
- **Decision: no mTLS or transport encryption is implemented at this stage.** The
  API-gateway authentication layer (API keys on every request, per Task 2's own scope)
  is the active control right now. This is judged sufficient because the trust
  boundary is the Docker host itself, not the network.
- This decision is explicitly scoped as provisional — see Section 5.

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
  AEGIS's current size (2–3 detector services plus a gateway).
- **Fit for this project:** Not recommended for the graduation-project timeline. Worth
  naming as the natural next step *if* AEGIS were to continue past graduation into a
  larger, production-shaped deployment.

## 5. Recommendation

- **Now (Compose-local, single host):** No transport encryption — rely on Docker's
  internal network isolation (Task 2) plus API-key authentication at the gateway.
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

**What is not yet decided:** the exact topology — which machines will be available
(team laptops? a shared lab machine? an actual edge device such as a Jetson board?),
how many hosts are involved, and whether the "camera" side is a real device or a
simulated feed from another machine. This directly affects implementation details
(e.g., how the internal CA and certificates are distributed, whether a lightweight
edge device can handle TLS overhead).

**Until this is resolved:** the mTLS design in Section 4 (Option A) is written to be
topology-agnostic — it does not assume a specific number of hosts or a specific
device type — so no work here needs to be redone once the hardware question is
answered. Implementation (certificate generation, distribution, and integration into
each service) is deferred until the topology is confirmed.

---

*This document satisfies the sprint deliverable "Design (not yet implement) the
transport security plan." No implementation work is required from this document; the
next action is supervisor review and a decision on the open question in Section 6.*
