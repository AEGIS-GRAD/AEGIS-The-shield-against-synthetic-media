# AEGIS Container & Supply-Chain Hardening Report (Week 11 Task 5)

**Branch:** `feat/week11-task5-container-supply-chain`  
**Tools Executed:** `gitleaks v8.30.1`, `pip-audit 2.10.1`, `npm audit` (Node/npm), `trivy v0.76.2`  
**Artifact Directory:** `security/supply_chain/`

---

## 1. Executive Summary (Before vs. After Remediation)

| Check | Baseline Finding | Remediation Applied | Post-Fix Observed Result |
| :--- | :--- | :--- | :--- |
| **Secret Scan (`gitleaks`)** | 1 historical match (`web/src/app/developer/api/page.tsx:14` curl dummy key `aegis-secret-key-change-in-prod`); 25 local untracked `.key`/`.next` hits on `dir` scan | Replaced UI snippet key with `<YOUR_INTERNAL_API_KEY>`; added [`.gitleaks.toml`](../../.gitleaks.toml) scoping untracked build caches/ephemeral certs and verified example literal | **`0` leaks** across all 197 git commits (`gitleaks detect`) and `230.16 MB` working tree (`gitleaks dir`) |
| **Python Dependency Audit (`pip-audit` + `trivy fs`)** | Open `>=` bounds hid `requirements*.txt` from static lock scanners; `venv` audit found **51 CVEs across 4 packages** (`pillow==12.3.0`, `gitpython==3.1.61`, `opentelemetry-api==1.45.0`, `setuptools==84.0.0`); Dockerfiles & CI pinned **`torch==2.2.2+cpu` (24 CVEs)** | Pinned exact `==` versions across all 18 `requirements*.txt` files (creating missing files for `ingestion` and `rtsp_bridge`); upgraded PyTorch to `2.14.1` and pinned `facenet-pytorch==2.5.3` cleanly | **`0` vulnerabilities** across all 18 `requirements*.txt` files verified by both `pip-audit -r` and `trivy fs` |
| **Web Dependency Audit (`npm audit` + `trivy fs`)** | `44` Trivy CVEs / `21` npm audit advisories (`5` CRITICAL `next==15.1.7`, `15` HIGH including `sharp`/`postcss`, `5` MODERATE); `web/Dockerfile` used `npm install` | Upgraded `next` and `eslint-config-next` to exact `15.5.29`; switched [web/Dockerfile](../../web/Dockerfile) to `npm ci` + `node:22.23.5-alpine` | **`0` CRITICAL CVEs**; Trivy `web/package-lock.json` dropped from 44 to **4 transitive `postcss==8.4.31`** findings; `npm audit --omit=dev` shows **0 critical** (2 bundled `next/postcss` findings) |
| **Dockerfile & Compose Hardening (`trivy config`)** | **12× HIGH (`DS-0002` root user)** and **3× LOW (`DS-0026` missing `HEALTHCHECK`)**; `:latest`/unpinned tags; no `read_only`, `cap_drop`, or `no-new-privileges` | Added non-root `USER` (`appuser` UID `10001` / `node`) and `HEALTHCHECK` to all 12 Dockerfiles; pinned Compose tags; added `read_only: true`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `tmpfs` scratch mounts, and `AEGIS_DB_PATH` | **`0` misconfigurations** across all 12 Dockerfiles in `trivy config`; `docker compose config` passes for base + mTLS overlays |
| **Model Weights & Checkpoints** | Unsafe `torch.load(...)` without `weights_only=True` (`aasist`, `syncnet`, `video-classifier` fallback to `weights_only=False`, `rppg`, `edge_model`); unpinned HuggingFace snapshots without SHA-256 checks | Created [`weights_sha256.json`](../supply_chain/weights_sha256.json) + [`model_integrity.py`](../supply_chain/model_integrity.py); removed `weights_only=False` fallback; enforced `weights_only=True`, pinned HF `revision` commits, and SHA-256 verification | **`9 passed`** in `security/tests/test_supply_chain_hardening.py` (verifying tamper rejection and pickle RCE gadget blocking) |
| **SBOM & CI Automation** | No SBOM; no automated security scanning workflows | Exported CycloneDX 1.7 SBOM (`358` components) and added [`.github/workflows/ci-security-supply-chain.yml`](../../.github/workflows/ci-security-supply-chain.yml) | Runs Gitleaks, `pip-audit`, `npm audit`, `trivy config/fs/image`, CycloneDX SBOM upload, and pytest policy gates on every PR |

---

## 2. Model Weight SHA-256 Registry & Pinned Revisions

Canonical manifest: [`security/supply_chain/weights_sha256.json`](../supply_chain/weights_sha256.json).

