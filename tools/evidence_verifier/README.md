# AEGIS Independent Offline Evidence Verifier (`aegis_verify.py`)

A standalone, **zero-dependency**, air-gapped CLI verifier for AEGIS cryptographic evidence bundles.  
A reviewer, opposing counsel, or teammate can verify genuine and tampered bundles using **only `aegis_verify.py` and Python 3.10+** — with **no access** to the running AEGIS server, Docker containers, orchestrator DB, or third-party `pip` packages.

---

## 1. Quickstart (No AEGIS Stack Required)

Copy `aegis_verify.py` (or the `tools/evidence_verifier/` folder) to any machine with Python 3.10+ installed:

```bash
# Verify a single genuine bundle
python tools/evidence_verifier/aegis_verify.py tools/evidence_verifier/sample_bundles/genuine_video_bundle.zip --verbose --inspect

# Verify a tampered bundle (exits with code 1 and reports exact tampering check that failed)
python tools/evidence_verifier/aegis_verify.py tools/evidence_verifier/sample_bundles/tampered_verdict_flip.zip --verbose

# Verify all sample bundles in a directory at once
python tools/evidence_verifier/aegis_verify.py tools/evidence_verifier/sample_bundles/

# Emit structured JSON for automated pipelines / audit logs
python tools/evidence_verifier/aegis_verify.py tools/evidence_verifier/sample_bundles/genuine_multimodal_bundle.zip --json
```

You can also unzip any bundle to a folder and point `aegis_verify.py` at the extracted directory:

```bash
python tools/evidence_verifier/aegis_verify.py path/to/extracted_bundle_dir/ --verbose
```

---

## 2. What the Verifier Checks

Each unified AEGIS bundle (`*_signed_bundle.zip`) contains:
- `evidence.json` — full evidentiary record (`input_hash`, detector scores, `model_versions`, `calibration_version`, full 3-round `judge_transcript`, ledger hashes & record signature)
- `report.md` — human-readable court-admissible forensic narrative
- `payload/<sha256>.<ext>` — original raw media file or surveillance frame
- `hashes.sha256` — SHA-256 manifest covering `evidence.json`, `report.md`, and `payload/*`
- `bundle_signature.sig` — cryptographic HMAC-SHA256 seal binding `hashes.sha256` and `evidence.json`
- Optional `seal.json` / `checkpoint.json` — Ed25519 asymmetric node seal & RFC 3161 trusted timestamp

`aegis_verify.py` executes **six independent cryptographic checks** (all stdlib-only):

| Step | Check Name | What It Proves |
|---|---|---|
| 1 | `artifact_presence` | All mandatory bundle files (`evidence.json`, `report.md`, `hashes.sha256`, `bundle_signature.sig`, `payload/*`) are present. |
| 2 | `manifest_hashes` | Every file listed in `hashes.sha256` matches byte-for-byte, and critical files are not omitted from the manifest. |
| 3 | `bundle_signature` | `bundle_signature.sig` digests match the actual `hashes.sha256` and `evidence.json`, and the HMAC-SHA256 signature verifies via constant-time `hmac.compare_digest`. |
| 4 | `payload_binding` | The raw media/frame file inside `payload/` hashes to the exact `input_hash` / `primary_frame.sha256` claimed inside `evidence.json`. |
| 5 | `ledger_chain_hash` | Recomputes canonical `manifest_digest` and verifies `SHA256(prev_record_hash:record_id:created_at_utc:manifest_digest) == record_hash`. |
| 6 | `record_signature` | Verifies the ledger record's HMAC-SHA256 signature against `record_hash`. |
| 7 *(optional)* | `ed25519_seal` | When `--trusted-keys <trusted_keys.json>` (and optionally `--tsa-cert <tsa.pem>`) are supplied, verifies asymmetric Ed25519 origin authenticity and RFC 3161 trusted timestamping. |

### Exit Codes
- `0` — All target bundle(s) passed every cryptographic check.
- `1` — One or more bundle(s) failed verification (missing file, hash mismatch, forged signature, or broken ledger chain).
- `2` — Usage / CLI argument error (e.g., unreadable `--key-file` or empty target directory).

---

## 3. Expected Output Examples

