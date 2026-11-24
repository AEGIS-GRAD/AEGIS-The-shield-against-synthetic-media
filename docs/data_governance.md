# AEGIS Privacy & Data Governance Review

- **Document Status:** Approved Review Deliverable (Week 12 — Task 5)
- **System Scope:** AEGIS Multimodal Deepfake Verification Platform (File Upload Orchestrator, Live mTLS/RTSP Surveillance Pipeline, Evidence Vault, MCP Server, Evaluation Suite, and RQ3 User Study)
- **Applicable Frameworks:** GDPR (Principles of Lawfulness, Purpose Limitation, Data Minimization, Storage Limitation — Articles 5 & 9), US Illinois BIPA / analogous biometric guardrails, Egypt Personal Data Protection Law (Law No. 151/2020), and ISO/IEC 27037:2012 (Digital Evidence Chain of Custody).

> [!NOTE]
> AEGIS currently operates as an **academic / non-commercial graduation research platform**. Because several benchmark datasets and upstream model checkpoints enforce **Non-Commercial / Research-Only** licenses, commercial production deployment requires replacing tainted models/datasets and remediating the operational privacy gaps flagged in the Compliance Checklist (§8).

---

## 1. Data Inventory & Retention Periods

| Data Category | Storage Location / Component | What Is Stored | Default Retention | Deletion / Lifecycle Mechanism | Compliance Status |
|---|---|---|---|---|---|
| **Orchestrator Upload Staging** | `tempfile.NamedTemporaryFile` in [`orchestrator/app/main.py`](../orchestrator/app/main.py) | Uploaded video, audio, image, or text payload during active inference | **0 seconds post-request** (ephemeral duration of `/orchestrate` call) | Unconditionally deleted in `finally: os.remove(tmp_path)` | **Enforced** |
| **Operational Audit DB** | `orchestrator/app/flight_recorder.db` ([`orchestrator/app/db.py`](../orchestrator/app/db.py)) | `RequestLog` & `JudgeAuditLog`: job IDs, detector scores, latencies, verdicts, debate transcripts (**no raw media bytes**) | **90 days** recommended operational window (configurable purge cron) | Automated SQLite row pruning (`created_at_utc < NOW() - 90d`) | **Policy Defined** *(needs cron)* |
| **Unified Evidence Vault** | `security/vault/` ([`security/forensics/evidence_vault.py`](../security/forensics/evidence_vault.py)) | Content-addressed media blobs (`blobs/`), verification manifests (`verifications/`), live surveillance alert frames (`incidents/`), MCP call hashes (`mcp_audits/`), `ledger.jsonl`, `checkpoints.jsonl` | **180 days** active forensic hold; **1–7 years** if locked under legal hold (non-case routine blobs purged after 30 days) | Vault blobs are immutable for FRE 902 integrity; GDPR erasure handled via **cryptographic shredding / key disposal or anonymized tombstone record** preserving chain hashes | **Partial** *(requires legal-hold TTL policy)* |
| **Live Surveillance Frame Buffers** | RAM sliding windows in `live_pipeline/`, `security/gateway/ingestion/server.py`, `rtsp_bridge` | Rolling RGB frames (16–32 frame window) + rolling SHA-256 chain hashes | **< 30 seconds in RAM only** (never written to disk for clean frames) | Overwritten in circular memory buffer unless Tier-1/Tier-2 incident triggers `store_incident()` | **Enforced** |
| **SIEM Alert Router & DLQ** | `security/incident_response/alert_router.py` | Alert tier, incident ID, camera ID, PRNU PCE, error telemetry | **90 days** (or 1 year for `P1_CRITICAL` security incidents) | Auto-purged from DLQ upon confirmed Wazuh/SIEM delivery + age cutoff | **Policy Defined** |
| **Prometheus / Grafana Metrics** | Prometheus TSDB (`docker-compose.yml`) | Aggregate counters & latency histograms (`detector_inference_latency_seconds`, `circuit_breaker_state`) | **15 days** (Prometheus default TSDB retention) | Automatic TSDB block compaction & expiry; contains **zero PII or media content** | **Enforced** |
| **RQ3 User Study Client State & Exports** | Browser `localStorage` (`aegis-rq3-study-v1` in [`web/src/app/study/page.tsx`](../web/src/app/study/page.tsx)) + downloaded CSV/JSON | Pseudonymized participant ID (`pid`), fictional scenario choices, Likert ratings, completion timestamps | **In-session only** for `localStorage`; study exports retained **until graduation defense + 30 days** (re-identification mapping purged) | Manual/facilitator browser storage clear at session end; anonymized CSV retained for paper reproducibility | **Requires Clear Step** |
| **Evaluation Datasets & Subsets** | External drives per [`eval/config/data_paths.yaml`](../eval/config/data_paths.yaml) + gitignored `eval/data/` | Third-party academic video/audio/image/text benchmarks | **Duration of academic evaluation only** | Raw data kept outside Git repo; wiped upon project archival or custodian request | **Enforced** |