| Artifact Path | Source / Pinned Revision | Loader Policy | SHA-256 Digest |
| :--- | :--- | :--- | :--- |
| `detectors/image/weights/model.safetensors` | `OwensLab/commfor-model-384` @ `6076002bf0d9dd37537f965ee2f06f826c333b61` | `safetensors` + SHA-256 | `b89f36275f3bf5e2b040eee36597a8f19db051bff9a473a9cf7b2466284fb387` |
| `detectors/text-detector/models/desklib-base/model.safetensors` | `desklib/ai-text-detector-v1.01` @ `5fdea974cd4287c61674951ec78803aa274e2fb7` | `safetensors` + `trust_remote_code=False` | `c024a1704c65f5a4bffeda58745c58fc0ed67d6ca07b158b068a257238815265` |
| `detectors/text-detector/models/desklib-finetuned/lora_adapter/adapter_model.safetensors` | Tracked in git | `safetensors` + SHA-256 | `dba5608b7f771fa38dce1c8148f874d46bc5d1bde6fb2e8a780f525c5044d93b` |
| `detectors/text-detector/models/gpt2/model.safetensors` | `openai-community/gpt2` @ `607a30d783dfa663caf39e06633721c8d4cfcd7e` | `safetensors` + `trust_remote_code=False` | `248dfc3911869ec493c76e65bf2fcf7f615828b0254c12b473182f0f81d3a707` |
| `detectors/aasist/AASIST.pth` | Tracked in git | `weights_only=True` + SHA-256 | `51d2d9cf0738172f61e2a384ec50a54a55363240f67c971ed55a92435bc1a1c0` |
| `detectors/video-classifier/models/efficientnet_b0_ffpp_finetuned.pth` | Tracked in git | `weights_only=True` + SHA-256 | `5622d78b079927a84a86f8d8545ac76e11130e6d3cbaf7c517ac90e2740f271a` |
| `detectors/video-classifier/models/efficientnet_b0_ffpp_c23.pth` | `Xicor9/efficientnet-b0-ffpp-c23` @ `21aebf2d1c8a7ba85eb61734884c50c877c38ea3` | `weights_only=True` + SHA-256 | `2a7963b787ece2594a79160f20e53d6bc621f6bfe34ee21d139efa81bcb70c84` |
| `detectors/video-classifier/models/efficientnet_b0_ffpp_ckpt_ep10.pth` | Tracked training resume checkpoint | `weights_only=True` + `safe_globals([WindowsPath, PosixPath])` | `b193f32b4bd4b492bce6b4fe72fe39d2e24608315e368f08987bb64cbf1b586e` |
| `engine/edge_model/mobilenetv3_small_ffpp.pth` | Tracked in git | `weights_only=True` + SHA-256 | `789ae9b3345d6dfb606fd711a6df3d9af22a787e15f97a9a4fb8fa614f31c176` |
| `engine/edge_model/mobilenetv3_small_fp32.onnx` | Tracked in git | ONNX static graph | `7a4de0d4d28f186fbdce7ec7d6f89b5be08ff4e28ff922d5fbbfa7e457711bd4` |
| `engine/edge_model/mobilenetv3_small_int8.onnx` | Tracked in git | ONNX static INT8 graph | `ba3d6dcf922586150aadb7ada993619f419a0161e87eacbe602f52eff0a54420` |

---

## 3. Residual Risks & Verification Scope

1. **Bundled `postcss` in `next@15.5.29`:** Next.js 15 bundles an internal copy of `postcss<=8.5.22` whose upstream fix (`next@16.4.6`) is a breaking major upgrade. Since Next.js uses `postcss` at compile/build time rather than evaluating untrusted runtime CSS payloads, `ci-security-supply-chain.yml` fails the web runtime audit gate on `critical` while logging `high` advisories until a planned Next.js 16 migration.
2. **Local Docker Daemon Image Build Scan:** Local verification ran `docker compose config -q` (both base and mTLS overlays) plus static `trivy config`, `trivy fs`, and CycloneDX SBOM generation; full container image builds (`docker build` + `trivy image`) execute in GitHub Actions via `.github/workflows/ci-security-supply-chain.yml` (local Windows Docker Desktop daemon was not running and host OS disk had minimal free capacity).
3. **`api_gateway` Capabilities:** `nginx:1.31.8-alpine` retains minimal `cap_add` (`NET_BIND_SERVICE`, `CHOWN`, `SETUID`, `SETGID`) after `cap_drop: [ALL]` so Nginx can bind `:80` and drop to its worker user; moving edge Nginx onto an unprivileged `:8080` listener (`nginx-unprivileged`) would allow zero added capabilities in a future iteration.
