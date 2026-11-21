"""Verification suite for Task 5 container hardening, pinned dependencies, and safe model loading."""

from __future__ import annotations

import os
import pickle
import re
from pathlib import Path

import pytest
import torch

from security.supply_chain.model_integrity import (
    ModelIntegrityError,
    compute_sha256,
    load_weights_manifest,
    safe_torch_load,
    verify_file_sha256,
    verify_registered_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class _ExploitPayload:
    """Pickle gadget that creates a marker file if unsafe deserialization occurs."""

    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def __reduce__(self):
        return (Path.write_text, (self.marker, "pwned"))


def test_weights_manifest_contains_commfor_and_desklib_hashes():
    artifacts = load_weights_manifest()
    assert "detectors/image/weights/model.safetensors" in artifacts
    assert "detectors/text-detector/models/desklib-base/model.safetensors" in artifacts
    assert "detectors/text-detector/models/desklib-finetuned/lora_adapter/adapter_model.safetensors" in artifacts

    for key, entry in artifacts.items():
        digest = entry["sha256"]
        assert re.fullmatch(r"[0-9a-f]{64}", digest), f"Invalid sha256 for {key}: {digest}"
        if entry.get("source_type") == "huggingface_hub":
            assert re.fullmatch(r"[0-9a-f]{40}", entry["revision"]), (
                f"Expected pinned 40-char HF commit revision for {key}"
            )


def test_tracked_weights_verify_against_manifest():
    tracked_core = [
        "detectors/aasist/AASIST.pth",
        "detectors/text-detector/models/desklib-finetuned/lora_adapter/adapter_model.safetensors",
        "detectors/video-classifier/models/efficientnet_b0_df40_finetuned.pth",
        "detectors/video-classifier/models/ffpp_legacy_baseline/efficientnet_b0_ffpp_finetuned.pth",
        "engine/edge_model/mobilenetv3_small_ffpp.pth",
    ]
    for rel in tracked_core:
        if (REPO_ROOT / rel).is_file():
            digest = verify_registered_artifact(rel, require_exists=True)
            assert digest == compute_sha256(REPO_ROOT / rel)


def test_safe_torch_load_rejects_tampered_digest(tmp_path: Path):
    ckpt = tmp_path / "weights.pth"
    torch.save({"w": torch.ones(2, 2)}, ckpt)
    valid_sha = compute_sha256(ckpt)
    loaded = safe_torch_load(ckpt, map_location="cpu", expected_sha256=valid_sha)
    assert torch.equal(loaded["w"], torch.ones(2, 2))

    tampered_sha = ("0" if valid_sha[0] != "0" else "1") + valid_sha[1:]
    with pytest.raises(ModelIntegrityError, match="SHA-256 mismatch"):
        safe_torch_load(ckpt, map_location="cpu", expected_sha256=tampered_sha)


def test_safe_torch_load_blocks_malicious_pickle_gadget(tmp_path: Path):
    marker = tmp_path / "pwned.txt"
    bad_ckpt = tmp_path / "malicious.pth"
    with bad_ckpt.open("wb") as handle:
        pickle.dump(_ExploitPayload(marker), handle)

    with pytest.raises(ModelIntegrityError):
        safe_torch_load(bad_ckpt, map_location="cpu")

    assert not marker.exists(), "Unsafe pickle gadget executed despite safe_torch_load!"


def test_no_weights_only_false_or_trust_remote_code_in_production_code():
    import ast

    code_roots = ["detectors", "engine", "orchestrator", "security", "live_pipeline", "debate", "mcp"]
    offenders = []
    for root in code_roots:
        root_dir = REPO_ROOT / root
        if not root_dir.exists():
            continue
        for py_file in root_dir.rglob("*.py"):
            if "tests" in py_file.parts or "archive" in py_file.parts:
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8-sig", errors="ignore"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if (
                            kw.arg == "weights_only"
                            and isinstance(kw.value, ast.Constant)
                            and kw.value.value is False
                        ):
                            offenders.append(f"{py_file.relative_to(REPO_ROOT)}:weights_only=False")
                        if (
                            kw.arg == "trust_remote_code"
                            and isinstance(kw.value, ast.Constant)
                            and kw.value.value is True
                        ):
                            offenders.append(f"{py_file.relative_to(REPO_ROOT)}:trust_remote_code=True")
    assert not offenders, f"Unsafe loader flags found: {offenders}"


def test_video_classifier_rejects_malicious_checkpoint(tmp_path: Path):
    import sys

    vc_dir = str(REPO_ROOT / "detectors" / "video-classifier")
    inserted = False
    if vc_dir not in sys.path:
        sys.path.insert(0, vc_dir)
        inserted = True
    try:
        from infer import load_model

        marker = tmp_path / "vc_pwned.txt"
        bad_ckpt = tmp_path / "evil_vc.pth"
        with bad_ckpt.open("wb") as handle:
            pickle.dump(_ExploitPayload(marker), handle)

        with pytest.raises(Exception):
            load_model(device="cpu", checkpoint_path=bad_ckpt)

        assert not marker.exists(), "video-classifier fell back to unsafe pickle execution!"
    finally:
        if inserted and vc_dir in sys.path:
            sys.path.remove(vc_dir)


def test_all_dockerfiles_have_non_root_user_and_healthcheck():
    dockerfiles = sorted(
        p for p in REPO_ROOT.rglob("Dockerfile")
        if "venv" not in p.parts and "node_modules" not in p.parts and "Community-Forensics" not in p.parts
    )
    assert len(dockerfiles) >= 12
    for df in dockerfiles:
        text = df.read_text(encoding="utf-8")
        users = [
            line.strip().split()[1]
            for line in text.splitlines()
            if re.match(r"^\s*USER\s+\S+", line)
        ]
        assert users, f"Missing USER directive in {df.relative_to(REPO_ROOT)}"
        assert users[-1].lower() not in {"root", "0", "0:0"}, (
            f"Final USER is root in {df.relative_to(REPO_ROOT)}: {users[-1]}"
        )
        assert re.search(r"^\s*HEALTHCHECK\s+", text, re.MULTILINE), (
            f"Missing HEALTHCHECK in {df.relative_to(REPO_ROOT)}"
        )


def test_requirements_files_use_exact_pins():
    req_files = sorted(
        p for p in REPO_ROOT.rglob("requirements*.txt")
        if "venv" not in p.parts and "node_modules" not in p.parts and "Community-Forensics" not in p.parts
    )
    assert len(req_files) >= 14
    unpinned = []
    for req in req_files:
        for idx, raw in enumerate(req.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            if "==" not in line:
                unpinned.append(f"{req.relative_to(REPO_ROOT)}:{idx}: {line}")
    assert not unpinned, f"Unpinned Python dependencies found:\n" + "\n".join(unpinned)


def test_compose_files_enforce_pinned_images_and_runtime_hardening():
    import yaml

    compose_path = REPO_ROOT / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = compose.get("services", {})
    assert services
    for name, svc in services.items():
        image = svc.get("image")
        if image:
            assert not image.endswith(":latest") and image not in {"alpine", "nginx:alpine"}, (
                f"Floating/unpinned image on service {name}: {image}"
            )
        assert svc.get("read_only") is True, f"Service {name} missing read_only: true"
        assert "ALL" in (svc.get("cap_drop") or []), f"Service {name} missing cap_drop: [ALL]"
        assert "no-new-privileges:true" in (svc.get("security_opt") or []), (
            f"Service {name} missing security_opt no-new-privileges:true"
        )
