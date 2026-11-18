# Evidence Admissibility & Chain-of-Custody Checklist

**Task:** Week 11 Cybersecurity Task 4 · For investigators exporting AEGIS evidence and examiners receiving it.
Grounded in ISO/IEC 27037 (identification, collection, acquisition, preservation) and the authentication logic of
US FRE 901(b)(9) / 902(13)–(14) and comparable rules elsewhere. This is an engineering checklist, not legal advice;
the receiving jurisdiction's counsel decides admissibility.

## A. Before evidence is collected (system readiness)

- [ ] Evidence node has an **active Ed25519 key** (`keyctl list`) and the current `trusted_keys.json` is published.
- [ ] Private key is encrypted at rest (no "UNENCRYPTED" warning in logs) or held in an HSM/TPM.
- [ ] A trusted **RFC 3161 TSA** is configured (`AEGIS_TSA_URL` preferred; in-house TSA on a separate host otherwise).
- [ ] Node and camera clocks are NTP/PTP-synchronised (offset < 1 s).
- [ ] Model weight fingerprints are pinned (`python -m security.forensics.model_provenance --check model_fingerprints.json` passes).
- [ ] Cameras are enrolled with valid mTLS certificates; the CRL is current (see device lifecycle report).
- [ ] Checkpoints are being shipped off-node (SIEM / WORM storage) at least every 15 minutes.

## B. At collection (per record)

- [ ] Input is hashed (SHA-256) **on arrival**, before any processing; hash is in the record (`input_hash`).
- [ ] Record captures detector outputs, model versions **and** weight fingerprints, calibration version, and the full judge transcript.
- [ ] Record is appended to the hash-chained ledger and carries a **seal with a trusted timestamp** (no `tst_error`).
- [ ] For live feeds: camera identity is from the mTLS certificate CN, frame hash chain and sequence checks passed,
      and any integrity failure produced `INTEGRITY_UNKNOWN`, never `AUTHENTIC`.

## C. At export (bundle for a case)

- [ ] Run a full audit first: `keyctl audit --vault ... --trusted-keys ... --tsa-cert ... --checkpoints <external copy>` → PASS.
- [ ] Export with `export_signed_bundle()`; confirm the bundle contains `seal.json` and `checkpoint.json`.
- [ ] Verify the bundle offline on a **different machine**: `verify_bundle.py bundle.zip --trusted-keys ... --tsa-cert ...` → PASS.
- [ ] Record in the custody log: bundle SHA-256, who exported it, when (TSA time from the report), case/exhibit number, recipient.
- [ ] Hand over the bundle **and, separately,** the published `trusted_keys.json` and TSA certificate.

## D. Custody log (one row per transfer)

| Exhibit | Bundle SHA-256 | Record id | From | To | Time (UTC) | Medium / channel | Verification result | Signature |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

## E. For the receiving examiner

- [ ] Recompute the bundle SHA-256 and match it to the custody log.
- [ ] Run `verify_bundle.py` with the independently obtained keyring and TSA certificate; keep the output.
- [ ] Confirm the signing key was not revoked before the TSA time shown (`trusted_keys.json`).
- [ ] Confirm the record's claimed time agrees with the TSA time (the verifier enforces ≤ 120 s).
- [ ] If model fingerprints are present, compare them with the vendor/project's pinned fingerprints.
- [ ] Note that a PRNU result is supporting evidence only: PRNU has so far been validated on simulated splices, not on
      real-camera footage (see `security/docs/device_lifecycle_and_prnu_report.md`).

## F. Known limits to disclose

- Records written before sealing was enabled are HMAC-only (integrity, not authenticity).
- Deletion of the newest records is provable only against a checkpoint that was held off-node.
- Detector scores are probabilistic; the report states calibration version and known failure modes (`docs/LIMITATIONS.md`).
