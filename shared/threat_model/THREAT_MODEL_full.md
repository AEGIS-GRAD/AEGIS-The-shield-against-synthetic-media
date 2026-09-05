# AEGIS - Chapter 1: Project Analysis
## Section 7: Cybersecurity Components

**Multimodal AI-Based Deepfake and Synthetic Media Detection System**  

### 7.1 Security Problem and Threat Model

AEGIS is a multimodal AI-based deepfake and synthetic-media detection system designed to analyze images, audio, video, and text, with a real-time surveillance extension. In the surveillance scenario, media is received continuously from camera feeds and processed to identify manipulated or synthetic content while maintaining low latency. The cybersecurity problem therefore extends beyond protecting the classifier: the system must establish that the media entering the pipeline is authentic, that communications have not been manipulated, and that alerts and forensic evidence remain trustworthy.

The project identifies four principal security surfaces: 
1. The AI detection layer
2. The live camera-feed layer
3. The SIEM/Wazuh monitoring layer
4. The C2PA/provenance layer

An attacker may attempt to fool the detector, replace or modify the camera stream before detection, interfere with security telemetry, or manipulate provenance information. The threat model therefore covers both content authenticity and pipeline/evidence trustworthiness.

The threat model follows the media and evidence path through the proposed system: **Media Source → Ingestion/Camera Feed → Preprocessing and Detection → Fusion/Explanation → Alert and Evidence Storage → SIEM/SOC.** 

Threats are evaluated using **STRIDE**. **MITRE ATLAS** is used where an AI-specific technique provides an appropriate mapping; infrastructure threats such as RTSP, Wazuh, and cryptographic implementation weaknesses are retained even when ATLAS does not provide an equivalent technique.

#### Threat Actors

| Actor | Capability / Motivation | Relevant Surface |
| :--- | :--- | :--- |
| **External attacker** | Remote adversary attempting to manipulate media, disrupt service, or bypass detection. | Camera/network interfaces, AI inputs |
| **Network-level attacker** | Attacker able to intercept, reroute, replay, or inject traffic on the camera path. | RTSP/RTP and local network |
| **AI-aware adversary** | Attacker who understands detector weaknesses and crafts adversarial inputs. | AI models and fusion |
| **Malicious insider** | Authorized user abusing credentials or infrastructure access. | Wazuh, evidence, signing keys |
| **Compromised edge/camera device** | Legitimate device controlled by an attacker. | Camera identity and stream integrity |
| **Provenance attacker** | Attacker seeking to remove, forge, or misuse provenance information. | C2PA manifests and signing keys |

#### Protected Assets

| Asset | Security Importance |
| :--- | :--- |
| **Live camera streams** | Primary real-time input; manipulation can cause false conclusions or blind spots. |
| **Uploaded media** | Input to offline multimodal analysis. |
| **AI models and model files** | Core detection capability; poisoning or unauthorized modification can alter decisions. |
| **Model outputs, confidence scores and explanations** | Support final authenticity assessment and human review. |
| **Camera identities and credentials** | Prevent unauthorized devices from impersonating legitimate cameras. |
| **Security alerts, logs and forensic evidence** | Must remain available, accurate and tamper-evident. |
| **C2PA manifests and signing keys** | Support provenance and authenticity claims. |
| **Wazuh configuration and telemetry** | Security monitoring and incident investigation. |

#### STRIDE Method
* **Spoofing** identifies impersonation of a trusted entity.
* **Tampering** covers unauthorized modification of media, telemetry or evidence.
* **Repudiation** covers loss of reliable attribution or evidence.
* **Information Disclosure** covers unauthorized exposure of protected data.
* **Denial of Service** covers loss of system availability.
* **Elevation of Privilege** covers obtaining permissions beyond those legitimately assigned.

#### Threat Coverage for the Service Architecture (added Week 1)

The threat surfaces above describe the system at a conceptual level. As the repository now defines a concrete microservice architecture — `orchestrator`, `engine`, `debate`, `eval`, `mcp`, and individual `detector_*` containers communicating over a shared internal Docker network — two additional, more immediate threats apply and directly inform this week's API design decisions:

