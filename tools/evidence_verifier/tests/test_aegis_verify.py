"""
Tests for tools/evidence_verifier/aegis_verify.py and sample demo bundles.
Verifies zero-dependency isolation, genuine bundle verification across all
modalities + live alerts, tamper detection across 5 attack vectors, CLI output
modes (--verbose, --inspect, --json, batch directory), and legacy bundles.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_VERIFIER_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _VERIFIER_DIR.parent.parent
_CLI_PATH = _VERIFIER_DIR / "aegis_verify.py"
_SAMPLE_DIR = _VERIFIER_DIR / "sample_bundles"

if str(_VERIFIER_DIR) not in sys.path:
    sys.path.insert(0, str(_VERIFIER_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import aegis_verify  # noqa: E402
from security.forensics.evidence_vault import UnifiedEvidenceVault  # noqa: E402

GENUINE_BUNDLES = [
    "genuine_video_bundle.zip",
    "genuine_audio_bundle.zip",
    "genuine_image_bundle.zip",
    "genuine_text_bundle.zip",
    "genuine_multimodal_bundle.zip",
    "genuine_live_alert_bundle.zip",
]

TAMPERED_EXPECTED_FAIL_STEP = {
    "tampered_verdict_flip.zip": "manifest_hashes",
    "tampered_payload_swap.zip": "manifest_hashes",
    "tampered_report_markdown.zip": "manifest_hashes",
    "tampered_forged_signature.zip": "bundle_signature",
    "tampered_missing_signature.zip": "artifact_presence",
}


def test_verifier_has_zero_top_level_repo_or_third_party_imports():
    """AST guarantee that aegis_verify.py runs with Python stdlib only."""
    tree = ast.parse(_CLI_PATH.read_text(encoding="utf-8"))
    top_level_modules = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_modules.add(node.module.split(".")[0])

    assert top_level_modules <= set(sys.stdlib_module_names), (
        f"Non-stdlib top-level imports found in aegis_verify.py: "
        f"{top_level_modules - set(sys.stdlib_module_names)}"
    )


@pytest.mark.parametrize("bundle_name", GENUINE_BUNDLES)
def test_genuine_sample_bundles_pass_offline_cli(bundle_name: str):
    bundle_path = _SAMPLE_DIR / bundle_name
    assert bundle_path.exists(), f"Missing sample bundle {bundle_path}"

    res = aegis_verify.verify_bundle(bundle_path)
    assert res.is_valid is True, f"{bundle_name} unexpectedly failed: {res.error_reason}"
    assert len(res.checks) == 6
    assert all(c.passed for c in res.checks)

    proc = subprocess.run(
        [sys.executable, str(_CLI_PATH), str(bundle_path), "--verbose", "--inspect"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "[PASS]" in proc.stdout
    assert "Model Versions:" in proc.stdout


@pytest.mark.parametrize("bundle_name,expected_step", list(TAMPERED_EXPECTED_FAIL_STEP.items()))
def test_tampered_sample_bundles_rejected_with_pinpointed_step(bundle_name: str, expected_step: str):
    bundle_path = _SAMPLE_DIR / bundle_name
    assert bundle_path.exists(), f"Missing tampered bundle {bundle_path}"

    res = aegis_verify.verify_bundle(bundle_path)
    assert res.is_valid is False
    failed_steps = [c.name for c in res.checks if not c.passed]
    assert expected_step in failed_steps

    proc = subprocess.run(
        [sys.executable, str(_CLI_PATH), str(bundle_path), "--verbose"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "[FAIL]" in proc.stdout


def test_extracted_directory_and_wrong_key_handling(tmp_path: Path):
    src_zip = _SAMPLE_DIR / "genuine_video_bundle.zip"
    extract_dir = tmp_path / "unzipped"
    with zipfile.ZipFile(src_zip, "r") as zf:
        zf.extractall(extract_dir)

    ok_dir = aegis_verify.verify_bundle(extract_dir)
    assert ok_dir.is_valid is True
    assert ok_dir.summary.modality == "video"

    bad_key = aegis_verify.verify_bundle(extract_dir, signing_key=b"wrong_auditor_secret")
    assert bad_key.is_valid is False
    assert bad_key.checks[-1].name == "bundle_signature"


def test_batch_and_json_cli_output(tmp_path: Path):
    # Batch directory with genuine + tampered must exit 1 and report counts cleanly in --json
    proc = subprocess.run(
        [sys.executable, str(_CLI_PATH), str(_SAMPLE_DIR), "--json"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    assert report["total"] == len(GENUINE_BUNDLES) + len(TAMPERED_EXPECTED_FAIL_STEP)
    assert report["passed"] == len(GENUINE_BUNDLES)
    assert report["failed"] == len(TAMPERED_EXPECTED_FAIL_STEP)
    assert report["all_valid"] is False

    # Passing genuine-only directory exits 0
    clean_dir = tmp_path / "clean_only"
    clean_dir.mkdir()
    for g in GENUINE_BUNDLES[:2]:
        (clean_dir / g).write_bytes((_SAMPLE_DIR / g).read_bytes())

    proc_ok = subprocess.run(
        [sys.executable, str(_CLI_PATH), str(clean_dir), "--json"],
        capture_output=True,
        text=True,
    )
    assert proc_ok.returncode == 0
    ok_report = json.loads(proc_ok.stdout)
    assert ok_report["all_valid"] is True
    assert ok_report["passed"] == 2


def test_legacy_incident_package_compatibility(tmp_path: Path):
    vault = UnifiedEvidenceVault(vault_dir=tmp_path / "vault")
    inc = vault.store_incident(
        camera_id="cam-legacy-01",
        threat_type="DEEPFAKE_ALERT",
        severity="HIGH",
        sequence_number=10,
        timestamp_ms=1795550000999,
        primary_frame_bytes=b"\x89PNG_LEGACY_TEST_FRAME",
        reasoning_narrative="Legacy bundle compatibility check",
    )
    legacy_zip = vault.export_incident_package(inc.incident_id, output_zip_path=tmp_path / "legacy.zip")

    res = aegis_verify.verify_bundle(legacy_zip)
    assert res.is_valid is True
    assert res.summary.bundle_format == "legacy_incident_package"