### Tension Between ISO/IEC 27037 Immutability and Privacy Erasure
Under GDPR Art. 17, data subjects may request erasure of uploaded faces/voices, whereas forensic vaults require an unbroken hash chain (`H_k = SHA256(H_{k-1} || manifest_digest)`). AEGIS resolves this with two operational rules:
1. **Opt-out / Ephemeral Analysis Mode:** Non-forensic interactive previews should bypass `store_verification()` persistence (retaining `0s` raw media).
2. **Tombstone Redaction on Deletion Requests:** Where an incident/verification blob must be erased prior to legal hold expiry, erase `blobs/<prefix>/<sha256>.*` (marking the record `REDACTED_BY_PRIVACY_REQUEST`) and log an audited revocation event so chain continuity of remaining records remains mathematically auditable.

---

## 2. Handling of Faces and Voices in Uploaded Media (Biometric Privacy)

Under GDPR Article 9 and Illinois BIPA, processing facial geometry or vocal acoustics **for unique identification** constitutes special-category biometric processing. AEGIS processes facial and vocal signals **strictly for manipulation/artifact forensics, never for identity recognition**:

| Service / Module | Facial / Vocal Signal Extracted | Persistent Biometric Storage? | Identity Matching / Enrollment? | Data-Minimization Control |
|---|---|---|---|---|
| **Video Classifier** (`detectors/video-classifier/`) | Sampled frames (every 10th frame), MTCNN 224x224 face crops | **None** (`in-memory tensor only`) | **No** (`nn.Linear(1280, 2)` Real vs. Fake logit only) | Face crops destroyed after forward pass; only scalar score returned. |
| **SyncNet** (`detectors/syncnet/`) | Lower-40% mouth ROI (5-frame window) + 16 kHz MFCC speech slices | **None** (`in-memory tensor only`) | **No** (audio-visual cross-correlation distance only) | Short-window local sync verification; zero transcript or speaker ID stored. |
| **rPPG & Streaming rPPG** (`detectors/rppg/`) | Facial skin chrominance ROI (green/CHROM reflectance band) | **None** (`NumPy array discarded post-window`) | **No** (cardiac BPM & spectral purity `[40-180 BPM]` only) | Physiological liveness signal cannot reconstruct identity; `motionless_face` & `not_applicable` prevent forced full-frame fallbacks. |
| **AASIST** (`detectors/aasist/`) | Mono 16 kHz waveform standardized to 64,600 samples (~4.04s) | **None** (`deleted post-inference`) | **No** (spoof vs. bonafide countermeasure classifier; ASV protocols ignored) | Explicitly avoids speaker-verification/voiceprint embeddings (`eval/DATA.md`: ASV ignored, CM only). |
| **Image Detectors** (`detector_image` MIRROR / `image` CommFor) | 384x384 / full-frame RGB spatial features + FFT/DCT grid & EXIF container checks | **None** | **No** | No face database lookup or reverse-image identity search. |
| **PRNU Sensor Fingerprinting** (`security/forensics/prnu.py`) | Camera photo-response non-uniformity noise residual (`W_cam`) | Enrolled **camera** baselines (`camera-001.npy`) | **Device hardware only, non-biometric** | Measures silicon sensor pattern noise on mTLS-authenticated CCTV cameras, not human faces. |

