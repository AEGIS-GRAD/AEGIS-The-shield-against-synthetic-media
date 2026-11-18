# Forensic Soundness Test Report — Tampering, Trusted Time, Key Management

**Task:** Week 11 Cybersecurity Task 4 · **Owner:** Cyber team (digital forensics & chain of evidence)
**Date:** 2026-11-16 · **Test suite:** `security/tests/test_forensic_soundness.py` (26 tests, all passing)
**Related:** [key_management_and_custody.md](key_management_and_custody.md) · [evidence_admissibility_checklist.md](evidence_admissibility_checklist.md)

## 1. Summary

We attacked the evidence vault and the offline bundle verifier the way a motivated party in litigation would:
edit a stored report, delete records, replay or transplant bundles, back-date evidence, and swap model versions.
Each attack was run against the **legacy scheme** (HMAC-SHA256 under a key committed to the repository) and
against the **sealed scheme** introduced by this task (Ed25519 node keys, RFC 3161 trusted timestamps,
signed ledger checkpoints, model weight fingerprints).

**Before this task, every deliberate tampering attack that re-signed its edits succeeded.** The legacy HMAC key
(`aegis_surveillance_node_secret_key_v1`) is public in the repo, so anyone with a clone could recompute every record
hash and signature, and the vault audit *and* the offline verifier reported "PASS". The legacy scheme detected only
naive edits that did not bother to re-sign. After this task, all 12 attack variants are detected.

We also found and fixed three vault defects that were not on the attack list:

| ID | Defect | Impact | Fix |
|---|---|---|---|
| F-1 | Two vault instances on one directory race on the ledger head | Ingestion gateway and alert router each open their own vault on `security/vault/`. Without a lock the chain **forked in 5/5 trials** (15–23 broken links per 50 concurrent writes), invalidating every later record | Cross-process file lock around read-head/append (`_interprocess_lock`) |
| F-2 | `verification_id` = date + modality + `job_id[:8]` | Re-verifying the same job on the same day **overwrote the earlier record's manifest**, silently breaking append-only storage and the earlier record's audit | Random suffix on the id + exclusive-create (`open(..., "x")`) manifest writes |
| F-3 | Audit counted records as "verified" after unrelated failures | `verified_records` over-reported once any record failed | Per-record error accounting |

## 2. Attack matrix

"Legacy" = HMAC-only vault/verifier as shipped in Week 10. "Sealed" = with a trusted keyring and TSA certificate.

| # | Attack | Legacy result | Sealed result | Detected by | Test |
|---|---|---|---|---|---|
| 1a | Edit verdict in a stored manifest (no re-sign) | Detected | Detected | manifest digest | `test_attack_modify_report_naive_edit_detected_even_by_legacy` |
| 1b | Edit verdict + recompute hashes/HMAC with public key, re-chain later records | **Undetected** | Detected | Ed25519 seal | `test_attack_modify_report_with_public_hmac_key_beats_legacy_but_not_seals` |
| 1c | Edit verdict in an exported bundle (`evidence.json` + `report.md`), re-sign bundle | **Undetected** (offline verifier PASS) | Detected | `seal.json` bound to original record hash | `test_attack_modify_bundle_report_resigned_with_public_key` |
| 2a | Delete a record from the middle of the ledger | Detected | Detected | hash chain | `test_attack_delete_middle_record_detected_by_chain` |
| 2b | Delete the newest record(s) + their manifests + local checkpoint log | **Undetected** | Detected **only with an externally held checkpoint** | signed checkpoint | `test_attack_delete_tail_record_undetected_without_checkpoint` |
| 2c | Delete a middle record and re-chain everything after it | **Undetected** | Detected | seals + checkpoint | `test_attack_delete_and_rechain_detected_by_seals_and_checkpoint` |
| 2d | Forge a checkpoint claiming a shorter ledger | n/a | Detected | checkpoint seal | `test_forged_checkpoint_rejected` |
| 3a | Present a bundle from another node (dev laptop / test vault) as production evidence | **Undetected** (shared default key) | Detected | unknown `kid` | `test_attack_replay_bundle_from_other_node_rejected` |
| 3b | Present an old unsealed bundle | **Undetected** | Detected | seal required | `test_attack_replay_unsealed_legacy_bundle_rejected` |
| 3c | Transplant record A's seal into record B's bundle | n/a | Detected | TSA imprint / signature | `test_attack_seal_transplant_between_records_rejected` |
| 3d | Insider with the node key back-dates a record by 2 days | **Undetected** | Detected | claimed time vs RFC 3161 `genTime` (> 120 s) | `test_attack_backdated_record_by_insider_rejected` |
| 3e | Reuse another record's timestamp token | n/a | Detected | TSA message imprint | `test_attack_reuse_timestamp_token_from_other_record_rejected` |
| 3f | Strip the timestamp from a seal | n/a | Detected | TSA required by policy | `test_attack_stripped_timestamp_rejected_when_tsa_required` |
| 4a | Change `model_versions` label to a "validated" model, re-sign | **Undetected** | Detected | Ed25519 seal | `test_attack_swap_model_version_label_resigned` |
| 4b | Replace weight file on disk, keep the same version string | **Undetected** (no weight hash recorded) | Detected | `model_fingerprints` (SHA-256 of weights) | `test_attack_swap_model_weights_on_disk_detected_by_fingerprint` |

