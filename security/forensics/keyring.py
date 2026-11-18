"""
AEGIS Evidence Signing Keyring — Week 11 Task 4
================================================

Replaces the shared HMAC secret as the *authenticity* mechanism for evidence.

Problem with the legacy scheme
------------------------------
The vault signs records and bundles with HMAC-SHA256 under
``DEFAULT_SIGNING_KEY = b"aegis_surveillance_node_secret_key_v1"``, a constant
committed to the repository. HMAC is symmetric: whoever can *verify* a bundle
(a defence expert, a court-appointed examiner) must hold the same secret and can
therefore *forge* one. With the default key, anyone with a copy of the repo can.

Scheme
------
* Each evidence node holds an Ed25519 signing key. Verifiers only need the
  **public** keyring (``trusted_keys.json``), so verification cannot forge.
* Keys are identified by ``kid`` = first 16 hex chars of SHA-256(raw public key).
* Lifecycle: ``active`` (signs) -> ``retired`` (verify-only after rotation) ->
  optionally ``revoked`` (compromised, with a compromise time).
* Revocation is time-aware: a signature is accepted from a revoked key only if
  a trusted RFC 3161 timestamp proves it was made *before* ``revoked_at``. This
  is why seals are timestamped (see ``sealing.py``).
* Private keys are stored PKCS#8, encrypted with ``AEGIS_VAULT_KEY_PASSPHRASE``
  when set. In production the private key belongs in an HSM / TPM / cloud KMS;
  this file-based keyring is the reference implementation and the interface the
  vault codes against (see docs/key_management_and_custody.md).
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = logging.getLogger("aegis.forensics.keyring")
UTC = dt.timezone.utc

ACTIVE, RETIRED, REVOKED = "active", "retired", "revoked"


def _now() -> dt.datetime:
    return dt.datetime.now(UTC)


def _iso(t: Optional[dt.datetime]) -> Optional[str]:
    return t.astimezone(UTC).isoformat() if t else None


def _parse(t: Optional[str]) -> Optional[dt.datetime]:
    if not t:
        return None
    v = dt.datetime.fromisoformat(t)
    return v if v.tzinfo else v.replace(tzinfo=UTC)


def kid_for(public_key: ed25519.Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass
class KeyRecord:
    kid: str
    node_id: str
    public_key_b64: str
    status: str = ACTIVE
    created_at: str = field(default_factory=lambda: _iso(_now()))
    retired_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revocation_reason: Optional[str] = None

    def public_key(self) -> ed25519.Ed25519PublicKey:
        return ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(self.public_key_b64))


class KeyringError(Exception):
    pass


class TrustedKeys:
    """Public, verify-only view of a keyring (what verifiers and courts receive)."""

    def __init__(self, records: Dict[str, KeyRecord]):
        self.records = records

    @classmethod
    def load(cls, path: Path | str) -> "TrustedKeys":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls({k["kid"]: KeyRecord(**k) for k in data.get("keys", [])})

    def to_json(self) -> str:
        return json.dumps({"format": "aegis-trusted-keys-v1",
                           "keys": [asdict(r) for r in self.records.values()]}, indent=2)

    def verify(self, kid: str, message: bytes, signature_b64: str,
               signed_at: Optional[dt.datetime] = None) -> Tuple[bool, str]:
        """Verifies a signature and applies lifecycle rules.

        ``signed_at`` must come from a *trusted timestamp*, never from the record
        itself (a self-asserted time is exactly what an attacker would forge).
        """
        rec = self.records.get(kid)
        if rec is None:
            return False, f"unknown signing key '{kid}' (not in the trusted keyring)"
        try:
            rec.public_key().verify(base64.b64decode(signature_b64), message)
        except (InvalidSignature, ValueError):
            return False, f"Ed25519 signature invalid for key '{kid}'"
        if rec.status == REVOKED:
            revoked_at = _parse(rec.revoked_at)
            if signed_at is None:
                return False, f"key '{kid}' is revoked and the signature has no trusted timestamp"
            if revoked_at is None or signed_at >= revoked_at:
                return False, f"key '{kid}' was revoked at {rec.revoked_at}; signature time {signed_at.isoformat()} is not before it"
            return True, f"signed by '{kid}' before its revocation ({rec.revocation_reason or 'no reason'})"
        if rec.status == RETIRED and signed_at is not None:
            retired_at = _parse(rec.retired_at)
            if retired_at is not None and signed_at > retired_at + dt.timedelta(minutes=5):
                return False, f"key '{kid}' was retired at {rec.retired_at} but signed at {signed_at.isoformat()}"
        return True, f"valid signature by '{kid}' ({rec.status}, node {rec.node_id})"


class SigningKeyring:
    """File-backed Ed25519 keyring for one evidence node."""

    def __init__(self, directory: Path | str, passphrase: Optional[bytes] = None):
        self.dir = Path(directory)
        self.private_dir = self.dir / "private"
        self.meta_path = self.dir / "keyring.json"
        env_pass = os.environ.get("AEGIS_VAULT_KEY_PASSPHRASE")
        self.passphrase = passphrase if passphrase is not None else (env_pass.encode() if env_pass else None)
        self._lock = threading.Lock()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.private_dir.mkdir(parents=True, exist_ok=True)
        self.records: Dict[str, KeyRecord] = {}
        if self.meta_path.exists():
            data = json.loads(self.meta_path.read_text(encoding="utf-8"))
            self.records = {k["kid"]: KeyRecord(**k) for k in data.get("keys", [])}
        self._private_cache: Dict[str, ed25519.Ed25519PrivateKey] = {}

    # -- persistence --------------------------------------------------------
    def _save(self) -> None:
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"format": "aegis-keyring-v1",
                                   "keys": [asdict(r) for r in self.records.values()]}, indent=2), encoding="utf-8")
        os.replace(tmp, self.meta_path)

    def _write_private(self, kid: str, key: ed25519.Ed25519PrivateKey) -> None:
        if self.passphrase:
            enc = serialization.BestAvailableEncryption(self.passphrase)
        else:
            logger.warning("Storing evidence signing key %s UNENCRYPTED (set AEGIS_VAULT_KEY_PASSPHRASE or use an HSM).", kid)
            enc = serialization.NoEncryption()
        path = self.private_dir / f"{kid}.pem"
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _load_private(self, kid: str) -> ed25519.Ed25519PrivateKey:
        if kid not in self._private_cache:
            path = self.private_dir / f"{kid}.pem"
            if not path.exists():
                raise KeyringError(f"private key for '{kid}' is not on this node")
            key = serialization.load_pem_private_key(path.read_bytes(), password=self.passphrase)
            if not isinstance(key, ed25519.Ed25519PrivateKey):
                raise KeyringError(f"key '{kid}' is not Ed25519")
            self._private_cache[kid] = key
        return self._private_cache[kid]

    # -- lifecycle ----------------------------------------------------------
    def active_kid(self) -> Optional[str]:
        for r in self.records.values():
            if r.status == ACTIVE:
                return r.kid
        return None

    def generate(self, node_id: str) -> str:
        """Creates a new active key; the previous active key (if any) is retired."""
        with self._lock:
            key = ed25519.Ed25519PrivateKey.generate()
            kid = kid_for(key.public_key())
            now = _iso(_now())
            for r in self.records.values():
                if r.status == ACTIVE:
                    r.status, r.retired_at = RETIRED, now
            raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            self.records[kid] = KeyRecord(kid=kid, node_id=node_id, public_key_b64=base64.b64encode(raw).decode())
            self._write_private(kid, key)
            self._private_cache[kid] = key
            self._save()
            logger.info("Generated evidence signing key %s for node %s", kid, node_id)
            return kid

    rotate = generate

    def ensure_active(self, node_id: str) -> str:
        return self.active_kid() or self.generate(node_id)

    def revoke(self, kid: str, revoked_at: Optional[dt.datetime] = None, reason: str = "key compromise",
               destroy_private: bool = True) -> None:
        """Marks a key compromised from ``revoked_at`` (default: now)."""
        with self._lock:
            rec = self.records.get(kid)
            if rec is None:
                raise KeyringError(f"unknown key '{kid}'")
            rec.status = REVOKED
            rec.revoked_at = _iso(revoked_at or _now())
            rec.revocation_reason = reason
            if rec.retired_at is None:
                rec.retired_at = rec.revoked_at
            self._save()
            if destroy_private:
                self._private_cache.pop(kid, None)
                p = self.private_dir / f"{kid}.pem"
                if p.exists():
                    p.unlink()

    def sign(self, message: bytes) -> Tuple[str, str]:
        kid = self.active_kid()
        if kid is None:
            raise KeyringError("no active signing key; call generate()/ensure_active() first")
        sig = self._load_private(kid).sign(message)
        return kid, base64.b64encode(sig).decode()

    def trusted(self) -> TrustedKeys:
        return TrustedKeys({k: KeyRecord(**asdict(v)) for k, v in self.records.items()})

    def export_trusted(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.trusted().to_json(), encoding="utf-8")
        return p

    def node_of(self, kid: str) -> Optional[str]:
        r = self.records.get(kid)
        return r.node_id if r else None

    def list(self) -> List[KeyRecord]:
        return list(self.records.values())