### Safeguards Required Before Handling Live Human Media at Scale
- **Transport Encryption:** All inter-service detector dispatch (`mesh_tls.py`) and live camera feeds (`security/gateway/ingestion/server.py`, `rtsp_bridge`) enforce **mutual TLS (mTLS)** with rotated X.509 device certificates (`security/transport/device_lifecycle.py`).
- **Explicit Consent Banner:** Interactive web uploads (`/analyze`) must display a concise notice stating that faces/voices are processed ephemerally for manipulation detection and whether forensic vault retention is active.

---

## 3. Log Scrubbing & Telemetry Hygiene

AEGIS enforces structured sanitization boundaries before untrusted filenames, EXIF metadata, detector text, or MCP arguments enter LLM prompts, audit ledgers, or application logs.

### Controls Already Verified in Codebase
1. **Path & Metadata Scrubbing (`debate/prompt_security.py`):**
   - `sanitize_filename()` strips directory paths (`os.path.basename`), removes Unicode control/bidi (`Cc`/`Cf`) characters, neutralizes prompt delimiters, and truncates to `100` chars.
   - `sanitize_exif_metadata()` enforces a strict 16-key allowlist (`ALLOWLISTED_META_KEYS`: `title`, `comment`, `artist`, `author`, `description`, `software`, `make`, `model`, `creation_time`, `encoder`, `copyright`, `user_comment`, `imagedescription`, `xpcomment`, `keywords`, `subject`), dropping GPS coordinates (`GPSLatitude`, `GPSLongitude`), device owner serials, and unallowlisted PII tags before prompt construction or logging.
   - `sanitize_claim_text()` and `sanitize_flags()` enforce length bounds (`512` / `64` chars) and scrub injection strings before `JudgeAgent` logging.
2. **MCP Token & Argument Redaction (`mcp/mcp_security.py`):**
   - `_summarize_args_for_audit()` unconditionally rewrites `auth_token` to `"[REDACTED]"` and stores only SHA-256 digests (`args_sha256`, `result_sha256`) plus truncated summaries (`<= 200` chars) inside `MCPAuditRecord`.
   - `MCPAuthManager` hashes bearer tokens with SHA-256 (`_hash_token`) and compares digests using constant-time `hmac.compare_digest`.
3. **Supply-Chain & Secret Scanning (`.github/workflows/ci-security-supply-chain.yml`, `.gitleaks.toml`):**
   - Automated Gitleaks secret scanning blocks credentials from entering Git history or CI logs.

### Concrete Codebase Audit Findings (Actionable Gaps)
| Finding ID | File & Line Reference | Issue Observed | Required Remediation | Severity |
|---|---|---|---|---|
| **LS-01** | [`orchestrator/app/main.py`](../orchestrator/app/main.py) lines 72 & 82 | `logger.warning(f"Unauthorized API key attempt...: '{api_key_header}'")` logs rejected `X-API-Key` credentials verbatim in plaintext logs (risking log disclosure of slightly mistyped production keys). | Redact to `f"sha256:{hashlib.sha256(api_key_header.encode()).hexdigest()[:12]}"` or `"[REDACTED]"`. | **High** |
| **LS-02** | [`orchestrator/app/main.py`](../orchestrator/app/main.py) line 233 & `log_decision()` | Logs `file.filename` (`safe_filename`); should verify user-supplied filenames do not embed emails/national IDs by truncating/anonymizing or hashing filenames in long-term SIEM telemetry. | Prefer `job_id` + `sha256[:12]` as log correlation ID; reserve raw `safe_filename` for sealed case manifests only. | **Medium** |
| **LS-03** | Text Upload Pipeline (`detectors/text-detector/app.py`, `orchestrator`) | Uploaded `.txt`/`.md` documents can contain personal correspondence or confidential text. | Confirm raw text content is **never** logged in `uvicorn`/FastAPI debug tracebacks or Prometheus labels; store only text hash unless `store_verification()` vault export is explicitly requested. | **Medium** |
| **LS-04** | Shared Docker Volume & Debug Traces | `tracebacks` in `main.py` line 441 log `traceback.format_exc()`, which must remain free of uploaded document text or `OPENROUTER_API_KEY`. | Audit exception handlers so payload variables are excluded from error strings. | **Low** |

