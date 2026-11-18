"""
AEGIS Camera Device Lifecycle — Week 11 Task 6
==============================================

Issuance, renewal (rotation) and revocation of camera mTLS identities, plus the
Certificate Revocation List (CRL) the ingestion gateway enforces.

Before this module the gateway trusted *any* certificate signed by the AEGIS CA
for its whole validity period: a stolen or decommissioned camera kept streaming
until its certificate expired (365 days by default). Revocation now works:

    ca = DeviceCA.load(certs_dir)
    crt, key, serial = ca.issue_camera("cam-lobby-01", valid_days=30)
    crt2, key2, _    = ca.renew_camera("cam-lobby-01")      # overlap window, then
    ca.revoke(serial, reason="superseded")                 # old cert stops working
    ca.write_crl()                                          # gateway hot-reloads it

The gateway loads ``crl.pem`` (``AEGIS_CRL_PATH`` or ``<certs>/crl.pem``) with
``VERIFY_CRL_CHECK_LEAF`` and reloads it whenever the file changes, so a
revocation takes effect on the camera's next handshake without a restart.

CLI::

    python -m security.transport.device_lifecycle issue  --camera-id cam-01 [--days 30]
    python -m security.transport.device_lifecycle renew  --camera-id cam-01
    python -m security.transport.device_lifecycle revoke --serial 0x... --reason key_compromise
    python -m security.transport.device_lifecycle crl
    python -m security.transport.device_lifecycle list
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

UTC = dt.timezone.utc
DEFAULT_CERTS_DIR = Path(__file__).resolve().parent / "certs"

REASONS = {
    "unspecified": x509.ReasonFlags.unspecified,
    "key_compromise": x509.ReasonFlags.key_compromise,
    "superseded": x509.ReasonFlags.superseded,
    "cessation_of_operation": x509.ReasonFlags.cessation_of_operation,
    "affiliation_changed": x509.ReasonFlags.affiliation_changed,
}


@dataclass
class DeviceRecord:
    camera_id: str
    serial: str  # hex
    not_before: str
    not_after: str
    cert_path: str
    status: str = "active"  # active | superseded | revoked
    revoked_at: Optional[str] = None
    reason: Optional[str] = None


class DeviceCA:
    """Camera-identity CA operations on top of the existing AEGIS root CA."""

    def __init__(self, ca_cert: x509.Certificate, ca_key, certs_dir: Path):
        self.ca_cert = ca_cert
        self.ca_key = ca_key
        self.dir = Path(certs_dir)
        self.devices_dir = self.dir / "devices"
        self.registry_path = self.dir / "device_registry.json"
        self.crl_path = self.dir / "crl.pem"
        self.devices_dir.mkdir(parents=True, exist_ok=True)
        self.registry: Dict[str, DeviceRecord] = {}
        if self.registry_path.exists():
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            self.registry = {d["serial"]: DeviceRecord(**d) for d in data}

    @classmethod
    def load(cls, certs_dir: Path | str = DEFAULT_CERTS_DIR) -> "DeviceCA":
        d = Path(certs_dir)
        if not (d / "ca.crt").exists():
            from security.transport.generate_certs import generate_all_service_certs

            generate_all_service_certs(str(d))
        ca_cert = x509.load_pem_x509_certificate((d / "ca.crt").read_bytes())
        ca_key = serialization.load_pem_private_key((d / "ca.key").read_bytes(), password=None)
        return cls(ca_cert, ca_key, d)

    def _save(self) -> None:
        tmp = self.registry_path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(r) for r in self.registry.values()], indent=2), encoding="utf-8")
        os.replace(tmp, self.registry_path)

    # ── issuance ─────────────────────────────────────────────────────────────
    def issue_camera(
        self,
        camera_id: str,
        valid_days: float = 30,
        not_before: Optional[dt.datetime] = None,
        out_dir: Optional[Path] = None,
        record: bool = True,
    ) -> Tuple[Path, Path, int]:
        """Issues a client certificate whose CN is the camera identity (ECDSA P-256)."""
        key = ec.generate_private_key(ec.SECP256R1())
        start = not_before or (dt.datetime.now(UTC) - dt.timedelta(minutes=1))
        serial = x509.random_serial_number()
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AEGIS"),
                x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Cameras"),
                x509.NameAttribute(NameOID.COMMON_NAME, camera_id),
            ]))
            .issuer_name(self.ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(serial)
            .not_valid_before(start)
            .not_valid_after(start + dt.timedelta(days=valid_days))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(camera_id)]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(self.ca_key.public_key()), critical=False)
            .sign(self.ca_key, hashes.SHA256())
        )
        d = Path(out_dir or self.devices_dir)
        d.mkdir(parents=True, exist_ok=True)
        stem = f"{camera_id}-{serial:x}"[:80]
        crt_path, key_path = d / f"{stem}.crt", d / f"{stem}.key"
        crt_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
        if record:
            self.registry[f"{serial:x}"] = DeviceRecord(
                camera_id=camera_id, serial=f"{serial:x}", not_before=start.isoformat(),
                not_after=(start + dt.timedelta(days=valid_days)).isoformat(), cert_path=str(crt_path))
            self._save()
        return crt_path, key_path, serial

    def renew_camera(self, camera_id: str, valid_days: float = 30) -> Tuple[Path, Path, int]:
        """Rotation: issues a fresh key + cert. The old cert stays valid (overlap window)
        until ``revoke(old_serial, 'superseded')`` once the camera confirms the switch."""
        for r in self.registry.values():
            if r.camera_id == camera_id and r.status == "active":
                r.status = "superseded"
        self._save()
        return self.issue_camera(camera_id, valid_days=valid_days)

    # ── revocation ───────────────────────────────────────────────────────────
    def revoke(self, serial: int | str, reason: str = "unspecified", when: Optional[dt.datetime] = None) -> None:
        key = serial if isinstance(serial, str) else f"{serial:x}"
        key = key.lower().removeprefix("0x")
        rec = self.registry.get(key)
        if rec is None:
            rec = DeviceRecord(camera_id="unknown", serial=key, not_before="", not_after="", cert_path="")
            self.registry[key] = rec
        rec.status = "revoked"
        rec.revoked_at = (when or dt.datetime.now(UTC)).isoformat()
        rec.reason = reason
        self._save()

    def revoked(self) -> List[DeviceRecord]:
        return [r for r in self.registry.values() if r.status == "revoked"]

    def write_crl(self, next_update_days: float = 7, path: Optional[Path] = None) -> Path:
        """Signs and writes the CRL. Re-issue before ``next_update`` or every handshake
        fails with 'CRL has expired' (fail-closed by design)."""
        now = dt.datetime.now(UTC)
        out = Path(path or self.crl_path)
        # The gateway hot-reloads CRLs into the same OpenSSL store, which keeps the
        # CRL with the newest lastUpdate; make lastUpdate strictly increasing so a
        # CRL written within the same second as the previous one still wins.
        last_update = now - dt.timedelta(minutes=1)
        if out.exists():
            try:
                prev = x509.load_pem_x509_crl(out.read_bytes()).last_update_utc
                last_update = max(last_update, prev + dt.timedelta(seconds=1))
            except ValueError:
                pass
        builder = (
            x509.CertificateRevocationListBuilder()
            .issuer_name(self.ca_cert.subject)
            .last_update(last_update)
            .next_update(now + dt.timedelta(days=next_update_days))
        )
        for r in self.revoked():
            revoked_at = dt.datetime.fromisoformat(r.revoked_at) if r.revoked_at else now
            entry = (
                x509.RevokedCertificateBuilder()
                .serial_number(int(r.serial, 16))
                .revocation_date(min(revoked_at, now))
                .add_extension(x509.CRLReason(REASONS.get(r.reason or "unspecified", x509.ReasonFlags.unspecified)), critical=False)
                .build()
            )
            builder = builder.add_revoked_certificate(entry)
        crl = builder.sign(self.ca_key, hashes.SHA256())
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(crl.public_bytes(serialization.Encoding.PEM))
        os.replace(tmp, out)  # atomic: the gateway never reads a half-written CRL
        return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AEGIS camera certificate lifecycle")
    ap.add_argument("--certs-dir", default=str(DEFAULT_CERTS_DIR))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("issue"); p.add_argument("--camera-id", required=True); p.add_argument("--days", type=float, default=30)
    p = sub.add_parser("renew"); p.add_argument("--camera-id", required=True); p.add_argument("--days", type=float, default=30)
    p = sub.add_parser("revoke"); p.add_argument("--serial", required=True); p.add_argument("--reason", default="unspecified", choices=sorted(REASONS))
    sub.add_parser("crl")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    ca = DeviceCA.load(args.certs_dir)
    if args.cmd == "issue":
        crt, key, serial = ca.issue_camera(args.camera_id, args.days)
        print(f"issued {args.camera_id} serial={serial:x}\n  cert {crt}\n  key  {key}")
    elif args.cmd == "renew":
        crt, key, serial = ca.renew_camera(args.camera_id, args.days)
        print(f"renewed {args.camera_id} serial={serial:x} (revoke the superseded serial once the camera has switched)")
    elif args.cmd == "revoke":
        ca.revoke(args.serial, args.reason)
        print(f"revoked {args.serial}; CRL -> {ca.write_crl()}")
    elif args.cmd == "crl":
        print(f"CRL -> {ca.write_crl()} ({len(ca.revoked())} revoked)")
    elif args.cmd == "list":
        for r in ca.registry.values():
            print(f"{r.serial:>34}  {r.status:10s} {r.camera_id:20s} until {r.not_after}  {r.reason or ''}")
    return 0


if __name__ == "__main__":
    _repo = Path(__file__).resolve().parents[2]
    if str(_repo) not in sys.path:
        sys.path.insert(0, str(_repo))
    sys.exit(main())