Key-management tests: rotation keeps old evidence valid (`test_key_rotation_keeps_old_evidence_valid`); a revoked key's
pre-compromise signatures stay valid only because they carry trusted timestamps, while a forgery made with the stolen
key after revocation is rejected (`test_revoked_key_rejects_post_compromise_signatures_only`,
`test_revoked_key_without_timestamp_is_not_trusted`); private keys are encrypted at rest and the published keyring
contains no private material. TSA tests cover token round-trip, wrong digest, untrusted TSA, nonce mismatch, bit flips,
the HTTP client, malformed requests, and TSA outage (capture continues, the gap is flagged and fails a strict audit).

## 3. What changed

| Component | Change |
|---|---|
| `security/forensics/timestamping.py` (new) | RFC 3161 request/response, HTTP client for external TSAs, in-house RFC 3161 TSA (ECDSA P-256, critical `id-kp-timeStamping` EKU, ESSCertIDv2), full offline token verification. Tokens are standard: **`openssl ts -verify` (OpenSSL 3.2.4) returns `Verification: OK`** on them. Only digests are ever sent to a TSA. |
| `security/forensics/keyring.py` (new) | Ed25519 node keys with `kid`, lifecycle `active → retired → revoked`, time-aware revocation, PKCS#8 encryption at rest, public `trusted_keys.json` export. |
| `security/forensics/sealing.py` (new) | Seals = Ed25519 over `(record_id, record_hash)` + RFC 3161 token over the signature; checkpoint seals; claimed-time vs trusted-time check; `sealer_from_env()` for deployment. |
| `security/forensics/evidence_vault.py` | Optional `sealer` (auto-enabled by `AEGIS_VAULT_KEYRING_DIR`); seals in every ledger entry; `create_checkpoint()`; audit verifies seals, TSA time, and external checkpoints; F-1/F-2/F-3 fixes; `model_fingerprints` on verification records; HMAC key now overridable via `AEGIS_VAULT_SIGNING_KEY` (still integrity-only). |
| `security/forensics/verify_bundle.py` | `--trusted-keys` / `--tsa-cert`: requires a valid seal bound to this record and a trusted timestamp; the stdlib-only path is unchanged. |
| `security/forensics/model_provenance.py` (new) | Pin / check SHA-256 fingerprints of every model weight file. |
| `security/forensics/keyctl.py` (new) | CLI: `init`, `rotate`, `revoke`, `export`, `list`, `tsa-init`, `checkpoint`, `audit`. |

Backward compatibility: legacy HMAC fields are still written and checked, the bundle layout only gains `seal.json`
and `checkpoint.json`, and all pre-existing vault, bundle, and alert-router tests still pass (65 tests in the combined run).

## 4. Residual risks (honest limits)

1. **Tail truncation needs an external witness.** Seals cannot prove that a record *should* exist. Checkpoints only
   help if a copy lives outside the vault host. Ship each checkpoint to the SIEM (Wazuh) or write-once storage at
   least every 15 minutes and on every bundle export. Until that is wired into `alert_router`, the window between
   checkpoints is unprotected.
2. **The node key is file-based.** The reference keyring encrypts it with a passphrase, but anyone with root on the
   evidence node *and* the passphrase can sign. Production should use a TPM/HSM/KMS behind the same `sign()` interface.
3. **The local TSA is only as independent as its host.** If it runs on the evidence node, an insider controls both clocks
   and the back-dating defence (3d) is void. For court use, prefer an external accredited RFC 3161 TSA (`AEGIS_TSA_URL`);
   the in-house TSA is for air-gapped sites and must run on a separate, access-controlled host.
4. **Model fingerprints must be supplied by the orchestrator.** The vault records and protects `model_fingerprints`, but
   `orchestrator/app/main.py` (AI-team owned) does not pass them yet. Until it does, attack 4b is detectable only for
   callers that supply fingerprints. Hand-off: call `fingerprint_models()` once at start-up and pass the dict to
   `store_verification(..., model_fingerprints=...)`.
5. **Existing evidence is unsealed.** Records written before sealing was enabled carry only HMACs. Seal-requiring audits
   will flag them; they should be re-attested (checkpoint + TSA) on migration day and treated as "integrity-only".
6. **Clock-skew threshold is a policy choice.** A record whose claimed time differs from the TSA time by more than
   120 s fails the strict audit. Reports must quote the TSA time, not the node clock.

## 5. Reproduce

```bash
pytest security/tests/test_forensic_soundness.py -v
python -m security.forensics.keyctl audit --vault security/vault --trusted-keys published/trusted_keys.json \
       --tsa-cert published/tsa.pem --checkpoints siem_checkpoints.jsonl
python security/forensics/verify_bundle.py bundle.zip --trusted-keys published/trusted_keys.json --tsa-cert published/tsa.pem
```