---

## 4. Dataset License Compliance Matrix

All third-party datasets referenced in [`eval/DATA.md`](../eval/DATA.md), [`eval/config/data_paths.yaml`](../eval/config/data_paths.yaml), [`detectors/video-classifier/README_df40_finetune.md`](../detectors/video-classifier/README_df40_finetune.md), [`capability_manifests/detector_text.json`](../capability_manifests/detector_text.json), and [`eval/adaptive_robustness/`](../eval/adaptive_robustness/) are stored **outside Git** (enforced via `.gitignore` ignoring `eval/data/` and `data/`).

| Dataset | Modality | License / Legal Terms | Commercial Use Allowed? | Key Compliance Obligations & Repo Restrictions |
|---|---|---|---|---|
| **FaceForensics++ (FF++ c23)** (`xdxd003/ff-c23` mirror / TUM official) | Video & cropped frames | **FaceForensics++ Custom Non-Commercial Research License** (TUM) | **No** | Official TUM access form required for formal publication; zero redistribution; raw files strictly external (`D:/archive/FaceForensics++_C23`); **taints downstream FF++ / DF40-trained video weights as research-only**. |
| **ASVspoof 2019 Logical Access (LA)** | Audio (speech) | **Open Data Commons Attribution (ODC-By 1.0)** (Univ. of Edinburgh DataShare) | Yes *(with attribution)* | Cite/attribute challenge organizers; use **LA partition only** (PA replay ignored); ignore ASV speaker-ID scores. |
| **OpenFake & OpenFake Reddit Split** (`eval/config/data_paths.yaml`) | Image | **Mixed per-generator / per-subset licenses** (documented explicitly in `eval/DATA.md`: *"non-commercial subsets exist; confirm per subset"*) | **Conditional (No if non-commercial subsets remain)** | Must audit `generator`/`license` column per subset in `manifest.csv`; strictly separate fine-tuning generators from held-out eval generators; strip non-commercial subsets before any commercial weight training. |
| **DF40 Benchmark** (`detectors/video-classifier/finetune_efficientnet_df40.py`) | Video | **Academic / Non-Commercial Institutional Agreement** | **No** | Access request logged; 27 training methods + 3 held-out (`uniface`, `wav2lip`, `VQGAN`); StyleGAN3 excluded due to byte-duplicate decontamination against StyleGAN2. |
| **Celeb-DF v2** | Video | **Non-Commercial Research Use Only** | **No** | Zero identity overlap permitted with FF++ training splits (`eval/DATA.md`); no redistribution. |
| **Wild Deepfake** | Video | **Research Only** | **No** | Academic evaluation benchmark; raw frames kept external. |
| **Deepfake-Eval-2024** | Video / Multimodal | **CC-BY-NC** (Non-Commercial) | **No** | Attribution required; evaluation-only zero-shot benchmark. |
| **DeepSpeak v2** | Audio / Speech | **Restricted Research License** | **No** | Access gated by dataset custodians; cross-modal audio eval only. |
| **CNN / DailyMail** (`eval/DATA.md` Task 4 human text) | Text | **Apache-2.0 script / underlying publisher article copyrights** (verify terms) | **Restricted** | Verify publisher terms for bulk commercial redistribution; restrict to non-commercial academic human-text eval baseline. |
| **ESC-50** (`eval/DATA.md` Task 6 audio guardrail) | Non-speech audio | **CC BY-NC 3.0** | **No** | Attribution required; used solely as non-speech negative control (`not_applicable` guardrail). |
| **RAID (`liamdugan/raid`) & MAGE** | Text | **MIT / Apache-2.0 / Academic Research Benchmarks** *(check per-generator output terms inside RAID)* | Conditional | Used in Desklib v1.01 training & LoRA adaptation; retain attribution and generator-license checks. |
| **AEGIS Adaptive Hard Negatives** (`eval/datasets/hard_negatives/`) | Image / Video / Text | **Project-generated synthetic adversarial fixtures** (Apache/project internal) | Yes *(subject to source seed provenance)* | Committed lightweight evaluation fixtures (`24` samples) for reproducibility of Week 11 Task 3 & Alignment Study B. |

