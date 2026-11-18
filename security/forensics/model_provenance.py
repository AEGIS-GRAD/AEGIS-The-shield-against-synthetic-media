"""
AEGIS Model Provenance — Week 11 Task 4
=======================================

A verification record names the models that produced it (``model_versions``),
but a version string is only a label: replacing ``AASIST.pth`` on disk with a
different checkpoint leaves every label unchanged. Recording the SHA-256 of the
weight files at inference time (``model_fingerprints``) lets an examiner prove
which exact weights produced a verdict, and lets the vault detect a silent swap.

CLI::

    python -m security.forensics.model_provenance --write security/forensics/model_fingerprints.json
    python -m security.forensics.model_provenance --check security/forensics/model_fingerprints.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

# Weight files shipped with (or downloaded into) the repository, keyed by detector id.
DEFAULT_MODEL_WEIGHTS: Dict[str, Path] = {
    "edge_mobilenetv3_int8": REPO_ROOT / "engine" / "edge_model" / "mobilenetv3_small_int8.onnx",
    "edge_mobilenetv3_fp32": REPO_ROOT / "engine" / "edge_model" / "mobilenetv3_small_fp32.onnx",
    "video-classifier": REPO_ROOT / "detectors" / "video-classifier" / "models" / "efficientnet_b0_ffpp_finetuned.pth",
    "aasist": REPO_ROOT / "detectors" / "aasist" / "AASIST.pth",
    "detector_text_lora": REPO_ROOT / "detectors" / "text-detector" / "models" / "desklib-finetuned" / "lora_adapter" / "adapter_model.safetensors",
    "detector_text_base": REPO_ROOT / "detectors" / "text-detector" / "models" / "desklib-base" / "model.safetensors",
    "detector_image": REPO_ROOT / "detectors" / "image" / "weights" / "model.safetensors",
}


def fingerprint_file(path: Path | str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def fingerprint_models(weights: Optional[Mapping[str, Path | str]] = None) -> Dict[str, str]:
    """SHA-256 of every weight file that exists (missing files are skipped)."""
    out: Dict[str, str] = {}
    for name, path in (weights or DEFAULT_MODEL_WEIGHTS).items():
        p = Path(path)
        if p.is_file():
            out[name] = fingerprint_file(p)
    return out


def compare_fingerprints(recorded: Mapping[str, str], current: Mapping[str, str]) -> List[str]:
    """Human-readable mismatches between fingerprints in a record and weights now on disk."""
    problems = []
    for name, digest in recorded.items():
        now = current.get(name)
        if now is None:
            problems.append(f"{name}: weights recorded as {digest[:12]}... are no longer present")
        elif now != digest:
            problems.append(f"{name}: weights changed since the verdict ({digest[:12]}... -> {now[:12]}...)")
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Pin or check SHA-256 fingerprints of AEGIS model weights")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", metavar="JSON")
    g.add_argument("--check", metavar="JSON")
    args = ap.parse_args(argv)
    current = fingerprint_models()
    if args.write:
        Path(args.write).write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Pinned {len(current)} model fingerprints -> {args.write}")
        return 0
    pinned = json.loads(Path(args.check).read_text(encoding="utf-8"))
    problems = compare_fingerprints(pinned, current)
    for p in problems:
        print(f"[FAIL] {p}")
    if not problems:
        print(f"[PASS] {len(pinned)} model weight files match their pinned fingerprints")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
