"""
AEGIS evidence key & custody control CLI — Week 11 Task 4
=========================================================

    python -m security.forensics.keyctl init       --keyring DIR --node-id NODE
    python -m security.forensics.keyctl rotate     --keyring DIR --node-id NODE
    python -m security.forensics.keyctl revoke     --keyring DIR --kid KID --at 2026-11-16T10:00:00+00:00 --reason "laptop stolen"
    python -m security.forensics.keyctl export     --keyring DIR --out published/trusted_keys.json
    python -m security.forensics.keyctl list       --keyring DIR
    python -m security.forensics.keyctl tsa-init   --dir DIR                      # in-house RFC 3161 TSA
    python -m security.forensics.keyctl checkpoint --vault VAULT_DIR              # uses AEGIS_VAULT_KEYRING_DIR
    python -m security.forensics.keyctl audit      --vault VAULT_DIR --trusted-keys published/trusted_keys.json \
                                                   [--tsa-cert tsa.pem] [--checkpoints external_checkpoints.jsonl]

Private keys are encrypted with AEGIS_VAULT_KEY_PASSPHRASE when it is set.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import List, Optional

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from security.forensics.evidence_vault import UnifiedEvidenceVault  # noqa: E402
from security.forensics.keyring import SigningKeyring, TrustedKeys  # noqa: E402
from security.forensics.timestamping import LocalTimestampAuthority, load_trusted_tsa_certs  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AEGIS evidence signing key and custody management")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "rotate"):
        p = sub.add_parser(name)
        p.add_argument("--keyring", required=True)
        p.add_argument("--node-id", required=True)
    p = sub.add_parser("revoke")
    p.add_argument("--keyring", required=True)
    p.add_argument("--kid", required=True)
    p.add_argument("--at", help="ISO-8601 compromise time (default: now)")
    p.add_argument("--reason", default="key compromise")
    p = sub.add_parser("export")
    p.add_argument("--keyring", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("list")
    p.add_argument("--keyring", required=True)
    p = sub.add_parser("tsa-init")
    p.add_argument("--dir", required=True)
    p = sub.add_parser("checkpoint")
    p.add_argument("--vault", required=True)
    p = sub.add_parser("audit")
    p.add_argument("--vault", required=True)
    p.add_argument("--trusted-keys", required=True)
    p.add_argument("--tsa-cert", action="append")
    p.add_argument("--checkpoints", help="JSONL of checkpoints retained OUTSIDE the vault host")
    args = ap.parse_args(argv)

    if args.cmd in ("init", "rotate"):
        kr = SigningKeyring(args.keyring)
        kid = kr.ensure_active(args.node_id) if args.cmd == "init" else kr.rotate(args.node_id)
        print(f"active signing key: {kid}")
    elif args.cmd == "revoke":
        at = dt.datetime.fromisoformat(args.at) if args.at else None
        SigningKeyring(args.keyring).revoke(args.kid, revoked_at=at, reason=args.reason)
        print(f"revoked {args.kid}; re-export and re-publish the trusted keyring now")
    elif args.cmd == "export":
        print(f"public keyring -> {SigningKeyring(args.keyring).export_trusted(args.out)}")
    elif args.cmd == "list":
        for r in SigningKeyring(args.keyring).list():
            print(f"{r.kid}  {r.status:8s} node={r.node_id} created={r.created_at} retired={r.retired_at} revoked={r.revoked_at}")
    elif args.cmd == "tsa-init":
        tsa = LocalTimestampAuthority.load_or_create(args.dir)
        print(f"TSA certificate: {Path(args.dir) / 'tsa.crt'} ({tsa.cert.subject.rfc4514_string()})")
    elif args.cmd == "checkpoint":
        vault = UnifiedEvidenceVault(vault_dir=args.vault)
        print(json.dumps(vault.create_checkpoint()))
    elif args.cmd == "audit":
        vault = UnifiedEvidenceVault(vault_dir=args.vault)
        cps = None
        if args.checkpoints:
            cps = [json.loads(l) for l in Path(args.checkpoints).read_text(encoding="utf-8").splitlines() if l.strip()]
        audit = vault.verify_vault_integrity(
            trusted_keys=TrustedKeys.load(args.trusted_keys),
            tsa_trust=load_trusted_tsa_certs(args.tsa_cert) if args.tsa_cert else None,
            checkpoints=cps,
        )
        print(audit.summary())
        for e in audit.errors[:50]:
            print(f"  [ERROR] {e}")
        for w in audit.warnings[:20]:
            print(f"  [WARN]  {w}")
        return 0 if audit.is_valid else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