---

## 5. Model & External API License Terms

| Model / External Service | Used In | License / Terms | Commercial Eligibility | Data Egress & Governance Constraints |
|---|---|---|---|---|
| **Video Classifier — EfficientNet-B0 DF40** (`efficientnet_b0_df40_finetuned.pth`, promoted default) & **FF++ Baseline** (`ffpp_legacy_baseline/`) | `detectors/video-classifier/`, `engine/` | Code: `torchvision` BSD-3-Clause; **Weights trained on FF++ C23 + DF40 -> Non-Commercial Research Only** | **No** *(training-data taint)* | Weight hashes pinned in [`security/supply_chain/weights_sha256.json`](../security/supply_chain/weights_sha256.json); safe `weights_only=True` enforced at load. |
| **Community Forensics** (`OwensLab/commfor-model-384`, ViT-Small) | `detectors/image/`, `capability_manifests/image.json` | **MIT License** (repo/checkpoint) | **Verify upstream training mix** | Trained on 2.7M community generator images + OpenFake subset — check OpenFake non-commercial subset taint before commercializing. |
| **MIRROR (DINOv3-L)** | `detectors/detector_image/`, `capability_manifests/detector_image.json` | **Research & Non-Commercial License** (`github.com/349793927/MIRROR`) + Meta DINOv3 license terms | **No** | Explicit `Non-Commercial` restriction documented directly in `capability_manifests/detector_image.json` line 49. |
| **Desklib AI Text Detector v1.01** (`microsoft/deberta-v3-large` + AEGIS LoRA) + **GPT-2** + **Qwen-0.5B** (opt-in Binoculars) | `detectors/text-detector/`, `capability_manifests/detector_text.json` | **MIT License** (Desklib, DeBERTa-v3, GPT-2); **Apache-2.0** (Qwen2.5-0.5B) | **Yes** *(clean permissive chain)* | Cleanest open-source licensing across all AEGIS detectors; LoRA weights scoped to non-PII text evaluation. |
| **AASIST** (NAVER / Clova AI) | `detectors/aasist/` | **MIT License** (code & ODC-By 1.0 ASVspoof LA weights) | **Yes** *(with ODC-By attribution)* | Trained purely on ASVspoof 2019 LA (CC/ODC-By attribution required). |
| **rPPG (CHROM classical DSP)** | `detectors/rppg/` | **Project native signal-processing code** (no external NN weights) | **Yes** | Runs locally without learned weights or external calls. |
| **SyncNet** (Oxford VGG architecture) | `detectors/syncnet/` | **Academic / Non-Commercial Research License** | **No** | Requires commercial license clearance or replacement if deployed outside academic research. |
| **OpenRouter API** (`planner.py`, `debate/llm_client.py`) | Orchestrator Planner & Judge (`llm` mode) | **OpenRouter Terms of Service + downstream model provider terms** (e.g., NVIDIA Nemotron / community free endpoints) | Conditional (paid SLA required for zero retention) | **Privacy Rule:** Free-tier endpoints may retain prompts. Send **only sanitized metadata summaries and numerical detector claims** — never raw uploaded files, raw text bodies, unallowlisted EXIF tags, or participant PII. Use **Local Ollama (`qwen2.5:0.5b`)** for zero-egress air-gapped runs. |
| **Anthropic API** (`eval/scripts/task4_stage_text.py`) | Offline eval text generation | **Anthropic Commercial / API Terms** | Subject to Anthropic Acceptable Use & API Terms | Used strictly offline to generate synthetic benchmark passages for `eval/data/text_eval/`; never invoked at runtime on user uploads. |

