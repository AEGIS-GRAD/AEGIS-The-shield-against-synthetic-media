# Evidence Signing Key Management & Rotation

**Task:** Week 11 Cybersecurity Task 4 · **Scope:** keys that make AEGIS evidence attributable and non-repudiable
**Implementation:** `security/forensics/keyring.py`, `sealing.py`, `timestamping.py`, `keyctl.py`

## 1. Keys in the system

| Key | Algorithm | Purpose | Who holds the private part | Who gets the public part |
|---|---|---|---|---|
| **Node evidence key** (one per evidence node) | Ed25519 | Seals every vault record and checkpoint | The evidence node only (HSM/TPM in production) | Published keyring `trusted_keys.json` → courts, examiners, auditors |
| **TSA key** | ECDSA P-256 (local) or the TSA's own | RFC 3161 time attestation | The TSA operator (external accredited TSA, or a separate in-house host) | `tsa.pem` / TSA CA certificate |
| Legacy vault HMAC key | HMAC-SHA256 | Accidental-corruption check only | Anyone (default is committed to git) | — |
| mTLS CA / device certs | RSA-2048 | Transport identity (cameras, services) | `security/transport/certs` | Services |

The legacy HMAC key is **not** an authenticity mechanism: it is symmetric and its default value is public. It is kept
only so older bundles and tooling keep working. Never present an HMAC-only bundle as proof of origin.

## 2. Storage

* Private node keys: PKCS#8 PEM, encrypted with `AEGIS_VAULT_KEY_PASSPHRASE` (`BestAvailableEncryption`), file mode 0600,
  in `AEGIS_VAULT_KEYRING_DIR/private/<kid>.pem`. The keyring refuses nothing at runtime if no passphrase is set but logs a
  warning on every key generation; deployment checklists must treat that warning as a blocker.
* Production target: move `SigningKeyring.sign()` behind a TPM 2.0 / PKCS#11 HSM / cloud KMS key. The rest of the
  code only calls `sign(message) -> (kid, signature)`, so the swap is local to `keyring.py`.
* The passphrase is delivered through the container's secret store (Docker/K8s secret), never in compose files or git.
* Separation of duties: the person who can read the node key must not administer the TSA, and vice versa.
* Backups: the **public** keyring is backed up with the evidence forever (verifiers need retired and revoked keys too).
  Private keys are not backed up. A lost key is rotated, not restored.

## 3. Lifecycle

```
generate (active) ──rotate──▶ retired (verify-only) ──compromise──▶ revoked(revoked_at, reason)
```

| Event | Command | Effect on existing evidence |
|---|---|---|
| Node commissioning | `keyctl init --keyring DIR --node-id NODE` | — |
| Scheduled rotation (every 90 days, or on staff change) | `keyctl rotate ...` then `keyctl export` + publish | Old records stay valid (retired key = verify-only). A retired key that signs more than 5 min after retirement is rejected. |
| Suspected compromise | `keyctl revoke --kid KID --at <earliest possible compromise time> --reason ...`, then `rotate`, `export`, publish | Records with a **trusted timestamp before `revoked_at`** stay valid. Untimestamped records from that key, and anything timestamped after, are rejected. |
| Decommissioning | `rotate` on the replacement node; mark old key retired | Old evidence remains verifiable with the published keyring |

Choose `--at` conservatively (the earliest moment the key could have leaked). Revocation is the reason every seal is
timestamped: without a trusted time, a revoked key would invalidate *all* evidence it ever signed.

## 4. Publication and verification

1. After every `init/rotate/revoke`, run `keyctl export --out trusted_keys.json`.
2. Publish the file through a channel the verifier trusts independently of the evidence: signed git tag on the
   project repo, the case management system, or handed to opposing counsel in discovery.
3. Verifiers run `verify_bundle.py bundle.zip --trusted-keys trusted_keys.json --tsa-cert tsa.pem`.
   The bundle never supplies its own trust anchors.

## 5. Checkpoints (ledger head commitments)

`keyctl checkpoint --vault DIR` (or `vault.create_checkpoint()`) emits a sealed, timestamped statement
`{ledger_size, head_record_id, head_hash}`. Policy:

* Every 15 minutes and on every bundle export (export does this automatically).
* Each checkpoint is shipped off the node (Wazuh/SIEM, WORM bucket, or printed into the case file).
* Audits pass those **external** copies with `--checkpoints`; the local `checkpoints.jsonl` can be deleted by the same
  attacker who truncates the ledger.

## 6. Clock discipline

* Evidence nodes and cameras: NTP/PTP synchronised; alarm if offset > 1 s.
* The audit rejects records whose claimed `created_at_utc` differs from the RFC 3161 `genTime` by more than 120 s
  (`max_clock_skew_s`). Court reports must quote the TSA time.
* If the TSA is unreachable, capture continues and the seal records `tst_error`; those records fail a strict audit
  and must be re-attested by a checkpoint as soon as the TSA returns.