- **Internal service trust (Spoofing + Tampering).** Containers on the internal network (`aegis_net`) can currently reach one another freely. Without per-service authentication, a compromised or buggy container (e.g. a detector) could send forged results to the orchestrator or debate layer, or a rogue container could impersonate a trusted service. This is why every service in `docker-compose.yml` now requires a shared `INTERNAL_API_KEY` — this threat is the reasoning behind that requirement, not just a general best practice.
- **Untrusted media parsing (Tampering / potential Elevation of Privilege).** The ingestion and detector services will parse attacker-influenced video, audio, and image files. Media-parsing libraries (e.g. FFmpeg, OpenCV, image decoders) have a documented history of memory-safety and remote-code-execution vulnerabilities. Detector services must treat uploaded/streamed media as untrusted input: no arbitrary file execution, parsing confined to hardened/sandboxed libraries where feasible, and strict allowlisting of accepted file types and sizes at the API boundary (see SR-16, and the corresponding requirement for Task 3's API schema).
- **The `mcp` (tool-calling) layer is a new surface not covered above.** Because the orchestrator agent selects and invokes detector "tools," a malicious or malformed detector response could attempt to manipulate the orchestrator's future tool-selection logic (a form of prompt/response injection). This should be tracked as a residual risk pending the mcp implementation, rather than assumed away.

This section will be extended as the microservice architecture matures; it is intentionally short for now, per this week's scope.

---

### 7.2 Potential Threats and Attack Scenarios

The following 21 scenarios are retained from the expanded STRIDE analysis. Sources are distinguished from team-derived design reasoning. MITRE ATLAS mappings are included where they are directly relevant; conventional infrastructure threats are not artificially mapped to ATLAS.

| # | Component | STRIDE | Attack Scenario | Source / Precedent | ATLAS | Severity |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | AI detector (image/audio/video/text) | Spoofing | Imperceptible adversarial perturbations cause synthetic media to be classified as authentic. | Carlini & Farid (2020); Hussain et al. (2021); Neekhara et al. (2021) | AML.T0015 | High |
| **2** | Image/video detector | Spoofing | Frequency-domain perturbations target forensic artifacts used by the detector. | Jia et al. (2022) | AML.T0015 | High |
| **3** | Audio detector | Spoofing | Convolutive adversarial noise is designed to defeat audio spoofing detection. | Panariello et al. (2023), Malafide | AML.T0015 | High |
| **4** | Face-deepfake video detector | Spoofing | Adapted adversarial noise targets face-deepfake detection. | Project research: 2D-Malafide line of work | AML.T0015 | Med–High |
| **5** | Face/voice consistency module | Spoofing | Face-swap and voice-clone timing is coordinated to defeat cross-modal consistency checks. | Team-derived from proposed fusion design | AML.T0015 | High |
| **6** | AI training pipeline | Tampering | A poisoned or backdoored pretrained checkpoint is introduced before deployment. | MITRE ATLAS backdoor/model-poisoning class; project supply-chain risk | AML.T0018 | High |
| **7** | Edge-deployed quantized models | Spoofing | Patch/adversarial attacks remain transferable across quantization levels. | Project research: QNN adversarial-robustness studies (2021–2025) | AML.T0015 | Med–High |
| **8** | Edge device | Elevation + Tampering | Physical/local access may allow interference with the model, inputs or deployment environment. | Team-derived architectural threat; local-access risk | — | Med–High |
| **9** | Live camera RTSP stream | Spoofing + Tampering | Pre-recorded or fabricated footage replaces the live stream before AI analysis. | VideoJak-style RTSP/RTP injection; cleartext RTSP exposure research | AML.CS0034 (related) | Critical |
| **10** | Camera local network | Spoofing + Tampering | ARP poisoning or DHCP/DNS spoofing reroutes traffic so fabricated video reaches the detector. | Documented IP-camera feed-replacement demonstrations | AML.CS0034 (related) | Critical |
| **11** | Live camera RTSP stream | Denial of Service | A crafted malformed RTSP DESCRIBE request can cause an affected Ningyuanda TC155 camera to reboot, demonstrating a real availability threat against RTSP camera infrastructure. | NVD CVE-2025-14747; original third-party advisory referenced by NVD | — | High |
| **12** | Encrypted camera feed | Information Disclosure | Traffic patterns may reveal limited information about the underlying media even when payloads are encrypted. | Project research; lower-severity traffic-analysis observation | — | Low |
| **13** | Camera device identity | Spoofing | A rogue device impersonates a legitimate camera and supplies a trusted-looking feed. | Logical extension of RTSP/MITM findings; not independently sourced | — | High |
| **14** | SIEM/Wazuh alert pipeline | Tampering + Repudiation | NDJSON injection can manipulate/delete alerts and forensic records in affected Wazuh Manager versions. | CVE-2026-56699 / Wazuh Manager vulnerability | — | Critical |
| **15** | Wazuh agent communication | Spoofing | A compromised/impersonated agent could inject misleading telemetry or false 'all clear' signals. | Team-derived consequence of agent-channel trust; not independently sourced | — | High |
| **16** | Wazuh/log storage | Denial of Service | High-volume false alerts can bury genuine detections, consume monitoring capacity, or overwhelm analysts. | Target 2013 breach reporting and subsequent monitoring/logging improvements | — | Medium |
| **17** | Custom Wazuh decoder/rules | Tampering | Malformed AI-alert data can exploit insufficient validation in the team's own decoder/rules. | Team design responsibility; informed by Wazuh input-validation failure | — | High |
| **18** | C2PA provenance manifest | Spoofing by omission | Complete removal of a manifest removes embedded provenance information. | C2PA Security Considerations | — | Medium |
| **19** | C2PA provenance | Spoofing + Repudiation | A real manifest is stripped and replaced/represented with misleading provenance information. | C2PA Security Considerations; project provenance research | — | High |
| **20** | C2PA signing key | Elevation of Privilege | Compromise of a legitimate signing key allows forged claims under a trusted identity. | Project provenance research; C2PA trust model | — | Critical |
| **21** | Cryptographic signing implementation | Tampering | Weak key storage, obsolete algorithms, poor rotation or insecure secret handling can undermine signing integrity. | Security engineering requirement; NIST key-management guidance | — | High |

---

### 7.3 Security Requirements

| ID | Requirement | System shall... |
| :--- | :--- | :--- |
| **SR-01** | Camera authentication | The system shall authenticate authorized camera/edge devices before accepting surveillance streams. |
| **SR-02** | Secure transport | The system shall use authenticated and encrypted communication for camera-to-ingestion and security-telemetry paths where supported by the deployed protocol. |
| **SR-03** | Stream integrity | The system shall validate timestamps, sequence information and continuity indicators to detect replay, duplication, reordering or injection. |
| **SR-04** | Evidence integrity | Flagged media, model outputs and relevant alerts shall be stored with tamper-evident integrity protection. |
| **SR-05** | Adversarial robustness | The AI pipeline shall be evaluated against representative adversarial perturbations for each implemented modality. |
| **SR-06** | Model provenance | Externally sourced model files and dependencies shall be verified before use and protected against unauthorized replacement. |
| **SR-07** | Least privilege | Camera, AI, API, evidence-storage and SIEM components shall operate with only the permissions required for their functions. |
| **SR-08** | Input validation | Wazuh decoders/rules and application interfaces shall validate and constrain untrusted fields before processing. |
| **SR-09** | SIEM resilience | The monitoring layer shall preserve critical alerts despite high-volume or malformed input and shall detect alert flooding. |
| **SR-10** | Provenance validation | C2PA manifests shall be cryptographically validated and absence of provenance shall not be treated as proof of authenticity. |
| **SR-11** | Key management | Signing keys shall be stored securely, rotated according to policy, protected from unauthorized export, and replaced when compromise is suspected. |
| **SR-12** | Incident response | Security alerts shall trigger a defined escalation workflow and preserve sufficient context for investigation. |
| **SR-13** | Fail-safe behavior | Loss of camera integrity, authentication or telemetry shall not silently produce a trusted 'authentic' state. |
| **SR-14** | Security logging | Security-relevant actions shall generate auditable logs protected against unauthorized modification or deletion. |
| **SR-15** | Internal service authentication | Every internal service (orchestrator, engine, detectors, debate, eval, mcp) shall require a shared internal API key on all requests, including service-to-service calls on the internal network — no internal endpoint shall be reachable without it. |
| **SR-16** | Safe media parsing | All services that parse uploaded or streamed media shall treat it as untrusted input: enforce an explicit allowlist of accepted file types (not a blocklist), enforce a maximum payload size, and avoid parsing paths known to enable arbitrary code execution. |

---

### 7.4 Proposed Security Mechanisms

| Security Area | Proposed Mechanism |
| :--- | :--- |
| **Camera identity** | Mutual authentication, unique device credentials/certificates, enrollment and revocation of cameras. |
| **Secure stream transport** | Authenticated encrypted transport where supported; isolate camera networks and restrict RTSP exposure to trusted segments. |
| **Replay/injection detection** | Timestamp and sequence validation, continuity checks, frame hash chaining, and comparison of stream identity/integrity signals. |
| **Adversarial defense** | Adversarial test sets, robustness benchmarking, augmentation, and—where feasible—adversarial/robust training for implemented detectors. |
| **Model supply chain** | Hash/version verification of model artifacts, controlled model registry, dependency pinning, and restricted write access to deployed model files. |
| **Edge security** | Minimal services, hardened OS/container configuration, restricted local access, secure boot/device integrity controls where supported, and protected model storage. |
| **Wazuh hardening** | Use supported patched Wazuh releases, restrict agent communication, validate custom decoder inputs, protect configuration, and monitor changes. |
| **Alert-flood resistance** | Rate limiting, event deduplication/correlation, priority queues for critical alerts, storage/throughput monitoring, and analyst-facing alert aggregation. |
| **Forensic evidence protection** | Hashing, append-only or access-controlled storage, integrity verification, synchronized timestamps, and preservation of original evidence. |
| **C2PA validation** | Validate signatures and content bindings; treat missing provenance as 'unknown' rather than 'authentic'; retain independent evidence when provenance is absent. |
| **Cryptographic key management** | Use established cryptographic libraries/algorithms, protected key storage, controlled rotation/revocation, separation of signing privileges, and secret-access auditing. |
| **Incident response** | Immediate operator notification, evidence preservation, containment actions, camera quarantine/re-authentication, and post-incident review. |
| **Internal service authentication** | Shared internal API key (see `INTERNAL_API_KEY` in `docker-compose.yml`), required on every internal service; to be revisited in favor of per-service credentials/mTLS if the architecture grows past the current stub stage. |
| **Safe media parsing** | Explicit file-type allowlist and payload size limits enforced at each service's API boundary; use of well-maintained, patched media-parsing libraries. |

> [!IMPORTANT]
> **Security Design Principle:** Detection is not enough. The system should distinguish between (a) content assessed as authentic, (b) content assessed as manipulated, and (c) content for which the integrity of the acquisition or evidence chain cannot be established. This prevents a compromised camera/network path from silently converting an integrity failure into a trusted AI verdict.

---

### 7.5 Security Tools and Testing Environment

Security validation will use a controlled test environment that reproduces the principal trust boundaries of the proposed system without requiring attacks against production infrastructure.

| Tool / Environment | Purpose |
| :--- | :--- |
| **Wazuh** | SIEM, security-event collection, alerting and monitoring of the cybersecurity pipeline. |
| **Python / FastAPI** | Integration and preprocessing services; security validation of APIs and alert payloads. |
| **PyTorch / AI test harness** | Adversarial-robustness testing, model integrity checks and comparison of clean versus adversarial inputs. |
| **RTSP test camera/stream** | Controlled surveillance-feed source for replay, injection, authentication and availability testing. |
| **Network test environment** | Isolated lab for MITM, replay, traffic manipulation and segmentation validation. |
| **C2PA tooling** | Manifest creation/validation and controlled provenance stripping/alteration tests. |
| **Cryptographic verification tools** | Hash/signature verification, key-storage and rotation tests, and integrity checks. |
| **Synthetic attack dataset** | Controlled adversarial, replayed, manipulated and malformed inputs for repeatable evaluation. |

---

### 7.6 Security Evaluation and Validation Criteria

| Control | Validation Test | Acceptance Criterion |
| :--- | :--- | :--- |
| **Camera authentication** | Unauthorized device connection attempt | Unauthorized source is rejected; legitimate camera remains accepted. |
| **Stream integrity** | Replay/injection/reordering test | Attack is detected or rejected; affected segment is not silently trusted. |
| **RTSP availability** | Controlled malformed/high-volume RTSP traffic | Camera/ingestion remains available or enters an explicit fail-safe state; outage is detected. |
| **AI adversarial robustness** | Clean vs. adversarial test set | Report accuracy degradation, attack success rate, and robustness delta by modality. |
| **Model integrity** | Modified/unsigned model artifact | Unauthorized artifact is rejected or clearly flagged before inference. |
| **Wazuh integrity** | Alert tampering/injection test | Critical alerts remain trustworthy; malformed telemetry does not silently overwrite evidence. |
| **Alert flooding** | High-volume synthetic alert stream | Critical events remain detectable; throughput/storage behavior is measured. |
| **Forensic integrity** | Modify/delete evidence after detection | Integrity verification detects unauthorized changes and preserves chain-of-evidence metadata. |
| **C2PA validation** | Strip/alter/replace provenance | Validator detects invalid provenance; missing provenance produces an explicit unknown state. |
| **Key management** | Access/rotation/revocation tests | Unauthorized key use/export is prevented or detected; revoked keys cannot create trusted new evidence. |
| **Incident response** | End-to-end simulated attack | Alert, escalation, evidence preservation and containment occur within defined operational targets. |
| **Overall security** | Threat-model regression suite | No critical threat is left without either a preventive/detective control or an explicitly documented residual risk. |
| **Internal service authentication** | Request without/with wrong internal API key | Request is rejected with an authentication error; correct key is accepted. |

---

### References

[1] AEGIS Cybersecurity Threat Research. Chapter 1, Section 7 supporting research, project team document, August 2026.  
[2] AEGIS Graduation Project Proposal — 2026/2027. Egyptian Chinese University.  
[3] Technical Approach / Deepfake Detection Project Proposal, project team document.  
[4] Carlini, N., & Farid, H. (2020). "Evading Deepfake-Image Detectors With White- and Black-Box Attacks." CVPR Workshops.  
[5] Jia, S., Ma, C., Yao, T., Yin, B., Ding, S., & Yang, X. (2022). "Exploring Frequency Adversarial Attacks for Face Forgery Detection." CVPR.  
[6] Panariello, M., Ge, W., Tak, H., Todisco, M., & Evans, N. (2023). "Malafide: A Novel Adversarial Convolutive Noise Attack Against Deepfake and Spoofing Detection Systems." Interspeech 2023.  
[7] MITRE. Adversarial Threat Landscape for Artificial-Intelligence Systems (ATLAS), including AML.T0015 and AML.T0018.  
[8] Coalition for Content Provenance and Authenticity (C2PA). C2PA Technical Specification and Security Considerations.  
[9] NIST National Vulnerability Database. CVE-2011-3318, Cisco Video Surveillance IP Camera denial-of-service vulnerability.  
[10] NIST National Vulnerability Database. CVE-2025-14747, Ningyuanda TC155 RTSP Service denial-of-service vulnerability.  
[11] NIST National Vulnerability Database. CVE-2026-56699, Wazuh Manager NDJSON injection vulnerability.  
[12] NIST National Vulnerability Database. CVE-2026-25790 and CVE-2026-34150, Wazuh analysis-engine availability/integrity vulnerabilities.  
[13] Target Corporation. "Updates on Target's security and technology enhancements," Apr. 29, 2014.  
[14] NIST SP 800-57. Recommendation for Key Management. National Institute of Standards and Technology.
