"""
CI Policy Guard: Verifies that all 5 Week 12 required security status checks
remain configured, unconditional (no path filters), and backed by real suites.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci-security-gates.yml"

EXPECTED_JOBS = {
    "attack-harness": "Attack Harness Categories",
    "injection-suite": "Prompt & Payload Injection Suite",
    "validator-suite": "Gateway Validator Suite",
    "robustness-smoke": "Adversarial Robustness Smoke Tests",
    "mtls-connection-audit": "mTLS Connection Audit",
}

EXPECTED_ATTACK_SCENARIOS = {
    "clean",
    "splice_carried",
    "splice_forged",
    "replay_carried",
    "replay_forged",
    "reorder_carried",
    "reorder_forged",
    "prnu_splice",
    "auth_bypass",
}


def _load_workflow() -> dict:
    assert WORKFLOW_PATH.is_file(), f"Missing workflow: {WORKFLOW_PATH}"
    data = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # PyYAML 1.1 treats bare `on:` as boolean True if unquoted.
    if True in data and "on" not in data:
        data["on"] = data.pop(True)
    return data


def test_workflow_triggers_unconditionally_on_main_prs_and_pushes():
    wf = _load_workflow()
    assert wf.get("name") == "Required Security Gates"

    triggers = wf.get("on", {})
    for event in ("pull_request", "push"):
        assert event in triggers, f"Missing trigger '{event}' in {WORKFLOW_PATH.name}"
        event_cfg = triggers[event] or {}
        assert "main" in (event_cfg.get("branches") or []), (
            f"Trigger '{event}' must target branch 'main'"
        )
        assert "paths" not in event_cfg, (
            f"Required workflow '{event}' must NOT use `paths:` filter (causes skipped-check deadlock)"
        )
        assert "paths-ignore" not in event_cfg, (
            f"Required workflow '{event}' must NOT use `paths-ignore:` filter"
        )


def test_all_five_required_security_gate_jobs_defined():
    wf = _load_workflow()
    jobs = wf.get("jobs", {})
    assert set(EXPECTED_JOBS).issubset(jobs.keys()), (
        f"Missing required security gate jobs: {sorted(set(EXPECTED_JOBS) - set(jobs.keys()))}"
    )

    for job_id, display_name in EXPECTED_JOBS.items():
        job = jobs[job_id]
        assert job.get("name") == display_name, (
            f"Job '{job_id}' name changed from '{display_name}' to '{job.get('name')}'; "
            "changing job names breaks GitHub Branch Protection required check matching."
        )
        assert "if" not in job or "false" not in str(job["if"]).lower()


def test_referenced_scripts_and_suites_exist():
    required_paths = [
        "security/transport/generate_certs.py",
        "security/attacks/generate_attack_streams.py",
        "security/fusion/tests/test_fusion_harness.py",
        "security/tests/test_harness_integration.py",
        "security/tests/test_prnu.py",
        "security/tests/test_stream_dos_hardening.py",
        "security/tests/test_llm_prompt_defenses.py",
        "mcp/tests/test_mcp_security_hardening.py",
        "eval/tests/test_poisoning_and_alignment_study_b.py",
        "security/gateway/validator/tests/test_validator_api.py",
        "security/gateway/validator/tests/test_magic_bytes.py",
        "security/gateway/validator/tests/test_path_safety.py",
        "security/gateway/validator/tests/test_image_text_validation.py",
        "eval/tests/test_robustness_perturbations.py",
        "eval/tests/test_adaptive_robustness_v2.py",
        "security/transport/audit_mesh_connections.py",
        "security/tests/test_full_mtls_mesh.py",
    ]
    missing = [rel for rel in required_paths if not (REPO_ROOT / rel).is_file()]
    assert not missing, f"Referenced required CI targets missing: {missing}"


def test_attack_generator_covers_all_expected_categories():
    from security.attacks.generate_attack_streams import DESCRIPTIONS

    declared_scenarios = set()
    for tamper_type, mode in DESCRIPTIONS:
        if tamper_type == "none":
            declared_scenarios.add("clean")
        elif tamper_type in {"prnu_splice", "auth_bypass"}:
            declared_scenarios.add(tamper_type)
        else:
            declared_scenarios.add(f"{tamper_type}_{mode}")

    assert EXPECTED_ATTACK_SCENARIOS.issubset(declared_scenarios), (
        f"Missing attack scenarios in generate_attack_streams.DESCRIPTIONS: "
        f"{sorted(EXPECTED_ATTACK_SCENARIOS - declared_scenarios)}"
    )

    wf_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for scenario in EXPECTED_ATTACK_SCENARIOS:
        assert scenario in wf_text, (
            f"CI fixture check must explicitly assert scenario '{scenario}'"
        )


def test_workflow_inline_pip_installs_are_pinned():
    wf_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Every quoted package spec installed inline in the workflow must pin an exact version (`==`).
    quoted_pkgs = re.findall(r'"([a-zA-Z0-9_.\-\[\]]+)"', wf_text)
    unpinned = [
        spec
        for spec in quoted_pkgs
        if any(sep in spec for sep in (">=", "<=", "~=", "!="))
    ]
    assert not unpinned, f"Non-exact version range found in workflow: {unpinned}"
