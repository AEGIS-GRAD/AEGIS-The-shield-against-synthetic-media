"""
AEGIS Evidence Sealing — Week 11 Task 4
=======================================

A *seal* is the court-facing authenticity proof attached to every vault record
and ledger checkpoint:

    seal = {
      "v": 1, "alg": "Ed25519", "kid": <signing key id>, "node_id": <evidence node>,
      "sig": Ed25519( "AEGIS-SEAL-v1|<record_id>|<record_hash>" ),
      "tst": RFC3161 TimeStampToken over SHA-256(message || sig)   # optional but expected
    }

``record_hash`` already commits to the full manifest (input hash, detector
outputs, model versions, calibration version, judge transcript) and to the
previous ledger record, so one signature covers content *and* position in the
chain. Timestamping the signature (not just the record) is what lets a verifier
keep trusting records signed before a key was revoked.

The legacy HMAC fields are left in place for backward compatibility; seals are
additive and verifiers that are given a trusted keyring require them.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from cryptography import x509

from .keyring import SigningKeyring, TrustedKeys
from .timestamping import TimestampError, b64, unb64, verify_timestamp_token

logger = logging.getLogger("aegis.forensics.sealing")
UTC = dt.timezone.utc
SEAL_VERSION = 1
DEFAULT_MAX_CLOCK_SKEW_S = 120.0


def seal_message(record_id: str, record_hash: str) -> bytes:
    return f"AEGIS-SEAL-v{SEAL_VERSION}|{record_id}|{record_hash}".encode("utf-8")


def checkpoint_message(ledger_size: int, head_hash: str, head_record_id: str) -> bytes:
    return f"AEGIS-CHECKPOINT-v{SEAL_VERSION}|{ledger_size}|{head_record_id}|{head_hash}".encode("utf-8")


def _tst_digest(message: bytes, sig_b64: str) -> bytes:
    return hashlib.sha256(message + base64.b64decode(sig_b64)).digest()


class EvidenceSealer:
    """Signs (and timestamps) record hashes and ledger checkpoints for one node.

    ``tsa`` is any object with ``timestamp(digest: bytes) -> bytes`` returning a
    DER TimeStampToken (``LocalTimestampAuthority`` or ``RFC3161HttpClient``).
    A TSA outage never blocks evidence capture: the seal is written without a
    token and ``tst_error`` records why, so the gap is visible in audits.
    """

    def __init__(self, keyring: SigningKeyring, node_id: str, tsa=None):
        self.keyring = keyring
        self.node_id = node_id
        self.tsa = tsa
        self.keyring.ensure_active(node_id)

    def _seal_message(self, message: bytes) -> Dict[str, Any]:
        kid, sig = self.keyring.sign(message)
        seal: Dict[str, Any] = {"v": SEAL_VERSION, "alg": "Ed25519", "kid": kid, "node_id": self.node_id, "sig": sig}
        if self.tsa is not None:
            try:
                seal["tst"] = b64(self.tsa.timestamp(_tst_digest(message, sig)))
            except Exception as exc:  # TSA down / refused: keep capturing, flag the gap
                logger.error("Trusted timestamp unavailable, sealing without it: %s", exc)
                seal["tst_error"] = str(exc)[:200]
        return seal

    def seal(self, record_id: str, record_hash: str) -> Dict[str, Any]:
        return self._seal_message(seal_message(record_id, record_hash))

    def seal_checkpoint(self, ledger_size: int, head_hash: str, head_record_id: str) -> Dict[str, Any]:
        return self._seal_message(checkpoint_message(ledger_size, head_hash, head_record_id))


def sealer_from_env() -> Optional["EvidenceSealer"]:
    """Builds a sealer from deployment environment variables, or None if not configured.

        AEGIS_VAULT_KEYRING_DIR     keyring directory (enables sealing)
        AEGIS_NODE_ID               evidence node identity (default: hostname)
        AEGIS_VAULT_KEY_PASSPHRASE  passphrase protecting the private key at rest
        AEGIS_TSA_URL               external RFC 3161 TSA (preferred for court use)
        AEGIS_LOCAL_TSA_DIR         in-house RFC 3161 TSA key/cert (air-gapped sites)
    """
    import os
    import socket

    keyring_dir = os.environ.get("AEGIS_VAULT_KEYRING_DIR")
    if not keyring_dir:
        return None
    from .timestamping import LocalTimestampAuthority, RFC3161HttpClient

    tsa = None
    if os.environ.get("AEGIS_TSA_URL"):
        tsa = RFC3161HttpClient(os.environ["AEGIS_TSA_URL"])
    elif os.environ.get("AEGIS_LOCAL_TSA_DIR"):
        tsa = LocalTimestampAuthority.load_or_create(os.environ["AEGIS_LOCAL_TSA_DIR"])
    else:
        logger.warning("Evidence sealing enabled without a TSA: record times will be self-asserted.")
    node_id = os.environ.get("AEGIS_NODE_ID") or socket.gethostname()
    return EvidenceSealer(SigningKeyring(keyring_dir), node_id=node_id, tsa=tsa)


@dataclass
class SealCheck:
    ok: bool
    reason: str
    kid: Optional[str] = None
    node_id: Optional[str] = None
    tsa_time: Optional[dt.datetime] = None
    tsa_trusted: bool = False
    clock_skew_s: Optional[float] = None
    warnings: Optional[List[str]] = None


def verify_message_seal(
    seal: Optional[Dict[str, Any]],
    message: bytes,
    trusted_keys: TrustedKeys,
    tsa_trust: Optional[Sequence[x509.Certificate]] = None,
    require_timestamp: bool = False,
    claimed_time: Optional[str] = None,
    max_clock_skew_s: float = DEFAULT_MAX_CLOCK_SKEW_S,
) -> SealCheck:
    if not seal:
        return SealCheck(False, "record is not sealed (no Ed25519 seal present)")
    if seal.get("alg") != "Ed25519" or seal.get("v") != SEAL_VERSION:
        return SealCheck(False, f"unsupported seal format alg={seal.get('alg')} v={seal.get('v')}")
    kid, sig = seal.get("kid", ""), seal.get("sig", "")
    warnings: List[str] = []

    tsa_time: Optional[dt.datetime] = None
    tsa_trusted = False
    if seal.get("tst"):
        try:
            v = verify_timestamp_token(unb64(seal["tst"]), _tst_digest(message, sig),
                                       trusted=tsa_trust, require_trust=bool(tsa_trust))
            tsa_time, tsa_trusted = v.gen_time, bool(tsa_trust)
        except TimestampError as exc:
            return SealCheck(False, f"trusted timestamp invalid: {exc}", kid=kid)
        if not tsa_trusted:
            warnings.append("timestamp present but no trusted TSA configured; time not relied upon")
    elif require_timestamp:
        why = f" ({seal['tst_error']})" if seal.get("tst_error") else ""
        return SealCheck(False, f"seal has no trusted timestamp{why}", kid=kid)

    signed_at = tsa_time if tsa_trusted else None
    ok, reason = trusted_keys.verify(kid, message, sig, signed_at=signed_at)
    if not ok:
        return SealCheck(False, reason, kid=kid, tsa_time=tsa_time, tsa_trusted=tsa_trusted)

    skew = None
    if claimed_time and tsa_time is not None:
        try:
            claimed = dt.datetime.fromisoformat(claimed_time)
            claimed = claimed if claimed.tzinfo else claimed.replace(tzinfo=UTC)
            skew = (claimed - tsa_time).total_seconds()
            if abs(skew) > max_clock_skew_s:
                if tsa_trusted:
                    return SealCheck(False, (
                        f"claimed creation time {claimed_time} differs from trusted timestamp "
                        f"{tsa_time.isoformat()} by {skew:+.0f}s (> {max_clock_skew_s:.0f}s): back/forward-dated "
                        "record or node clock skew"), kid=kid, tsa_time=tsa_time, tsa_trusted=True, clock_skew_s=skew)
                warnings.append(f"node clock differs from TSA time by {skew:+.0f}s")
        except ValueError:
            warnings.append(f"unparseable claimed time '{claimed_time}'")

    return SealCheck(True, reason, kid=kid, node_id=seal.get("node_id"), tsa_time=tsa_time,
                     tsa_trusted=tsa_trusted, clock_skew_s=skew, warnings=warnings or None)


def verify_record_seal(seal, record_id: str, record_hash: str, trusted_keys: TrustedKeys, **kw) -> SealCheck:
    return verify_message_seal(seal, seal_message(record_id, record_hash), trusted_keys, **kw)


def verify_checkpoint_seal(checkpoint: Dict[str, Any], trusted_keys: TrustedKeys, **kw) -> SealCheck:
    msg = checkpoint_message(int(checkpoint["ledger_size"]), checkpoint["head_hash"], checkpoint["head_record_id"])
    return verify_message_seal(checkpoint.get("seal"), msg, trusted_keys, **kw)
