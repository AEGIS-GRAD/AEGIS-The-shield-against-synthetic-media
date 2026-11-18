"""
AEGIS Trusted Timestamping (RFC 3161) — Week 11 Task 4
======================================================

Why this exists
---------------
Every vault record carries ``created_at_utc`` taken from the evidence node's own
clock. That value is self-asserted: an operator holding the signing key (or an
attacker who changed the system clock) can back-date a record and it still
verifies. A trusted timestamp from an independent Time-Stamping Authority (TSA)
proves that a given digest existed no later than the TSA's ``genTime``. It is
also what keeps old evidence valid after a signing key is later revoked: a
signature that was timestamped *before* the compromise date is still trusted.

What is implemented
-------------------
* ``build_timestamp_request`` / ``RFC3161HttpClient`` — standard RFC 3161
  ``TimeStampReq`` over HTTP (``application/timestamp-query``), usable against any
  public or commercial TSA (FreeTSA, DigiCert, Sectigo, a national TSA).
* ``LocalTimestampAuthority`` — an in-house RFC 3161 responder (ECDSA P-256,
  ``id-kp-timeStamping`` certificate) for air-gapped deployments and tests. Its
  tokens are genuine DER ``TimeStampToken``s that ``openssl ts -verify`` accepts.
  Run it as a separate trust domain (its own host/HSM and key), never with the
  evidence node's signing key.
* ``verify_timestamp_token`` — offline verification: imprint match, nonce,
  CMS signed-attribute digest, ESSCertIDv2 binding, signature, EKU and validity
  period, and trust anchoring to a pinned TSA certificate or issuing CA.

Only the SHA-256 *digest* of evidence is ever sent to a TSA, never the evidence.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

from asn1crypto import algos, cms, core, tsp
from asn1crypto import x509 as ax509
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# Private-arc policy OID for the AEGIS local TSA (replace with an IANA PEN arc
# if the project registers one). External TSAs report their own policy OID.
AEGIS_TSA_POLICY_OID = "1.3.6.1.4.1.57264.1.1"

UTC = dt.timezone.utc


class TimestampError(Exception):
    """Raised when a timestamp cannot be obtained or does not verify."""


@dataclass(frozen=True)
class TimestampVerification:
    gen_time: dt.datetime
    serial_number: int
    policy: str
    nonce: Optional[int]
    tsa_subject: str
    tsa_cert_sha256: str
    accuracy_seconds: Optional[float]


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


# ─────────────────────────────────────────────────────────────────────────────
# Requests
# ─────────────────────────────────────────────────────────────────────────────
def build_timestamp_request(digest: bytes, nonce: Optional[int] = None, cert_req: bool = True) -> bytes:
    """DER-encoded RFC 3161 TimeStampReq for a SHA-256 digest."""
    if len(digest) != 32:
        raise ValueError("RFC 3161 requests here are SHA-256 only (32-byte digest expected)")
    fields = {
        "version": "v1",
        "message_imprint": tsp.MessageImprint({
            "hash_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
            "hashed_message": digest,
        }),
        "cert_req": cert_req,
    }
    if nonce is not None:
        fields["nonce"] = nonce
    return tsp.TimeStampReq(fields).dump()


def parse_timestamp_response(resp_der: bytes):
    """Returns (status, status_text, token_der_or_None) from a DER TimeStampResp.

    Parsed generically because asn1crypto treats ``time_stamp_token`` as mandatory
    while RFC 3161 omits it on rejection.
    """
    try:
        seq = core.Sequence.load(resp_der)
        status_info = tsp.PKIStatusInfo.load(seq[0].dump())
        token_der = seq[1].dump() if len(seq) > 1 else None
    except Exception as exc:
        raise TimestampError(f"malformed TimeStampResp: {exc}") from exc
    status = status_info["status"].native
    text = None
    if status_info["status_string"].native:
        text = "; ".join(status_info["status_string"].native)
    return status, text, token_der


def token_from_response(resp_der: bytes) -> bytes:
    """Extracts the TimeStampToken (CMS ContentInfo DER) from a TimeStampResp."""
    status, text, token_der = parse_timestamp_response(resp_der)
    if status not in ("granted", "granted_with_mods"):
        raise TimestampError(f"TSA refused the request: status={status} {text or ''}".strip())
    if not token_der:
        raise TimestampError("TSA response granted but carries no token")
    return token_der


# ─────────────────────────────────────────────────────────────────────────────
# Local RFC 3161 authority
# ─────────────────────────────────────────────────────────────────────────────
def _name(common_name: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AEGIS"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Forensic Time-Stamping"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])


def issue_tsa_certificate(
    tsa_key: ec.EllipticCurvePrivateKey,
    common_name: str = "AEGIS Local TSA",
    issuer_key=None,
    issuer_cert: Optional[x509.Certificate] = None,
    valid_days: int = 3650,
    not_before: Optional[dt.datetime] = None,
) -> x509.Certificate:
    """Issues a TSA certificate with the critical id-kp-timeStamping EKU (RFC 3161 §2.3)."""
    now = not_before or (dt.datetime.now(UTC) - dt.timedelta(minutes=5))
    subject = _name(common_name)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_cert.subject if issuer_cert is not None else subject)
        .public_key(tsa_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(tsa_key.public_key()), critical=False)
    )
    signer = issuer_key if issuer_key is not None else tsa_key
    return builder.sign(signer, hashes.SHA256())


class LocalTimestampAuthority:
    """Minimal RFC 3161 responder (ECDSA P-256 / SHA-256).

    ``clock`` is injectable so tests can model clock skew; in production it must
    be the TSA host's NTP/PTP-disciplined UTC clock, not the evidence node's.
    """

    def __init__(
        self,
        key: Optional[ec.EllipticCurvePrivateKey] = None,
        cert: Optional[x509.Certificate] = None,
        policy_oid: str = AEGIS_TSA_POLICY_OID,
        clock: Optional[Callable[[], dt.datetime]] = None,
        accuracy_seconds: int = 1,
    ):
        self.key = key or ec.generate_private_key(ec.SECP256R1())
        self.cert = cert or issue_tsa_certificate(self.key)
        self.policy_oid = policy_oid
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.accuracy_seconds = accuracy_seconds
        self._serial = int.from_bytes(secrets.token_bytes(6), "big")
        self._lock = threading.Lock()
        self._cert_der = self.cert.public_bytes(serialization.Encoding.DER)

    # Persistence -----------------------------------------------------------
    def save(self, directory: Path | str, passphrase: Optional[bytes] = None) -> None:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        enc = serialization.BestAvailableEncryption(passphrase) if passphrase else serialization.NoEncryption()
        (d / "tsa.key").write_bytes(self.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc))
        (d / "tsa.crt").write_bytes(self.cert.public_bytes(serialization.Encoding.PEM))

    @classmethod
    def load(cls, directory: Path | str, passphrase: Optional[bytes] = None, **kw) -> "LocalTimestampAuthority":
        d = Path(directory)
        key = serialization.load_pem_private_key((d / "tsa.key").read_bytes(), password=passphrase)
        cert = x509.load_pem_x509_certificate((d / "tsa.crt").read_bytes())
        return cls(key=key, cert=cert, **kw)

    @classmethod
    def load_or_create(cls, directory: Path | str, passphrase: Optional[bytes] = None, **kw) -> "LocalTimestampAuthority":
        d = Path(directory)
        if (d / "tsa.key").exists() and (d / "tsa.crt").exists():
            return cls.load(d, passphrase, **kw)
        tsa = cls(**kw)
        tsa.save(d, passphrase)
        return tsa

    # RFC 3161 --------------------------------------------------------------
    def respond(self, request_der: bytes) -> bytes:
        """Handles a DER TimeStampReq and returns a DER TimeStampResp."""
        try:
            req = tsp.TimeStampReq.load(request_der)
            imprint = req["message_imprint"]
            if imprint["hash_algorithm"]["algorithm"].native != "sha256":
                return self._rejection("bad_alg", "only SHA-256 imprints are accepted")
            if len(imprint["hashed_message"].native) != 32:
                return self._rejection("bad_data_format", "imprint length does not match SHA-256")
            nonce = req["nonce"].native if req["nonce"].native is not None else None
        except Exception as exc:  # malformed request
            return self._rejection("bad_request", f"malformed TimeStampReq: {exc}")

        with self._lock:
            self._serial += 1
            serial = self._serial
        gen_time = self.clock().astimezone(UTC)

        tst_fields = {
            "version": "v1",
            "policy": self.policy_oid,
            "message_imprint": imprint,
            "serial_number": serial,
            "gen_time": gen_time,
            "accuracy": tsp.Accuracy({"seconds": self.accuracy_seconds}),
            "ordering": False,
        }
        if nonce is not None:
            tst_fields["nonce"] = nonce
        tst_der = tsp.TSTInfo(tst_fields).dump()

        asn_cert = ax509.Certificate.load(self._cert_der)

        def signed_attrs() -> cms.CMSAttributes:
            return cms.CMSAttributes([
                cms.CMSAttribute({"type": "content_type", "values": ["tst_info"]}),
                cms.CMSAttribute({"type": "message_digest", "values": [sha256(tst_der)]}),
                cms.CMSAttribute({"type": "signing_certificate_v2", "values": [tsp.SigningCertificateV2({
                    "certs": [tsp.ESSCertIDv2({
                        "hash_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
                        "cert_hash": sha256(self._cert_der),
                    })],
                })]}),
            ])

        to_sign = signed_attrs().dump()  # universal SET OF encoding, as RFC 5652 §5.4 requires
        signature = self.key.sign(to_sign, ec.ECDSA(hashes.SHA256()))

        signer_info = cms.SignerInfo({
            "version": "v1",
            "sid": cms.SignerIdentifier({
                "issuer_and_serial_number": cms.IssuerAndSerialNumber({
                    "issuer": asn_cert.issuer, "serial_number": asn_cert.serial_number,
                }),
            }),
            "digest_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
            "signed_attrs": signed_attrs(),
            "signature_algorithm": algos.SignedDigestAlgorithm({"algorithm": "sha256_ecdsa"}),
            "signature": signature,
        })
        signed_data = cms.SignedData({
            "version": "v3",
            "digest_algorithms": [algos.DigestAlgorithm({"algorithm": "sha256"})],
            "encap_content_info": cms.EncapsulatedContentInfo({
                "content_type": "tst_info",
                "content": core.ParsableOctetString(tst_der),
            }),
            "certificates": [asn_cert],
            "signer_infos": [signer_info],
        })
        token = cms.ContentInfo({"content_type": "signed_data", "content": signed_data})
        return tsp.TimeStampResp({
            "status": tsp.PKIStatusInfo({"status": "granted"}),
            "time_stamp_token": token,
        }).dump()

    def _rejection(self, failure: str, text: str) -> bytes:
        # asn1crypto marks time_stamp_token as mandatory, but RFC 3161 §2.4.2 omits
        # it on rejection, so the outer SEQUENCE is encoded by hand.
        status = tsp.PKIStatusInfo({
            "status": "rejection",
            "status_string": [text],
            "fail_info": tsp.PKIFailureInfo({failure}),
        }).dump()
        n = len(status)
        length = bytes([n]) if n < 0x80 else (b"\x81" + bytes([n]) if n < 0x100 else b"\x82" + n.to_bytes(2, "big"))
        return b"\x30" + length + status

    def timestamp(self, digest: bytes, nonce: Optional[int] = None) -> bytes:
        """Convenience: digest -> TimeStampToken DER."""
        return token_from_response(self.respond(build_timestamp_request(digest, nonce)))


class RFC3161HttpClient:
    """RFC 3161 client for an external TSA over HTTP(S).

    ``transport`` lets tests route requests to a ``LocalTimestampAuthority``
    without network access (``httpx.MockTransport``).
    """

    def __init__(self, url: str, timeout: float = 10.0, transport=None, headers: Optional[dict] = None):
        self.url = url
        self.timeout = timeout
        self.transport = transport
        self.headers = headers or {}

    def timestamp(self, digest: bytes, nonce: Optional[int] = None) -> bytes:
        import httpx

        nonce = nonce if nonce is not None else secrets.randbits(63)
        req = build_timestamp_request(digest, nonce)
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            r = client.post(self.url, content=req, headers={
                "Content-Type": "application/timestamp-query", **self.headers})
        if r.status_code != 200:
            raise TimestampError(f"TSA HTTP {r.status_code}")
        token = token_from_response(r.content)
        # Bind the response to *this* request (anti-replay of TSA responses).
        verify_timestamp_token(token, digest, trusted=None, expected_nonce=nonce, require_trust=False)
        return token


# ─────────────────────────────────────────────────────────────────────────────
# Verification
# ─────────────────────────────────────────────────────────────────────────────
def _crypto_cert(asn_cert: ax509.Certificate) -> x509.Certificate:
    return x509.load_der_x509_certificate(asn_cert.dump())


def _verify_sig(public_key, signature: bytes, data: bytes) -> None:
    if isinstance(public_key, ec.EllipticCurvePublicKey):
        public_key.verify(signature, data, ec.ECDSA(hashes.SHA256()))
    elif isinstance(public_key, rsa.RSAPublicKey):
        public_key.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
    elif isinstance(public_key, ed25519.Ed25519PublicKey):
        public_key.verify(signature, data)
    else:
        raise TimestampError(f"Unsupported TSA key type {type(public_key).__name__}")


def _is_trusted(signer: x509.Certificate, trusted: Sequence[x509.Certificate]) -> bool:
    signer_fp = signer.fingerprint(hashes.SHA256())
    for anchor in trusted:
        if anchor.fingerprint(hashes.SHA256()) == signer_fp:
            return True
        if anchor.subject == signer.issuer:
            try:
                signer.verify_directly_issued_by(anchor)
                return True
            except (ValueError, TypeError, InvalidSignature):
                continue
    return False


def verify_timestamp_token(
    token_der: bytes,
    digest: bytes,
    trusted: Optional[Sequence[x509.Certificate]] = None,
    expected_nonce: Optional[int] = None,
    require_trust: bool = True,
) -> TimestampVerification:
    """Verifies an RFC 3161 TimeStampToken over ``digest``. Raises TimestampError."""
    try:
        token = cms.ContentInfo.load(token_der)
        if token["content_type"].native != "signed_data":
            raise TimestampError("token is not CMS SignedData")
        sd = token["content"]
        eci = sd["encap_content_info"]
        if eci["content_type"].native != "tst_info":
            raise TimestampError("encapsulated content is not TSTInfo")
        tst_der = eci["content"].contents
        tst = tsp.TSTInfo.load(tst_der)
    except TimestampError:
        raise
    except Exception as exc:
        raise TimestampError(f"malformed timestamp token: {exc}") from exc

    imprint = tst["message_imprint"]
    if imprint["hash_algorithm"]["algorithm"].native != "sha256":
        raise TimestampError("timestamp imprint is not SHA-256")
    if imprint["hashed_message"].native != digest:
        raise TimestampError("timestamp imprint does not match the evidence digest")
    nonce = tst["nonce"].native
    if expected_nonce is not None and nonce != expected_nonce:
        raise TimestampError("timestamp nonce mismatch (possible replayed TSA response)")

    signer_infos = sd["signer_infos"]
    if len(signer_infos) != 1:
        raise TimestampError("expected exactly one SignerInfo")
    si = signer_infos[0]

    certs: List[x509.Certificate] = []
    for choice in (sd["certificates"] or []):
        if choice.name == "certificate":
            certs.append(_crypto_cert(choice.chosen))
    sid = si["sid"]
    signer_cert: Optional[x509.Certificate] = None
    if sid.name == "issuer_and_serial_number":
        want_serial = sid.chosen["serial_number"].native
        for c in list(certs) + list(trusted or []):
            if c.serial_number == want_serial:
                signer_cert = c
                break
    if signer_cert is None:
        raise TimestampError("TSA signing certificate not found in token or trust store")

    attrs = {a["type"].native: a["values"] for a in si["signed_attrs"]}
    if attrs.get("content_type") is None or attrs["content_type"][0].native != "tst_info":
        raise TimestampError("signed content-type attribute is not TSTInfo")
    if attrs.get("message_digest") is None or attrs["message_digest"][0].native != sha256(tst_der):
        raise TimestampError("signed message-digest does not match TSTInfo (token altered)")
    cert_der = signer_cert.public_bytes(serialization.Encoding.DER)
    if attrs.get("signing_certificate_v2") is not None:
        ess = attrs["signing_certificate_v2"][0]["certs"][0]
        if ess["cert_hash"].native != sha256(cert_der):
            raise TimestampError("ESSCertIDv2 does not match the TSA certificate")

    signed_bytes = b"\x31" + si["signed_attrs"].dump()[1:]
    try:
        _verify_sig(signer_cert.public_key(), si["signature"].native, signed_bytes)
    except InvalidSignature as exc:
        raise TimestampError("TSA signature is invalid") from exc

    try:
        eku = signer_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        if ExtendedKeyUsageOID.TIME_STAMPING not in eku.value:
            raise TimestampError("TSA certificate lacks id-kp-timeStamping EKU")
    except x509.ExtensionNotFound as exc:
        raise TimestampError("TSA certificate lacks an Extended Key Usage extension") from exc

    gen_time = tst["gen_time"].native
    if gen_time.tzinfo is None:
        gen_time = gen_time.replace(tzinfo=UTC)
    if not (signer_cert.not_valid_before_utc <= gen_time <= signer_cert.not_valid_after_utc):
        raise TimestampError("genTime is outside the TSA certificate validity period")

    if require_trust:
        if not trusted:
            raise TimestampError("no trusted TSA certificates configured")
        if not _is_trusted(signer_cert, trusted):
            raise TimestampError("TSA certificate is not trusted (unknown TSA)")

    accuracy = None
    if tst["accuracy"].native:
        acc = tst["accuracy"].native
        accuracy = float(acc.get("seconds") or 0) + float(acc.get("millis") or 0) / 1e3 + float(acc.get("micros") or 0) / 1e6

    return TimestampVerification(
        gen_time=gen_time,
        serial_number=int(tst["serial_number"].native),
        policy=tst["policy"].dotted,
        nonce=nonce,
        tsa_subject=signer_cert.subject.rfc4514_string(),
        tsa_cert_sha256=signer_cert.fingerprint(hashes.SHA256()).hex(),
        accuracy_seconds=accuracy,
    )


def load_trusted_tsa_certs(paths: Iterable[Path | str]) -> List[x509.Certificate]:
    out: List[x509.Certificate] = []
    for p in paths:
        data = Path(p).read_bytes()
        try:
            out.extend(x509.load_pem_x509_certificates(data))
        except ValueError:
            out.append(x509.load_der_x509_certificate(data))
    return out


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))
