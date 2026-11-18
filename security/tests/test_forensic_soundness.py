"""
Week 11 Task 4 — Forensic soundness: tampering, trusted time, key management.

Each attack is run twice:
  * against the LEGACY scheme (HMAC with the key committed to the repo) to record
    whether the attack succeeded before this task — these tests assert the
    vulnerability so the report's "before" column is reproducible;
  * against the SEALED scheme (Ed25519 node key + RFC 3161 timestamps + signed
    ledger checkpoints) to prove the attack is now detected.

Run:  pytest security/tests/test_forensic_soundness.py -v
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import shutil
import sys
import threading
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from security.forensics import evidence_vault as ev  # noqa: E402
from security.forensics.evidence_vault import DEFAULT_SIGNING_KEY, UnifiedEvidenceVault  # noqa: E402
from security.forensics.keyring import SigningKeyring, TrustedKeys  # noqa: E402
from security.forensics.model_provenance import compare_fingerprints, fingerprint_models  # noqa: E402
from security.forensics.sealing import EvidenceSealer, verify_record_seal  # noqa: E402
from security.forensics.timestamping import (  # noqa: E402
    LocalTimestampAuthority,
    RFC3161HttpClient,
    TimestampError,
    build_timestamp_request,
    sha256,
    verify_timestamp_token,
)
from security.forensics.verify_bundle import verify_bundle  # noqa: E402

UTC = dt.timezone.utc


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures and helpers
# ─────────────────────────────────────────────────────────────────────────────
class Node:
    """A sealed evidence node: vault + Ed25519 keyring + trusted TSA."""

    def __init__(self, root: Path, node_id: str = "aegis-node-01", tsa: LocalTimestampAuthority | None = None):
        self.keyring = SigningKeyring(root / "keys", passphrase=b"test-passphrase")
        self.tsa = tsa or LocalTimestampAuthority()
        self.sealer = EvidenceSealer(self.keyring, node_id=node_id, tsa=self.tsa)
        self.vault = UnifiedEvidenceVault(vault_dir=root / "vault", sealer=self.sealer)
        self.published_keys = self.keyring.export_trusted(root / "published" / "trusted_keys.json")
        self.tsa_cert_path = root / "published" / "tsa.pem"
        from cryptography.hazmat.primitives import serialization

        self.tsa_cert_path.write_bytes(self.tsa.cert.public_bytes(serialization.Encoding.PEM))

    @property
    def trusted(self) -> TrustedKeys:
        return TrustedKeys.load(self.keyring.export_trusted(self.published_keys))

    def audit(self, **kw):
        return self.vault.verify_vault_integrity(trusted_keys=self.trusted, tsa_trust=[self.tsa.cert], **kw)


def _populate(vault: UnifiedEvidenceVault, n: int = 4, fingerprints=None):
    recs = []
    for i in range(n):
        recs.append(vault.store_verification(
            job_id=f"job-{i:04d}-abcdef",
            modality=["image", "text", "video", "audio"][i % 4],
            input_filename=f"input_{i}.bin",
            input_bytes=f"payload-{i}".encode() * 10,
            verdict="SYNTHETIC" if i % 2 == 0 else "AUTHENTIC",
            calibrated_score=0.9 if i % 2 == 0 else 0.1,
            detector_outputs=[{"detector": "detector_image", "status": "ok", "raw_score": 0.9, "confidence": 0.9, "latency_ms": 10}],
            model_versions={"detector_image": "commfor-model-384-fp16"},
            judge_transcript={"judge_mode": "deterministic", "rounds": [], "forensic_justification": "test"},
            model_fingerprints=fingerprints,
        ))
    return recs


def _rewrite_with_hmac(vault: UnifiedEvidenceVault, mutate_manifest=None, drop_index: int | None = None,
                       key: bytes = DEFAULT_SIGNING_KEY) -> None:
    """Attacker who knows the (public) HMAC key edits/deletes records and re-chains
    every later record so the legacy audit passes. Seals cannot be re-created
    without the node's private key, so they are carried over untouched."""
    entries = [json.loads(l) for l in vault.ledger_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    out, prev = [], ev.GENESIS_HASH
    for pos, entry in enumerate(entries):
        idx = entry["record_index"]
        is_ver = entry.get("record_type") == "VERIFICATION"
        mdir = vault.verifications_dir if is_ver else vault.incidents_dir
        mpath = mdir / f"{entry['incident_id']}.json"
        if drop_index is not None and idx == drop_index:
            mpath.unlink()
            continue
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        if mutate_manifest is not None:
            mutate_manifest(idx, manifest)
        manifest["record_index"] = len(out) + 1
        manifest["prev_record_hash"] = prev
        manifest["record_hash"] = ""
        manifest["signature"] = ""
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        rec_hash = hashlib.sha256(f"{prev}:{entry['incident_id']}:{entry['created_at_utc']}:{digest}".encode()).hexdigest()
        sig = hmac.new(key, rec_hash.encode(), hashlib.sha256).hexdigest()
        manifest["record_hash"], manifest["signature"] = rec_hash, sig
        mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        entry.update({"record_index": len(out) + 1, "prev_record_hash": prev, "manifest_digest": digest,
                      "record_hash": rec_hash, "signature": sig})
        out.append(entry)
        prev = rec_hash
    vault.ledger_path.write_text("".join(json.dumps(e) + "\n" for e in out), encoding="utf-8")


def _resign_bundle_with_hmac(src: Path, dst: Path, edit) -> None:
    """Attacker edits evidence.json/report.md inside a bundle and re-signs every
    HMAC (record + bundle) with the public default key."""
    with zipfile.ZipFile(src) as zf:
        files = {n: zf.read(n) for n in zf.namelist()}
    evidence = json.loads(files["evidence.json"])
    edit(evidence)
    evidence["record_hash"], evidence["signature"] = "", ""
    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    rid = evidence.get("verification_id") or evidence.get("incident_id")
    rec_hash = hashlib.sha256(f"{evidence['prev_record_hash']}:{rid}:{evidence['created_at_utc']}:{digest}".encode()).hexdigest()
    evidence["record_hash"] = rec_hash
    evidence["signature"] = hmac.new(DEFAULT_SIGNING_KEY, rec_hash.encode(), hashlib.sha256).hexdigest()
    files["evidence.json"] = json.dumps(evidence, indent=2, sort_keys=True).encode()
    files["report.md"] = files["report.md"].replace(b"SYNTHETIC", b"AUTHENTIC")
    payload = [k for k in files if k.startswith("payload/")][0]
    hashes_txt = (f"{hashlib.sha256(files['evidence.json']).hexdigest()}  evidence.json\n"
                  f"{hashlib.sha256(files['report.md']).hexdigest()}  report.md\n"
                  f"{hashlib.sha256(files[payload]).hexdigest()}  {payload}\n")
    files["hashes.sha256"] = hashes_txt.encode()
    hs, es = hashlib.sha256(files["hashes.sha256"]).hexdigest(), hashlib.sha256(files["evidence.json"]).hexdigest()
    files["bundle_signature.sig"] = json.dumps({
        "algorithm": "HMAC-SHA256", "record_id": rid, "hashes_sha256": hs, "evidence_sha256": es,
        "signature": hmac.new(DEFAULT_SIGNING_KEY, f"{hs}:{es}".encode(), hashlib.sha256).hexdigest()}).encode()
    with zipfile.ZipFile(dst, "w") as zf:
        for n, b in files.items():
            zf.writestr(n, b)


@pytest.fixture
def node(tmp_path):
    return Node(tmp_path / "node")


# ─────────────────────────────────────────────────────────────────────────────
# Baseline
# ─────────────────────────────────────────────────────────────────────────────
def test_clean_sealed_vault_passes_full_audit(node):
    _populate(node.vault, 4)
    node.vault.store_incident(camera_id="cam-01", threat_type="HASH_CHAIN_BREAK", sequence_number=7,
                              timestamp_ms=280, primary_frame_bytes=b"\x89PNG frame")
    cp = node.vault.create_checkpoint()
    audit = node.audit(checkpoints=[cp])
    assert audit.is_valid, audit.errors
    assert audit.sealed_records == 5 and audit.verified_records == 5 and audit.checkpoints_verified == 1


# ─────────────────────────────────────────────────────────────────────────────
# Attack 1 — modify a stored report
# ─────────────────────────────────────────────────────────────────────────────
def test_attack_modify_report_naive_edit_detected_even_by_legacy(node):
    recs = _populate(node.vault, 3)
    path = node.vault.verifications_dir / f"{recs[0].verification_id}.json"
    m = json.loads(path.read_text())
    m["verdict"] = "AUTHENTIC"
    path.write_text(json.dumps(m, indent=2))
    assert not node.vault.verify_vault_integrity().is_valid


def test_attack_modify_report_with_public_hmac_key_beats_legacy_but_not_seals(node):
    recs = _populate(node.vault, 3)
    target = recs[0].record_index

    def flip(idx, m):
        if idx == target:
            m["verdict"], m["calibrated_score"] = "AUTHENTIC", 0.02

    _rewrite_with_hmac(node.vault, mutate_manifest=flip)
    legacy = node.vault.verify_vault_integrity()
    assert legacy.is_valid, "legacy HMAC audit is expected to be fooled (key is public)"
    sealed = node.audit()
    assert not sealed.is_valid
    assert any("Seal verification failed" in e for e in sealed.errors)


def test_attack_modify_bundle_report_resigned_with_public_key(node, tmp_path):
    recs = _populate(node.vault, 1)
    bundle = node.vault.export_signed_bundle(recs[0].verification_id, tmp_path / "orig.zip")
    forged = tmp_path / "forged.zip"
    _resign_bundle_with_hmac(bundle, forged, lambda e: e.update(verdict="AUTHENTIC", calibrated_score=0.01))

    ok_legacy, _ = verify_bundle(forged)
    assert ok_legacy, "legacy offline verifier is expected to accept the re-signed forgery"
    ok_sealed, msg = verify_bundle(forged, trusted_keys_path=str(node.published_keys),
                                   tsa_cert_paths=[str(node.tsa_cert_path)])
    assert not ok_sealed and "different record" in msg
    ok_orig, msg = verify_bundle(bundle, trusted_keys_path=str(node.published_keys),
                                 tsa_cert_paths=[str(node.tsa_cert_path)])
    assert ok_orig, msg


# ─────────────────────────────────────────────────────────────────────────────
# Attack 2 — delete a record
# ─────────────────────────────────────────────────────────────────────────────
def test_attack_delete_middle_record_detected_by_chain(node):
    _populate(node.vault, 4)
    lines = node.vault.ledger_path.read_text().splitlines()
    del lines[1]
    node.vault.ledger_path.write_text("\n".join(lines) + "\n")
    audit = node.vault.verify_vault_integrity()
    assert not audit.is_valid and audit.broken_records


def test_attack_delete_tail_record_undetected_without_checkpoint(node):
    recs = _populate(node.vault, 4)
    cp_external = node.vault.create_checkpoint()  # shipped to the SIEM before the attack
    lines = node.vault.ledger_path.read_text().splitlines()
    node.vault.ledger_path.write_text("\n".join(lines[:-1]) + "\n")
    (node.vault.verifications_dir / f"{recs[-1].verification_id}.json").unlink()
    node.vault.checkpoints_path.unlink()  # attacker also wipes the local checkpoint log

    assert node.vault.verify_vault_integrity().is_valid, "pure chain audit cannot see a removed tail"
    assert node.audit().is_valid, "seals alone cannot see a removed tail either"
    audit = node.audit(checkpoints=[cp_external])
    assert not audit.is_valid and any("Ledger truncated" in e for e in audit.errors)


def test_attack_delete_and_rechain_detected_by_seals_and_checkpoint(node):
    recs = _populate(node.vault, 4)
    cp_external = node.vault.create_checkpoint()
    _rewrite_with_hmac(node.vault, drop_index=recs[1].record_index)
    assert node.vault.verify_vault_integrity().is_valid, "legacy audit fooled by re-chaining"
    audit = node.audit(checkpoints=[cp_external])
    assert not audit.is_valid
    assert any("Seal verification failed" in e for e in audit.errors)
    assert any("truncated" in e or "rewritten" in e for e in audit.errors)


def test_forged_checkpoint_rejected(node):
    _populate(node.vault, 3)
    cp = node.vault.create_checkpoint()
    forged = dict(cp, ledger_size=1)
    audit = node.audit(checkpoints=[forged])
    assert not audit.is_valid and any("seal invalid" in e for e in audit.errors)


# ─────────────────────────────────────────────────────────────────────────────
# Attack 3 — replay a bundle
# ─────────────────────────────────────────────────────────────────────────────
def test_attack_replay_bundle_from_other_node_rejected(node, tmp_path):
    rogue = Node(tmp_path / "rogue", node_id="dev-laptop")  # e.g. a dev/test vault
    r = _populate(rogue.vault, 1)[0]
    bundle = rogue.vault.export_signed_bundle(r.verification_id, tmp_path / "rogue.zip")
    assert verify_bundle(bundle)[0], "legacy verifier accepts any bundle signed with the shared default key"
    ok, msg = verify_bundle(bundle, trusted_keys_path=str(node.published_keys))
    assert not ok and "unknown signing key" in msg


def test_attack_replay_unsealed_legacy_bundle_rejected(node, tmp_path):
    legacy = UnifiedEvidenceVault(vault_dir=tmp_path / "legacy")
    r = _populate(legacy, 1)[0]
    bundle = legacy.export_signed_bundle(r.verification_id, tmp_path / "legacy.zip")
    assert verify_bundle(bundle)[0]
    ok, msg = verify_bundle(bundle, trusted_keys_path=str(node.published_keys))
    assert not ok and "not sealed" in msg


def test_attack_seal_transplant_between_records_rejected(node, tmp_path):
    a, b = _populate(node.vault, 2)
    ba = node.vault.export_signed_bundle(a.verification_id, tmp_path / "a.zip")
    bb = node.vault.export_signed_bundle(b.verification_id, tmp_path / "b.zip")
    with zipfile.ZipFile(ba) as za:
        seal_a = json.loads(za.read("seal.json"))
    with zipfile.ZipFile(bb) as zb:
        files = {n: zb.read(n) for n in zb.namelist()}
    seal_a["record_id"], seal_a["record_hash"] = b.verification_id, b.record_hash  # relabel A's seal as B's
    files["seal.json"] = json.dumps(seal_a).encode()
    spliced = tmp_path / "spliced.zip"
    with zipfile.ZipFile(spliced, "w") as zf:
        for n, data in files.items():
            zf.writestr(n, data)
    ok, msg = verify_bundle(spliced, trusted_keys_path=str(node.published_keys))
    # Caught by the timestamp imprint (bound to the original message) or the Ed25519 signature.
    assert not ok and ("signature invalid" in msg or "imprint does not match" in msg), msg


def test_attack_backdated_record_by_insider_rejected(node):
    """Insider holds the node signing key (not the TSA key) and back-dates a record two days."""
    real_datetime = ev.datetime

    class Backdated(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.now(tz) - dt.timedelta(days=2)

    ev.datetime = Backdated
    try:
        rec = _populate(node.vault, 1)[0]
    finally:
        ev.datetime = real_datetime
    audit = node.audit()
    assert not audit.is_valid
    assert any("differs from trusted timestamp" in e for e in audit.errors)
    # Without a trusted TSA the back-dating would only be a warning-free pass:
    weak = node.vault.verify_vault_integrity(trusted_keys=node.trusted)
    assert weak.is_valid and rec.created_at_utc < dt.datetime.now(UTC).isoformat()


def test_attack_reuse_timestamp_token_from_other_record_rejected(node):
    a, b = _populate(node.vault, 2)
    entries = [json.loads(l) for l in node.vault.ledger_path.read_text().splitlines()]
    entries[1]["seal"]["tst"] = entries[0]["seal"]["tst"]
    node.vault.ledger_path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    audit = node.audit()
    assert not audit.is_valid and any("imprint does not match" in e for e in audit.errors)


def test_attack_stripped_timestamp_rejected_when_tsa_required(node):
    _populate(node.vault, 1)
    entries = [json.loads(l) for l in node.vault.ledger_path.read_text().splitlines()]
    del entries[0]["seal"]["tst"]
    node.vault.ledger_path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    audit = node.audit()
    assert not audit.is_valid and any("no trusted timestamp" in e for e in audit.errors)


# ─────────────────────────────────────────────────────────────────────────────
# Attack 4 — swap model versions
# ─────────────────────────────────────────────────────────────────────────────
def test_attack_swap_model_version_label_resigned(node):
    recs = _populate(node.vault, 2)

    def swap(idx, m):
        if idx == recs[0].record_index:
            m["model_versions"] = {"detector_image": "commfor-model-384-fp16-VALIDATED-v2"}

    _rewrite_with_hmac(node.vault, mutate_manifest=swap)
    assert node.vault.verify_vault_integrity().is_valid, "legacy audit fooled"
    assert not node.audit().is_valid


def test_attack_swap_model_weights_on_disk_detected_by_fingerprint(node, tmp_path):
    weights = tmp_path / "weights.bin"
    weights.write_bytes(b"genuine checkpoint bytes" * 100)
    pinned = fingerprint_models({"detector_image": weights})
    rec = _populate(node.vault, 1, fingerprints=pinned)[0]
    assert node.audit().is_valid
    weights.write_bytes(b"backdoored checkpoint bytes" * 100)  # same file name, same version label
    problems = compare_fingerprints(rec.model_fingerprints, fingerprint_models({"detector_image": weights}))
    assert problems and "weights changed" in problems[0]

    def scrub(idx, m):  # attacker tries to hide it by editing the recorded fingerprint
        m["model_fingerprints"] = fingerprint_models({"detector_image": weights})

    _rewrite_with_hmac(node.vault, mutate_manifest=scrub)
    assert not node.audit().is_valid


# ─────────────────────────────────────────────────────────────────────────────
# Key management — rotation, revocation, storage
# ─────────────────────────────────────────────────────────────────────────────
def test_key_rotation_keeps_old_evidence_valid(node):
    old_kid = node.keyring.active_kid()
    _populate(node.vault, 2)
    new_kid = node.keyring.rotate("aegis-node-01")
    assert new_kid != old_kid
    _populate(node.vault, 2)
    entries = [json.loads(l) for l in node.vault.ledger_path.read_text().splitlines()]
    assert [e["seal"]["kid"] for e in entries] == [old_kid, old_kid, new_kid, new_kid]
    assert node.audit().is_valid


def test_revoked_key_rejects_post_compromise_signatures_only(node, tmp_path):
    _populate(node.vault, 2)  # honest records, timestamped before the compromise
    stolen_kid = node.keyring.active_kid()
    stolen_copy = tmp_path / "stolen.pem"
    shutil.copy(node.keyring.private_dir / f"{stolen_kid}.pem", stolen_copy)  # attacker exfiltrates the key

    compromise_time = dt.datetime.now(UTC)
    node.keyring.revoke(stolen_kid, revoked_at=compromise_time, reason="laptop stolen")
    node.keyring.rotate("aegis-node-01")
    _populate(node.vault, 1)  # new honest record under the new key
    assert node.audit().is_valid, "pre-compromise records stay valid thanks to trusted timestamps"

    # Attacker forges a record with the stolen key after revocation.
    attacker = SigningKeyring(tmp_path / "attacker", passphrase=b"test-passphrase")
    attacker.records[stolen_kid] = node.keyring.records[stolen_kid].__class__(
        **{**node.keyring.records[stolen_kid].__dict__, "status": "active"})
    (attacker.private_dir / f"{stolen_kid}.pem").write_bytes(stolen_copy.read_bytes())
    forged_sealer = EvidenceSealer(attacker, node_id="aegis-node-01", tsa=node.tsa)
    node.vault.sealer = forged_sealer
    _populate(node.vault, 1)
    audit = node.audit()
    assert not audit.is_valid and any("revoked" in e for e in audit.errors)


def test_revoked_key_without_timestamp_is_not_trusted(node):
    _populate(node.vault, 1)
    entries = [json.loads(l) for l in node.vault.ledger_path.read_text().splitlines()]
    kid = entries[0]["seal"]["kid"]
    node.keyring.revoke(kid)
    chk = verify_record_seal(entries[0]["seal"], entries[0]["incident_id"], entries[0]["record_hash"],
                             node.trusted, tsa_trust=None)
    assert not chk.ok and "no trusted timestamp" in chk.reason


def test_private_key_is_encrypted_at_rest(node):
    kid = node.keyring.active_kid()
    pem = (node.keyring.private_dir / f"{kid}.pem").read_bytes()
    assert b"ENCRYPTED" in pem
    with pytest.raises(Exception):
        SigningKeyring(node.keyring.dir, passphrase=b"wrong").sign(b"x")


def test_published_keyring_contains_no_private_material(node):
    text = Path(node.published_keys).read_text()
    assert "PRIVATE" not in text and "public_key_b64" in text


# ─────────────────────────────────────────────────────────────────────────────
# Concurrency — two writers must not fork the chain
# ─────────────────────────────────────────────────────────────────────────────
def test_concurrent_writers_on_same_vault_do_not_fork_chain(node):
    second = UnifiedEvidenceVault(vault_dir=node.vault.vault_dir, sealer=node.sealer)  # e.g. alert router

    def writer(v, tag):
        for i in range(15):
            v.store_incident(camera_id=f"cam-{tag}", threat_type="SEQUENCE_ANOMALY", sequence_number=i,
                             timestamp_ms=i * 40, primary_frame_bytes=f"{tag}-{i}".encode())

    threads = [threading.Thread(target=writer, args=(v, t)) for v, t in ((node.vault, "a"), (second, "b"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    audit = node.audit()
    assert audit.is_valid, audit.errors[:3]
    assert audit.total_records == 30


# ─────────────────────────────────────────────────────────────────────────────
# Trusted timestamping (RFC 3161)
# ─────────────────────────────────────────────────────────────────────────────
def test_rfc3161_token_roundtrip_and_failure_modes():
    tsa = LocalTimestampAuthority()
    d = sha256(b"evidence")
    tok = tsa.timestamp(d, nonce=99)
    v = verify_timestamp_token(tok, d, trusted=[tsa.cert], expected_nonce=99)
    assert abs((v.gen_time - dt.datetime.now(UTC)).total_seconds()) < 5
    for bad in (
        lambda: verify_timestamp_token(tok, sha256(b"other"), trusted=[tsa.cert]),
        lambda: verify_timestamp_token(tok, d, trusted=[LocalTimestampAuthority().cert]),
        lambda: verify_timestamp_token(tok, d, trusted=[tsa.cert], expected_nonce=1),
        lambda: verify_timestamp_token(tok[:-30] + bytes([tok[-30] ^ 0xFF]) + tok[-29:], d, trusted=[tsa.cert]),
    ):
        with pytest.raises(TimestampError):
            bad()


def test_rfc3161_http_client_against_mock_tsa():
    import httpx

    tsa = LocalTimestampAuthority()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["content-type"] == "application/timestamp-query"
        return httpx.Response(200, content=tsa.respond(request.content),
                              headers={"content-type": "application/timestamp-reply"})

    client = RFC3161HttpClient("https://tsa.example.test/tsr", transport=httpx.MockTransport(handler))
    d = sha256(b"frame")
    token = client.timestamp(d)
    assert verify_timestamp_token(token, d, trusted=[tsa.cert]).tsa_subject.startswith("CN=AEGIS Local TSA")


def test_tsa_rejects_malformed_request():
    from security.forensics.timestamping import parse_timestamp_response, token_from_response

    tsa = LocalTimestampAuthority()
    resp = tsa.respond(b"\x30\x03\x02\x01\x01")
    status, text, token = parse_timestamp_response(resp)
    assert status == "rejection" and token is None and "malformed" in text
    with pytest.raises(TimestampError, match="refused"):
        token_from_response(resp)
    with pytest.raises(ValueError):
        build_timestamp_request(b"short")


def test_tsa_outage_does_not_block_capture_but_is_flagged(node):
    class DownTSA:
        def timestamp(self, digest):
            raise TimestampError("connection refused")

    node.vault.sealer = EvidenceSealer(node.keyring, "aegis-node-01", tsa=DownTSA())
    _populate(node.vault, 1)
    entry = json.loads(node.vault.ledger_path.read_text().splitlines()[0])
    assert "tst" not in entry["seal"] and "connection refused" in entry["seal"]["tst_error"]
    audit = node.audit()
    assert not audit.is_valid and any("no trusted timestamp" in e for e in audit.errors)