---

## 6. Consent Handling for the RQ3 User Study (`web/src/app/study/`)

The AEGIS RQ3 Trust & Usability User Study ([`web/src/app/study/page.tsx`](../web/src/app/study/page.tsx), [`web/src/lib/study.ts`](../web/src/lib/study.ts)) investigates how full forensic evidence vs. single-score outputs affect human decision accuracy and calibrated trust across 8 scenarios (`S1..S8`).

### Implemented Privacy & Ethical Safeguards in `/study`
1. **Zero Personal Media / Fictional Stimuli Invariant:** As enforced in [`web/src/lib/study.ts`](../web/src/lib/study.ts) (lines 7–8), every scenario (`S1..S8`) uses **100% fictional invented filenames, personas, and scores**. Participants are **never** asked to upload photos, videos, audio recordings, or personal text of themselves or third parties.
2. **Mandatory Three-Point Informed Consent Gate (`step === "consent"`):** Participants must review the information sheet and actively check all three statements (`CONSENT_STATEMENTS`, `study.ts` lines 389–393) before any scenario loads:
   - *Comprehension:* `"I have read the information sheet and I understand what the study involves."`
   - *Voluntary Withdrawal:* `"I understand that taking part is voluntary and that I can stop at any time without giving a reason."`
   - *Research Use of Anonymous Data:* `"I agree that my anonymous answers and timings may be used in the research."`
3. **Pseudonymized Session Identification:** Sessions use non-identifying participant codes (`pid`, e.g., `P01..P24`) for within-subject Latin-square counterbalancing (`buildSession(pid)`).
4. **Local-First Export Without Cloud Tracking:** Results export directly to local JSON (`StudyExport`) and CSV files (`scenarioCsv`, `postCsv`) controlled by the facilitator, with no third-party analytics trackers embedded in `/study`.

### Required Operational Protocol for Facilitators
- **Key Separation:** If a sign-up sheet links participant names/emails to `pid` codes for scheduling, store that mapping encrypted separately from exported `scenarioCsv` / `postCsv` datasets and **destroy the re-identification key within 30 days after graduation defense completion**.
- **Withdrawal & Browser Cleanup:** Because [`web/src/app/study/page.tsx`](../web/src/app/study/page.tsx) (line 143) saves in-progress state to browser `localStorage` (`aegis-rq3-study-v1`) to protect against accidental page refreshes, facilitators **must clear `localStorage.removeItem("aegis-rq3-study-v1")`** on shared lab machines immediately after exporting each participant's session (and immediately if a participant withdraws mid-study).
- **Minimal Demographics:** Collect only domain-relevant background (`experience` and `tools` familiarity levels in `BACKGROUND_ITEMS`) — never age, gender, ethnicity, or workplace identities unless explicitly approved by ethics review.

---

## 7. Independent Evidence Verifier Governance Note (Task 4 Integration)
With [`tools/evidence_verifier/aegis_verify.py`](../tools/evidence_verifier/aegis_verify.py), receiving auditors and opposing examiners verify exported evidence bundles **completely offline** without accessing AEGIS's live APIs, user database, or other tenants' records — enforcing least-privilege disclosure (`need-to-know` per-incident export only).

---

## 8. Privacy & Data Governance Compliance Checklist

