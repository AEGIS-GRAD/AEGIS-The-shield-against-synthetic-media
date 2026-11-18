#!/usr/bin/env python3
"""
AEGIS Offline Forensic Evidence Bundle Verifier
================================================
Standalone ISO/IEC 27037 & FRE Rule 902(13/14) verification tool.
Operates 100% offline with zero external dependencies beyond the Python stdlib.

Verifies:
  1. Presence of required bundle artifacts (evidence.json, report.md, hashes.sha256,
     bundle_signature.sig, payload/*)
  2. Bitwise SHA-256 integrity of every file listed in hashes.sha256
  3. Input payload hash match against evidence.json (`input_hash` or `primary_frame.sha256`)
  4. Tamper-evident cryptographic hash chain calculation (`record_hash`)
  5. HMAC-SHA256 signatures on both the bundle manifest and the ledger record

Usage:
  python verify_bundle.py <path/to/bundle.zip | path/to/extracted_dir> [--key-env VAR]
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import zipfile
from typing import Dict, Optional, Tuple

DEFAULT_SIGNING_KEY = b"aegis_surveillance_node_secret_key_v1"


def _read_bundle_files(target: Path) -> Dict[str, bytes]:
    """Reads all files from either a ZIP archive or an extracted directory."""
    files: Dict[str, bytes] = {}
    if target.is_file() and zipfile.is_zipfile(target):
        with zipfile.ZipFile(target, "r") as zf:
            for name in zf.namelist():
                if not name.endswith("/"):
                    files[name.replace("\\", "/")] = zf.read(name)
    elif target.is_dir():
        for p in target.rglob("*"):
            if p.is_file():
                rel = p.relative_to(target).as_posix()
                files[rel] = p.read_bytes()
    else:
        raise FileNotFoundError(f"Target '{target}' is neither a valid ZIP bundle nor a directory.")
    return files


def verify_bundle(
    target: Path | str,
    signing_key: bytes = DEFAULT_SIGNING_KEY,
    trusted_keys_path: Optional[str] = None,
    tsa_cert_paths: Optional[list] = None,
) -> Tuple[bool, str]:
    """
    Runs full offline cryptographic verification on a signed evidence bundle.
    Returns (is_valid, human_readable_report).

    With ``trusted_keys_path`` (the published public keyring) the bundle must also
    carry a valid Ed25519 seal; with ``tsa_cert_paths`` its RFC 3161 timestamp must
    chain to a trusted TSA and agree with the record's claimed creation time.
    """
    target_path = Path(target)
    try:
        files = _read_bundle_files(target_path)
    except Exception as exc:
        return False, f"[FAIL] Could not open bundle: {exc}"

    required = ("evidence.json", "report.md", "hashes.sha256", "bundle_signature.sig")
    for req in required:
        if req not in files:
            return False, f"[FAIL] Missing required bundle artifact: '{req}'"

    # 1. Verify hashes.sha256 entries against actual file bytes
    hashes_raw = files["hashes.sha256"].decode("utf-8")
    listed_files: Dict[str, str] = {}
    for line in hashes_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            return False, f"[FAIL] Malformed line in hashes.sha256: '{line}'"
        expected_sha, relpath = parts[0].strip(), parts[1].strip()
        listed_files[relpath] = expected_sha
        if relpath not in files:
            return False, f"[FAIL] File listed in hashes.sha256 is missing from bundle: '{relpath}'"
        actual_sha = hashlib.sha256(files[relpath]).hexdigest()
        if actual_sha != expected_sha:
            return False, (
                f"[FAIL] SHA-256 mismatch for '{relpath}'!\n"
                f"       Expected: {expected_sha}\n"
                f"       Actual:   {actual_sha}"
            )

    if "evidence.json" not in listed_files or "report.md" not in listed_files:
        return False, "[FAIL] hashes.sha256 does not cover evidence.json and report.md"

    # 2. Verify bundle_signature.sig
    try:
        sig_doc = json.loads(files["bundle_signature.sig"].decode("utf-8"))
    except Exception as exc:
        return False, f"[FAIL] Invalid JSON in bundle_signature.sig: {exc}"

    hashes_sha = hashlib.sha256(files["hashes.sha256"]).hexdigest()
    evidence_sha = hashlib.sha256(files["evidence.json"]).hexdigest()
    if sig_doc.get("hashes_sha256") != hashes_sha or sig_doc.get("evidence_sha256") != evidence_sha:
        return False, "[FAIL] bundle_signature.sig digest mismatch (hashes.sha256 or evidence.json altered)."

    expected_bundle_sig = hmac.new(
        signing_key, f"{hashes_sha}:{evidence_sha}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig_doc.get("signature", ""), expected_bundle_sig):
        return False, "[FAIL] Cryptographic bundle signature verification FAILED!"

    # 3. Verify evidence.json internal consistency, input hash, and ledger record hash
    try:
        evidence = json.loads(files["evidence.json"].decode("utf-8"))
    except Exception as exc:
        return False, f"[FAIL] Invalid JSON in evidence.json: {exc}"

    record_id = evidence.get("verification_id") or evidence.get("incident_id", "")
    ts = evidence.get("created_at_utc", "")
    prev_hash = evidence.get("prev_record_hash", "")
    stored_rec_hash = evidence.get("record_hash", "")
    stored_rec_sig = evidence.get("signature", "")

    # Verify input payload hash matches evidence.json metadata
    expected_input_hash = evidence.get("input_hash") or evidence.get("primary_frame", {}).get("sha256", "")
    payload_keys = [k for k in files if k.startswith("payload/")]
    if not payload_keys:
        return False, "[FAIL] No raw payload file found under payload/"
    payload_sha = hashlib.sha256(files[payload_keys[0]]).hexdigest()
    if payload_sha != expected_input_hash:
        return False, (
            f"[FAIL] Raw payload SHA-256 does not match evidence.json!\n"
            f"       Expected: {expected_input_hash}\n"
            f"       Actual:   {payload_sha}"
        )

    # Recompute manifest_digest (record without record_hash and signature)
    copy_dict = dict(evidence)
    copy_dict["record_hash"] = ""
    copy_dict["signature"] = ""
    manifest_digest = hashlib.sha256(json.dumps(copy_dict, sort_keys=True).encode("utf-8")).hexdigest()

    recomputed_rec_hash = hashlib.sha256(
        f"{prev_hash}:{record_id}:{ts}:{manifest_digest}".encode("utf-8")
    ).hexdigest()
    if recomputed_rec_hash != stored_rec_hash:
        return False, (
            f"[FAIL] Ledger record hash mismatch for '{record_id}'!\n"
            f"       Expected: {recomputed_rec_hash}\n"
            f"       Stored:   {stored_rec_hash}"
        )

    expected_rec_sig = hmac.new(
        signing_key, stored_rec_hash.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(stored_rec_sig, expected_rec_sig):
        return False, f"[FAIL] Record HMAC signature mismatch for '{record_id}'!"

    modality = evidence.get("modality", "live_surveillance")
    verdict = evidence.get("verdict") or evidence.get("threat_type", "N/A")
    cal_ver = evidence.get("calibration_version", "N/A")
    model_vers = evidence.get("model_versions", {})

    # 4. Ed25519 seal + RFC 3161 trusted timestamp (authenticity). Only enforced when
    # the verifier supplies the published public keyring; the HMAC checks above use a
    # shared secret and cannot, on their own, prove who produced the bundle.
    seal_line = "       Seal:                not checked (no --trusted-keys given; HMAC integrity only)"
    if trusted_keys_path:
        ok_seal, seal_msg = _verify_seal(files, record_id, stored_rec_hash, ts, trusted_keys_path, tsa_cert_paths)
        if not ok_seal:
            return False, f"[FAIL] {seal_msg}"
        seal_line = f"       Seal:                {seal_msg}"

    summary = (
        f"[PASS] Offline cryptographic verification SUCCEEDED!\n"
        f"       Record ID:           {record_id}\n"
        f"       Modality:            {modality}\n"
        f"       Verdict / Threat:    {verdict}\n"
        f"       Input SHA-256:       {payload_sha}\n"
        f"       Calibration Version: {cal_ver}\n"
        f"       Model Versions:      {json.dumps(model_vers)}\n"
        f"       Record Hash:         {stored_rec_hash}\n"
        f"       Files Verified:      {len(listed_files)}\n"
        f"{seal_line}"
    )
    return True, summary


def _verify_seal(files: Dict[str, bytes], record_id: str, record_hash: str, claimed_time: str,
                 trusted_keys_path: str, tsa_cert_paths) -> Tuple[bool, str]:
    """Verifies seal.json against a pinned public keyring (needs the `cryptography`
    and `asn1crypto` packages; the rest of this script is stdlib-only)."""
    if "seal.json" not in files:
        return False, "Bundle is not sealed (seal.json missing) but a trusted keyring was supplied."
    try:
        import sys as _sys
        _here = Path(__file__).resolve().parent
        for _p in (_here.parent.parent, _here.parent):
            if str(_p) not in _sys.path:
                _sys.path.insert(0, str(_p))
        try:
            from security.forensics.keyring import TrustedKeys
            from security.forensics.sealing import verify_record_seal
            from security.forensics.timestamping import load_trusted_tsa_certs
        except ImportError:
            from forensics.keyring import TrustedKeys  # type: ignore
            from forensics.sealing import verify_record_seal  # type: ignore
            from forensics.timestamping import load_trusted_tsa_certs  # type: ignore
    except Exception as exc:
        return False, f"Seal verification needs the AEGIS forensics package: {exc}"

    doc = json.loads(files["seal.json"].decode("utf-8"))
    if doc.get("record_id") != record_id or doc.get("record_hash") != record_hash:
        return False, "seal.json belongs to a different record (possible replay / substitution)."
    trusted = TrustedKeys.load(trusted_keys_path)
    tsa_trust = load_trusted_tsa_certs(tsa_cert_paths) if tsa_cert_paths else None
    chk = verify_record_seal(doc.get("seal"), record_id, record_hash, trusted, tsa_trust=tsa_trust,
                             require_timestamp=bool(tsa_trust), claimed_time=claimed_time)
    if not chk.ok:
        return False, f"Seal verification FAILED: {chk.reason}"
    when = f", trusted time {chk.tsa_time.isoformat()}" if chk.tsa_time and chk.tsa_trusted else ""
    return True, f"Ed25519 key {chk.kid} (node {chk.node_id}){when}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an AEGIS signed forensic evidence bundle offline.")
    parser.add_argument("bundle", help="Path to the signed evidence bundle (.zip or directory)")
    parser.add_argument(
        "--key-env",
        default="AEGIS_VAULT_SIGNING_KEY",
        help="Environment variable containing custom HMAC signing key (optional)",
    )
    parser.add_argument("--trusted-keys", default=None,
                        help="Published AEGIS public keyring (trusted_keys.json); requires a valid Ed25519 seal")
    parser.add_argument("--tsa-cert", action="append", default=None,
                        help="Trusted TSA certificate or issuing CA (PEM/DER); repeatable")
    args = parser.parse_args()

    env_key = os.environ.get(args.key_env)
    key_bytes = env_key.encode("utf-8") if env_key else DEFAULT_SIGNING_KEY

    ok, msg = verify_bundle(args.bundle, signing_key=key_bytes,
                            trusted_keys_path=args.trusted_keys, tsa_cert_paths=args.tsa_cert)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