### Genuine Bundle (`--verbose --inspect`)
```text
[PASS] tools\evidence_verifier\sample_bundles\genuine_video_bundle.zip
       Record ID: VER-20261124-video-demo-vid | Modality: video | Verdict: SYNTHETIC | Files Verified: 3
         [OK] artifact_presence: All required artifacts present (4 core files + payload/...)
         [OK] manifest_hashes: All 3 SHA-256 checksums matched byte-for-byte
         [OK] bundle_signature: HMAC-SHA256 bundle signature valid (...)
         [OK] payload_binding: Raw payload SHA-256 matches evidence manifest (...)
         [OK] ledger_chain_hash: Ledger chain hash valid (...)
         [OK] record_signature: Record HMAC-SHA256 signature valid (...)
```

### Tampered Bundle (`tampered_verdict_flip.zip --verbose`)
```text
[FAIL] tools\evidence_verifier\sample_bundles\tampered_verdict_flip.zip
       Reason: SHA-256 mismatch for 'evidence.json' (expected ..., got ...)
         [OK] artifact_presence: All required artifacts present (4 core files + payload/...)
         [XX] manifest_hashes: SHA-256 mismatch for 'evidence.json' (...)
```

---

## 4. Custom Signing Keys & Production Asymmetric Verification

For deployments using non-default HMAC keys or Ed25519 node keyrings:

```bash
# Custom HMAC secret via environment variable
AEGIS_VAULT_SIGNING_KEY="prod-hmac-secret" python tools/evidence_verifier/aegis_verify.py bundle.zip

# Custom HMAC key from file
python tools/evidence_verifier/aegis_verify.py bundle.zip --key-file /path/to/vault.key

# Full asymmetric Ed25519 + RFC 3161 TSA verification (requires security/forensics keyring module)
python tools/evidence_verifier/aegis_verify.py bundle.zip --trusted-keys trusted_keys.json --tsa-cert tsa.pem
```

---

## 5. Independent Teammate Verification Protocol (Demo Sign-Off)

To validate zero-reliance portability, a second team member should perform this test on a clean shell (without starting Docker, Orchestrator, or reading `aegis_verify.py` source code):

1. Read only Sections 1–2 of this `README.md`.
2. Run each of the 11 sample bundles in [`sample_bundles/`](sample_bundles/MANIFEST.md) using `python tools/evidence_verifier/aegis_verify.py <bundle.zip> --verbose`.
3. Confirm that all **6 genuine bundles** exit `0` (`[PASS]`) and all **5 tampered bundles** exit `1` (`[FAIL]`) with clear diagnostic reasons:

| Bundle File | Expected Outcome | Verifier Exit Code | Teammate Verified? |
|---|---|---|---|
| `genuine_video_bundle.zip` | `[PASS]` (`video`, `SYNTHETIC`) | `0` | `[ ]` |
| `genuine_audio_bundle.zip` | `[PASS]` (`audio`, `SYNTHETIC`) | `0` | `[ ]` |
| `genuine_image_bundle.zip` | `[PASS]` (`image`, `AUTHENTIC`) | `0` | `[ ]` |
| `genuine_text_bundle.zip` | `[PASS]` (`text`, `SYNTHETIC`) | `0` | `[ ]` |
| `genuine_multimodal_bundle.zip` | `[PASS]` (`multimodal`, `SYNTHETIC`) | `0` | `[ ]` |
| `genuine_live_alert_bundle.zip` | `[PASS]` (`live_surveillance`, `HASH_CHAIN_BREAK`) | `0` | `[ ]` |
| `tampered_verdict_flip.zip` | `[FAIL]` (`manifest_hashes` mismatch on `evidence.json`) | `1` | `[ ]` |
| `tampered_payload_swap.zip` | `[FAIL]` (`manifest_hashes` mismatch on `payload/*`) | `1` | `[ ]` |
| `tampered_report_markdown.zip` | `[FAIL]` (`manifest_hashes` mismatch on `report.md`) | `1` | `[ ]` |
| `tampered_forged_signature.zip` | `[FAIL]` (`bundle_signature` HMAC failure) | `1` | `[ ]` |
| `tampered_missing_signature.zip` | `[FAIL]` (`artifact_presence` missing `.sig`) | `1` | `[ ]` |
