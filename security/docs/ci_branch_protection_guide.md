# Branch Protection & Required Security Gates Setup (Week 12 Task 2)

This guide covers the **five mandatory security status checks** implemented in [`.github/workflows/ci-security-gates.yml`](../../.github/workflows/ci-security-gates.yml) and documents how to enforce them on `main` and capture the blocking-PR demonstration required for Week 12 Cybersecurity Task 2.

---

## 1. Required Security Status Checks

Workflow file: `.github/workflows/ci-security-gates.yml` (`name: Required Security Gates`)

All five jobs execute unconditionally on every `pull_request` and `push` targeting `main` (zero `paths:` / `paths-ignore:` filters, preventing the GitHub skipped-check PR deadlock).

| # | Category (Task 2 Spec) | Job ID | GitHub Check Name (`job.name`) | Suites & Checks Executed |
|---|---|---|---|---|
| 1 | Attack-harness categories | `attack-harness` | `Attack Harness Categories` | Generates mTLS certs (`security/transport/generate_certs.py`) and all 9 attack-harness scenarios (`clean`, `splice_carried`, `splice_forged`, `replay_carried`, `replay_forged`, `reorder_carried`, `reorder_forged`, `prnu_splice`, `auth_bypass`) via `security/attacks/generate_attack_streams.py`, then runs `security/fusion/tests/`, `test_harness_integration.py`, `test_prnu.py`, `test_hash_chain.py`, `test_stream_dos_hardening.py`, `test_cyber_fortress.py`, `test_dual_mode_gateway.py`, `test_device_lifecycle.py`, and `test_live_ingestion.py`. |
| 2 | Injection suite | `injection-suite` | `Prompt & Payload Injection Suite` | Runs `security/tests/test_llm_prompt_defenses.py`, `mcp/tests/test_mcp_security_hardening.py`, `eval/tests/test_poisoning_and_alignment_study_b.py`, and `security/tests/test_required_security_ci_gates.py`. |
| 3 | Validator tests | `validator-suite` | `Gateway Validator Suite` | Runs `security/gateway/validator/tests/` (`test_validator_api.py`, `test_magic_bytes.py`, `test_path_safety.py`, `test_image_text_validation.py`) unconditionally. |
| 4 | Robustness smoke tests | `robustness-smoke` | `Adversarial Robustness Smoke Tests` | Runs `eval/tests/test_robustness_perturbations.py` and `eval/tests/test_adaptive_robustness_v2.py` with CPU PyTorch against tracked weights. |
| 5 | mTLS connection audit | `mtls-connection-audit` | `mTLS Connection Audit` | Runs `python security/transport/audit_mesh_connections.py --self-test` (exporting Markdown & JSON reports as workflow artifacts) plus `test_full_mtls_mesh.py`, `test_detector_mtls.py`, `test_inter_service_mtls.py`, and `test_mtls.py`. |

> **Important:** Do **not** add `test-validator` from `.github/workflows/ci-gateway.yml` (`Gateway Validator CI`) to branch protection as a required check — that legacy workflow has a `paths: ['security/gateway/**']` filter and remains `Skipped` on non-gateway PRs. Always require `Gateway Validator Suite` from `.github/workflows/ci-security-gates.yml`.

Optional defense-in-depth checks you may also mark as required (unconditional in their respective workflows):
- `Surveillance, Stream Integrity & Security Suites` (`.github/workflows/ci-tests.yml`)
- `Gitleaks Secret Scan`, `Python & npm Dependency Audit`, `Trivy Misconfig, Container Scan & CycloneDX SBOM`, `Checkpoint Safety & Container Policy Tests` (`.github/workflows/ci-security-supply-chain.yml`)

---

## 2. Configuring Branch Protection on `main`

Because `main` currently needs to receive the PR containing `.github/workflows/ci-security-gates.yml` first, follow this order:

1. **Push & open a PR for this branch (`feat/week12-task2-required-security-checks` → `main`):**
   - Wait for all five jobs in `Required Security Gates` to finish and report green status checks on the PR. (GitHub only lists status checks in the Branch Protection search box after they have reported at least once recently.)
   - Merge this PR into `main`.

2. **Open Repository Settings → Branches (or Rules → Rulesets):**
   - Go to **GitHub Repository → Settings → Branches → Add branch protection rule** (or edit the existing rule for `main`).
   - **Branch name pattern:** `main`
   - Enable:
     - ✅ **Require a pull request before merging** (with at least `1` approval if enforcing two-person review, or as appropriate for your team).
     - ✅ **Require status checks to pass before merging**
       - ✅ **Require branches to be up to date before merging**
       - Under **Status checks that are required**, search and add all 5 check names:
         1. `Attack Harness Categories`
         2. `Prompt & Payload Injection Suite`
         3. `Gateway Validator Suite`
         4. `Adversarial Robustness Smoke Tests`
         5. `mTLS Connection Audit`
     - ✅ **Do not allow bypassing the above settings** (critical so administrators/owners cannot accidentally bypass failing security gates).
   - Click **Create** / **Save changes**.

---

## 3. Reproducible Demonstration: Failing Security Test Blocks a PR

After `main` branch protection is active, execute the following steps to capture verifiable proof (and screenshots for the thesis / weekly report) of a failing security check blocking a merge:

1. Create a temporary verification branch from updated `main`:
   ```bash
   git checkout main && git pull origin main
   git checkout -b test/demo-blocked-security-pr
   ```
2. Introduce an intentional, isolated security failure (for example, revert a validation guard in a test or add a temporary failing assertion inside a security test file):
   ```python
   # Temporary one-line addition at the bottom of security/gateway/validator/tests/test_magic_bytes.py
   def test_demo_security_gate_blocks_regression():
       assert False, "Intentional security regression demo for Week 12 Task 2"
   ```
3. Commit and push the branch, then open a Pull Request targeting `main`:
   ```bash
   git add security/gateway/validator/tests/test_magic_bytes.py
   git commit -m "test(security): demonstrate required CI gate blocking unsafe PR"
   git push -u origin test/demo-blocked-security-pr
   ```
4. Observe GitHub PR status checks:
   - `Gateway Validator Suite` fails with exit code `1`.
   - Even if all other 4 security checks pass, GitHub displays **`Merging is blocked`** / **`Required statuses must pass before merging`** (`Gateway Validator Suite` required check failed), disabling the **Merge pull request** button even for admins.
5. Capture screenshots of:
   - The failed `Required Security Gates / Gateway Validator Suite` check run log,
   - The blocked PR merge box showing required status check enforcement, and
   - The `Settings → Branches` rule listing all 5 active required status checks.
6. Clean up the demonstration PR and throwaway branch:
   - Close the PR on GitHub (do not merge), and delete the remote + local branch:
     ```bash
     git checkout main
     git branch -D test/demo-blocked-security-pr
     git push origin --delete test/demo-blocked-security-pr
     ```
