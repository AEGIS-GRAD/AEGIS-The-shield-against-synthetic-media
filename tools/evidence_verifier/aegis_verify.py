#!/usr/bin/env python3
"""
AEGIS Independent Offline Evidence Verifier CLI
================================================
Standalone forensic verification utility complying with ISO/IEC 27037:2012
and US Federal Rules of Evidence (FRE) Rule 902(13)/(14).

Designed to run on any air-gapped auditor/examiner machine using ONLY the
Python 3 standard library — with zero dependency on the running AEGIS server,
databases, Docker containers, or repository codebase.

Supports:
  1. Unified Signed Evidence Bundles (`evidence.json`, `report.md`, `hashes.sha256`,
     `bundle_signature.sig`, `payload/*`, optional `seal.json` / `checkpoint.json`)
     for all 5 modalities (`video`, `audio`, `image`, `text`, `multimodal`) and
     live surveillance alerts (`INC-*`).
  2. Legacy Incident Packages (`manifest.json`, `evidence/*`).

Usage examples:
  python aegis_verify.py bundle.zip
  python aegis_verify.py sample_bundles/ --verbose --inspect
  python aegis_verify.py a.zip b.zip --json
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Default node development key (override in production via --key-env / --key-file / --key)
DEFAULT_SIGNING_KEY = b"aegis_surveillance_node_secret_key_v1"

EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_USAGE_ERROR = 2


@dataclass
class CheckResult:
    """Outcome of a single cryptographic verification step."""

    name: str
    passed: bool
    detail: str


@dataclass
class BundleMetadataSummary:
    """Extracted forensic metadata from a verified (or inspected) bundle."""

    bundle_format: str = "unknown"  # "unified_signed_bundle" | "legacy_incident_package"
    record_id: str = ""
    job_id: str = ""
    modality: str = ""
    verdict: str = ""
    calibrated_score: Optional[float] = None
    calibration_version: str = ""
    model_versions: Dict[str, str] = field(default_factory=dict)
    created_at_utc: str = ""
    input_sha256: str = ""
    record_hash: str = ""
    debate_rounds_count: int = 0
    files_verified: int = 0
    has_ed25519_seal: bool = False
    seal_status: str = "not checked (no --trusted-keys supplied; HMAC/SHA-256 verified)"


@dataclass
class VerificationResult:
    """Structured result returned for each target bundle."""

    target: str
    is_valid: bool
    checks: List[CheckResult] = field(default_factory=list)
    summary: BundleMetadataSummary = field(default_factory=BundleMetadataSummary)
    error_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "is_valid": self.is_valid,
            "error_reason": self.error_reason,
            "checks": [asdict(c) for c in self.checks],
            "summary": asdict(self.summary),
        }


def _read_bundle_files(target: Path) -> Dict[str, bytes]:
    """Reads archive entries into a normalized POSIX-keyed byte map."""
    files: Dict[str, bytes] = {}
    if target.is_file() and zipfile.is_zipfile(target):
        with zipfile.ZipFile(target, "r") as zf:
            for info in zf.infolist():
                if not info.is_dir():
                    files[info.filename.replace("\\", "/")] = zf.read(info.filename)
        return files
    if target.is_dir():
        for p in sorted(target.rglob("*")):
            if p.is_file():
                files[p.relative_to(target).as_posix()] = p.read_bytes()
        return files
    raise FileNotFoundError(f"Target '{target}' is neither a readable ZIP file nor a directory.")


def _verify_legacy_incident_package(target_str: str, files: Dict[str, bytes]) -> VerificationResult:
    """Verifies legacy Week-3 `manifest.json` + `evidence/` bundles."""
    checks: List[CheckResult] = []
    meta = BundleMetadataSummary(bundle_format="legacy_incident_package")

    if "manifest.json" not in files:
        checks.append(CheckResult("artifact_presence", False, "Missing manifest.json"))
        return VerificationResult(
            target=target_str,
            is_valid=False,
            checks=checks,
            summary=meta,
            error_reason="Missing manifest.json in legacy bundle.",
        )

    try:
        data = json.loads(files["manifest.json"].decode("utf-8"))
    except Exception as exc:
        checks.append(CheckResult("artifact_presence", False, f"Malformed manifest.json: {exc}"))
        return VerificationResult(
            target=target_str,
            is_valid=False,
            checks=checks,
            summary=meta,
            error_reason=f"Malformed manifest.json: {exc}",
        )

    primary = data.get("primary_frame") or {}
    expected_sha = primary.get("sha256", "")
    blob_rel = str(primary.get("blob_relpath", ""))
    ev_name = f"evidence/{os.path.basename(blob_rel)}"
    if ev_name not in files:
        checks.append(CheckResult("artifact_presence", False, f"Missing primary evidence blob '{ev_name}'"))
        return VerificationResult(
            target=target_str,
            is_valid=False,
            checks=checks,
            summary=meta,
            error_reason=f"Missing primary evidence blob '{ev_name}'",
        )
    checks.append(CheckResult("artifact_presence", True, "manifest.json and primary evidence blob present"))

    actual_sha = hashlib.sha256(files[ev_name]).hexdigest()
    sha_ok = bool(expected_sha) and hmac.compare_digest(actual_sha, expected_sha)
    checks.append(
        CheckResult(
            "payload_binding",
            sha_ok,
            f"SHA-256 matches ({actual_sha[:16]}...)"
            if sha_ok
            else f"SHA-256 mismatch: expected {expected_sha}, got {actual_sha}",
        )
    )

    meta.record_id = data.get("incident_id", "")
    meta.modality = "live_surveillance"
    meta.verdict = data.get("threat_type", "")
    meta.created_at_utc = data.get("created_at_utc", "")
    meta.input_sha256 = actual_sha
    meta.record_hash = data.get("record_hash", "")
    meta.files_verified = 2

    return VerificationResult(
        target=target_str,
        is_valid=sha_ok,
        checks=checks,
        summary=meta,
        error_reason=None if sha_ok else checks[-1].detail,
    )


def _verify_optional_ed25519_seal(
    files: Dict[str, bytes],
    record_id: str,
    record_hash: str,
    claimed_time: str,
    trusted_keys_path: str,
    tsa_cert_paths: Optional[Sequence[str]],
) -> Tuple[bool, str]:
    """Optional asymmetric Ed25519 + RFC 3161 TSA verification when keyring is provided."""
    if "seal.json" not in files:
        return False, "Bundle does not contain seal.json, but --trusted-keys was required."
    try:
        here = Path(__file__).resolve()
        repo_root = here.parent.parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from security.forensics.keyring import TrustedKeys
        from security.forensics.sealing import verify_record_seal
        from security.forensics.timestamping import load_trusted_tsa_certs
    except Exception as exc:
        return False, f"Asymmetric seal check requires AEGIS keyring module + cryptography: {exc}"

    try:
        doc = json.loads(files["seal.json"].decode("utf-8"))
    except Exception as exc:
        return False, f"Malformed seal.json: {exc}"

    if doc.get("record_id") != record_id or doc.get("record_hash") != record_hash:
        return False, "seal.json record_id/record_hash does not match evidence.json (possible replay)."

    trusted = TrustedKeys.load(trusted_keys_path)
    tsa_trust = load_trusted_tsa_certs(list(tsa_cert_paths)) if tsa_cert_paths else None
    chk = verify_record_seal(
        doc.get("seal"),
        record_id,
        record_hash,
        trusted,
        tsa_trust=tsa_trust,
        require_timestamp=bool(tsa_trust),
        claimed_time=claimed_time,
    )
    if not chk.ok:
        return False, f"Ed25519 seal verification FAILED: {chk.reason}"
    tsa_note = f", TSA time={chk.tsa_time.isoformat()}" if chk.tsa_time and chk.tsa_trusted else ""
    return True, f"Ed25519 kid={chk.kid} (node={chk.node_id}{tsa_note})"


def verify_bundle(
    target: Path | str,
    *,
    signing_key: bytes = DEFAULT_SIGNING_KEY,
    trusted_keys_path: Optional[str] = None,
    tsa_cert_paths: Optional[Sequence[str]] = None,
) -> VerificationResult:
    """Runs complete offline cryptographic verification on a single bundle or extracted directory."""
    target_path = Path(target)
    target_str = str(target_path)
    checks: List[CheckResult] = []
    meta = BundleMetadataSummary()

    try:
        files = _read_bundle_files(target_path)
    except Exception as exc:
        checks.append(CheckResult("artifact_presence", False, f"Cannot open bundle: {exc}"))
        return VerificationResult(
            target=target_str,
            is_valid=False,
            checks=checks,
            summary=meta,
            error_reason=f"Cannot open bundle: {exc}",
        )

    # Support legacy incident packages transparently
    if "evidence.json" not in files and "manifest.json" in files:
        return _verify_legacy_incident_package(target_str, files)

    meta.bundle_format = "unified_signed_bundle"
    meta.has_ed25519_seal = "seal.json" in files

    # ── Check 1: Artifact Presence ───────────────────────────────────────────
    required = ("evidence.json", "report.md", "hashes.sha256", "bundle_signature.sig")
    missing = [req for req in required if req not in files]
    payload_keys = sorted(k for k in files if k.startswith("payload/") and not k.endswith("/"))
    if not payload_keys:
        missing.append("payload/<media_or_frame_blob>")

    if missing:
        detail = f"Missing required bundle artifact(s): {', '.join(missing)}"
        checks.append(CheckResult("artifact_presence", False, detail))
        return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)

    checks.append(
        CheckResult(
            "artifact_presence",
            True,
            f"All required artifacts present ({len(required)} core files + {payload_keys[0]})",
        )
    )

    # ── Check 2: Manifest Hashes (hashes.sha256) ─────────────────────────────
    try:
        hashes_raw = files["hashes.sha256"].decode("utf-8")
    except UnicodeDecodeError as exc:
        detail = f"hashes.sha256 is not valid UTF-8: {exc}"
        checks.append(CheckResult("manifest_hashes", False, detail))
        return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)

    listed_files: Dict[str, str] = {}
    for line in hashes_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            detail = f"Malformed checksum line in hashes.sha256: '{line}'"
            checks.append(CheckResult("manifest_hashes", False, detail))
            return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)
        expected_sha, relpath = parts[0].strip().lower(), parts[1].strip().replace("\\", "/")
        listed_files[relpath] = expected_sha
        if relpath not in files:
            detail = f"File listed in hashes.sha256 is missing from bundle: '{relpath}'"
            checks.append(CheckResult("manifest_hashes", False, detail))
            return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)
        actual_sha = hashlib.sha256(files[relpath]).hexdigest()
        if not hmac.compare_digest(actual_sha, expected_sha):
            detail = (
                f"SHA-256 mismatch for '{relpath}' "
                f"(expected {expected_sha[:16]}..., got {actual_sha[:16]}...)"
            )
            checks.append(CheckResult("manifest_hashes", False, detail))
            return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)

    uncovered = [req for req in ("evidence.json", "report.md", payload_keys[0]) if req not in listed_files]
    if uncovered:
        detail = f"hashes.sha256 omits critical file(s): {', '.join(uncovered)}"
        checks.append(CheckResult("manifest_hashes", False, detail))
        return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)

    meta.files_verified = len(listed_files)
    checks.append(CheckResult("manifest_hashes", True, f"All {len(listed_files)} SHA-256 checksums matched byte-for-byte"))

    # ── Check 3: Bundle Signature (bundle_signature.sig) ─────────────────────
    try:
        sig_doc = json.loads(files["bundle_signature.sig"].decode("utf-8"))
    except Exception as exc:
        detail = f"Invalid JSON in bundle_signature.sig: {exc}"
        checks.append(CheckResult("bundle_signature", False, detail))
        return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)

    hashes_sha = hashlib.sha256(files["hashes.sha256"]).hexdigest()
    evidence_sha = hashlib.sha256(files["evidence.json"]).hexdigest()
    if sig_doc.get("hashes_sha256") != hashes_sha or sig_doc.get("evidence_sha256") != evidence_sha:
        detail = "bundle_signature.sig digest mismatch (hashes.sha256 or evidence.json was altered)"
        checks.append(CheckResult("bundle_signature", False, detail))
        return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)

    expected_bundle_sig = hmac.new(signing_key, f"{hashes_sha}:{evidence_sha}".encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(sig_doc.get("signature", "")), expected_bundle_sig):
        detail = "HMAC-SHA256 bundle signature verification FAILED (invalid key or forged bundle signature)"
        checks.append(CheckResult("bundle_signature", False, detail))
        return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)

    checks.append(CheckResult("bundle_signature", True, f"HMAC-SHA256 bundle signature valid (sig={expected_bundle_sig[:16]}...)"))

    # ── Check 4: Parse evidence.json & Verify Raw Payload Binding ────────────
    try:
        evidence = json.loads(files["evidence.json"].decode("utf-8"))
    except Exception as exc:
        detail = f"Invalid JSON in evidence.json: {exc}"
        checks.append(CheckResult("payload_binding", False, detail))
        return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)

    record_id = evidence.get("verification_id") or evidence.get("incident_id", "")
    ts = evidence.get("created_at_utc", "")
    prev_hash = evidence.get("prev_record_hash", "")
    stored_rec_hash = evidence.get("record_hash", "")
    stored_rec_sig = evidence.get("signature", "")

    meta.record_id = record_id
    meta.job_id = evidence.get("job_id", "")
    meta.modality = evidence.get("modality", "live_surveillance")
    meta.verdict = evidence.get("verdict") or evidence.get("threat_type", "N/A")
    meta.calibrated_score = evidence.get("calibrated_score")
    meta.calibration_version = evidence.get("calibration_version", "N/A")
    meta.model_versions = dict(evidence.get("model_versions") or {})
    meta.created_at_utc = ts
    meta.record_hash = stored_rec_hash
    transcript = evidence.get("judge_transcript") or {}
    meta.debate_rounds_count = len(transcript.get("rounds", [])) if isinstance(transcript, dict) else 0

    expected_input_hash = evidence.get("input_hash") or (evidence.get("primary_frame") or {}).get("sha256", "")
    payload_sha = hashlib.sha256(files[payload_keys[0]]).hexdigest()
    meta.input_sha256 = payload_sha
    if not expected_input_hash or not hmac.compare_digest(payload_sha, expected_input_hash):
        detail = (
            f"Raw payload SHA-256 mismatch against evidence.json "
            f"(expected {expected_input_hash[:16]}..., got {payload_sha[:16]}...)"
        )
        checks.append(CheckResult("payload_binding", False, detail))
        return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)

    checks.append(CheckResult("payload_binding", True, f"Raw payload SHA-256 matches evidence manifest ({payload_sha[:16]}...)"))

    # ── Check 5: Tamper-Evident Ledger Chain Hash ────────────────────────────
    copy_dict = dict(evidence)
    copy_dict["record_hash"] = ""
    copy_dict["signature"] = ""
    manifest_digest = hashlib.sha256(json.dumps(copy_dict, sort_keys=True).encode("utf-8")).hexdigest()
    recomputed_rec_hash = hashlib.sha256(f"{prev_hash}:{record_id}:{ts}:{manifest_digest}".encode("utf-8")).hexdigest()
    if not stored_rec_hash or not hmac.compare_digest(recomputed_rec_hash, stored_rec_hash):
        detail = (
            f"Ledger record_hash mismatch for '{record_id}' "
            f"(expected {recomputed_rec_hash[:16]}..., stored {stored_rec_hash[:16]}...)"
        )
        checks.append(CheckResult("ledger_chain_hash", False, detail))
        return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)

    checks.append(CheckResult("ledger_chain_hash", True, f"Ledger chain hash valid ({stored_rec_hash[:16]}...)"))

    # ── Check 6: Ledger Record HMAC-SHA256 Signature ─────────────────────────
    expected_rec_sig = hmac.new(signing_key, stored_rec_hash.encode("utf-8"), hashlib.sha256).hexdigest()
    if not stored_rec_sig or not hmac.compare_digest(stored_rec_sig, expected_rec_sig):
        detail = f"Record HMAC-SHA256 signature mismatch for '{record_id}'"
        checks.append(CheckResult("record_signature", False, detail))
        return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=detail)

    checks.append(CheckResult("record_signature", True, f"Record HMAC-SHA256 signature valid ({expected_rec_sig[:16]}...)"))

    # ── Optional Check 7: Ed25519 Seal & RFC 3161 TSA (if keyring supplied) ──
    if trusted_keys_path:
        ok_seal, seal_msg = _verify_optional_ed25519_seal(
            files, record_id, stored_rec_hash, ts, trusted_keys_path, tsa_cert_paths
        )
        checks.append(CheckResult("ed25519_seal", ok_seal, seal_msg))
        meta.seal_status = seal_msg
        if not ok_seal:
            return VerificationResult(target=target_str, is_valid=False, checks=checks, summary=meta, error_reason=seal_msg)
    elif meta.has_ed25519_seal:
        meta.seal_status = "seal.json present (pass --trusted-keys <trusted_keys.json> to verify Ed25519/TSA)"

    return VerificationResult(target=target_str, is_valid=True, checks=checks, summary=meta)


def _discover_targets(raw_targets: Sequence[str]) -> List[Path]:
    """Expands CLI arguments into individual bundle ZIPs or extracted bundle directories."""
    out: List[Path] = []
    for item in raw_targets:
        p = Path(item)
        if p.is_dir():
            if (p / "evidence.json").exists() or (p / "manifest.json").exists():
                out.append(p)
            else:
                zips = sorted(p.glob("*.zip"))
                out.extend(zips)
        else:
            out.append(p)
    return out


def _resolve_signing_key(args: argparse.Namespace) -> bytes:
    if args.key is not None:
        return args.key.encode("utf-8")
    if args.key_file is not None:
        return Path(args.key_file).read_bytes().strip()
    env_val = os.environ.get(args.key_env)
    if env_val:
        return env_val.encode("utf-8")
    return DEFAULT_SIGNING_KEY


def _format_human(res: VerificationResult, *, verbose: bool = False, inspect: bool = False) -> str:
    s = res.summary
    badge = "[PASS]" if res.is_valid else "[FAIL]"
    lines = [f"{badge} {res.target}"]
    if res.is_valid:
        lines.append(
            f"       Record ID: {s.record_id} | Modality: {s.modality} | "
            f"Verdict: {s.verdict} | Files Verified: {s.files_verified}"
        )
    else:
        lines.append(f"       Reason: {res.error_reason}")

    if verbose:
        for chk in res.checks:
            mark = "OK" if chk.passed else "XX"
            lines.append(f"         [{mark}] {chk.name}: {chk.detail}")

    if inspect and res.is_valid:
        lines.append(f"       Format:              {s.bundle_format}")
        lines.append(f"       Job ID:              {s.job_id or 'N/A'}")
        lines.append(f"       Timestamp (UTC):     {s.created_at_utc}")
        lines.append(f"       Input SHA-256:       {s.input_sha256}")
        if s.calibrated_score is not None:
            lines.append(f"       Calibrated Score:    {s.calibrated_score:.4f}")
        lines.append(f"       Calibration Version: {s.calibration_version or 'N/A'}")
        lines.append(f"       Model Versions:      {json.dumps(s.model_versions)}")
        lines.append(f"       Debate Rounds:       {s.debate_rounds_count}")
        lines.append(f"       Record Hash:         {s.record_hash}")
        lines.append(f"       Seal Status:         {s.seal_status}")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegis_verify",
        description="Verify AEGIS signed forensic evidence bundles offline using Python stdlib only.",
    )
    parser.add_argument(
        "targets",
        nargs="+",
        help="Path(s) to .zip bundle(s), extracted bundle directory, or directory of *.zip bundles.",
    )
    parser.add_argument(
        "--key",
        default=None,
        help="Inline UTF-8 HMAC signing key string (overrides --key-env).",
    )
    parser.add_argument(
        "--key-file",
        default=None,
        help="Path to file containing the HMAC signing key (overrides --key-env).",
    )
    parser.add_argument(
        "--key-env",
        default="AEGIS_VAULT_SIGNING_KEY",
        help="Environment variable with custom HMAC signing key (default: AEGIS_VAULT_SIGNING_KEY).",
    )
    parser.add_argument(
        "--trusted-keys",
        default=None,
        help="Optional path to published trusted_keys.json keyring for Ed25519 seal verification.",
    )
    parser.add_argument(
        "--tsa-cert",
        action="append",
        default=None,
        help="Optional trusted RFC 3161 TSA certificate path (PEM/DER, repeatable).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show per-check verification breakdown for each bundle.",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Print extracted forensic metadata (model versions, calibration, hashes) on pass.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON verification report.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        key_bytes = _resolve_signing_key(args)
    except OSError as exc:
        print(f"[ERROR] Failed to read signing key: {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    targets = _discover_targets(args.targets)
    if not targets:
        print("[ERROR] No .zip bundles or bundle directories found for given target(s).", file=sys.stderr)
        return EXIT_USAGE_ERROR

    results: List[VerificationResult] = []
    for t in targets:
        if not t.exists():
            results.append(
                VerificationResult(
                    target=str(t),
                    is_valid=False,
                    checks=[CheckResult("artifact_presence", False, f"Target not found: '{t}'")],
                    error_reason=f"Target not found: '{t}'",
                )
            )
            continue
        results.append(
            verify_bundle(
                t,
                signing_key=key_bytes,
                trusted_keys_path=args.trusted_keys,
                tsa_cert_paths=args.tsa_cert,
            )
        )

    passed_count = sum(1 for r in results if r.is_valid)
    failed_count = len(results) - passed_count

    if args.json:
        payload = {
            "total": len(results),
            "passed": passed_count,
            "failed": failed_count,
            "all_valid": failed_count == 0,
            "results": [r.to_dict() for r in results],
        }
        print(json.dumps(payload, indent=2))
    else:
        for res in results:
            print(_format_human(res, verbose=args.verbose, inspect=args.inspect))
        if len(results) > 1:
            print(f"\nSummary: {passed_count}/{len(results)} passed, {failed_count} failed.")

    return EXIT_VALID if failed_count == 0 else EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