| Check ID | Domain | Requirement / Control | Status | Repo Evidence / Location | Required Action |
|---|---|---|---|---|---|
| **DG-01** | Retention | Ephemeral upload temp files deleted immediately after inference | **COMPLIANT** | `orchestrator/app/main.py` lines 256, 444–445 | Verify exception paths never leak temp files on OOM/SIGKILL. |
| **DG-02** | Retention | Define & enforce purge schedule for `flight_recorder.db` (90d) and non-case vault blobs (180d) + legal-hold lock | **PARTIAL** | `orchestrator/app/db.py`, `security/forensics/evidence_vault.py` | Add scheduled retention cleanup job + privacy tombstone support for Art. 17 requests. |
| **DG-03** | Retention | Clear RQ3 study browser `localStorage` (`aegis-rq3-study-v1`) after each participant session | **PARTIAL** | `web/src/app/study/page.tsx` line 35 & 143 | Add explicit *"Reset / End Session & Wipe Browser Cache"* button for facilitators. |
| **DG-04** | Biometrics | No facial recognition / voiceprint identification DBs; ephemeral tensor-only face/voice processing | **COMPLIANT** | `detectors/{video-classifier,syncnet,rppg,aasist}/` | Maintain strict prohibition on speaker ID / face ID enrollment features. |
| **DG-05** | Biometrics | Enforce mTLS encryption on live camera & inter-detector biometric media transport | **COMPLIANT** | `security/gateway/ingestion/server.py`, `orchestrator/app/mesh_tls.py` | Ensure `AEGIS_SECURITY_PROFILE=prod` enables strict mTLS in production compose overlay. |
| **DG-06** | Log Scrubbing | Redact MCP bearer tokens & prompt-injection payloads before logging or persistence | **COMPLIANT** | `mcp/mcp_security.py`, `debate/prompt_security.py` | Keep `AEGIS_MCP_REQUIRE_AUTH=1` in non-dev deployments. |
| **DG-07** | Log Scrubbing | Never log rejected `X-API-Key` header secrets verbatim in warning logs (`main.py` lines 72 & 82) | **OPEN GAP** | `orchestrator/app/main.py` lines 72 & 82 | Replace raw `'{api_key_header}'` with truncated SHA-256 digest or `"[REDACTED]"`. |
| **DG-08** | Log Scrubbing | Strip EXIF GPS/device PII before LLM prompt construction or audit storage | **COMPLIANT** | `debate/prompt_security.py` (`ALLOWLISTED_META_KEYS`) | Add CI unit check verifying uploaded media EXIF GPS tags never reach logs or DB. |
| **DG-09** | Datasets | Keep all raw datasets external (`eval/config/data_paths.yaml`) & staging (`eval/data/`) gitignored | **COMPLIANT** | `.gitignore`, `eval/DATA.md` | Preserve external-only policy for any newly onboarded corpora. |
| **DG-10** | Datasets | Track & enforce **Non-Commercial** boundaries for FF++, DF40, Celeb-DF v2, Wild Deepfake, Deepfake-Eval-2024, DeepSpeak v2, ESC-50, and **OpenFake non-commercial subsets** | **COMPLIANT (Research)** | `eval/DATA.md`, `detectors/video-classifier/README_df40_finetune.md` | If transitioning to commercial SaaS, exclude non-commercial OpenFake subsets and replace FF++/DF40 sets. |
| **DG-11** | Models & APIs | Track model license terms (`MIRROR` NC, `Video Classifier` FF++/DF40 NC taint, `SyncNet` Academic vs. `Desklib`/`AASIST` MIT) | **COMPLIANT (Research)** | `capability_manifests/detector_image.json`, `detector_text.json`, `weights_sha256.json` | Commercial release must swap FF++/DF40, MIRROR, and SyncNet weights for commercially licensed equivalents. |
| **DG-12** | Models & APIs | Prevent raw media/PII egress to OpenRouter cloud LLMs; keep metadata-only + local Ollama option | **COMPLIANT** | `orchestrator/app/planner.py`, `debate/prompt_builder.py` | Mandate local Ollama (`AEGIS_LOCAL_LLM_ENABLED=1`) or paid zero-retention SLA in production. |
| **DG-13** | User Study | Enforce informed consent gate, fictional-only stimuli, pseudonymized IDs, and withdrawal data deletion | **COMPLIANT** | `web/src/app/study/page.tsx`, `web/src/lib/study.ts` | Destroy offline participant-to-`pid` re-identification sheets <= 30 days post-defense. |
