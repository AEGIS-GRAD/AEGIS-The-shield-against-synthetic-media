"""
AEGIS MCP Server — Model Context Protocol interface for the Debate & Arbitration Layer.
========================================================================================

Exposes two tools via the MCP ``FastMCP`` server:

* ``arbitrate_evidence(claims, operating_conditions)``
  Accepts conflicting detector claims, routes them through the debate/judge
  arbitration logic, and returns a structured ``CourtAdmissibleVerdict``.

* ``capabilities()``
  Returns each detector's capability manifest and current reliability metrics.

Run modes
---------
* **stdio** (default): ``python mcp/server.py``
* **SSE**:             ``python mcp/server.py --transport sse --port 8000``
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# ── Path plumbing ────────────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent          # <repo>/mcp
_REPO_ROOT = _THIS_DIR.parent                        # <repo>

# Temporarily exclude repo root & CWD entries so `<repo>/mcp/` does not shadow the
# installed `mcp` SDK package during import, then append `_REPO_ROOT` at the end.
for p in ["", ".", str(_THIS_DIR), str(_REPO_ROOT)]:
    while p in sys.path:
        sys.path.remove(p)

try:
    from mcp.server.fastmcp import FastMCP
    _HAS_MCP_SDK = True
except ModuleNotFoundError:
    _HAS_MCP_SDK = False

    class FastMCP:  # type: ignore[no-redef]
        """Minimal fallback when optional `mcp` SDK package is unavailable."""

        def __init__(self, name: str, instructions: str = "") -> None:
            self.name = name
            self.instructions = instructions
            self.settings = argparse.Namespace(host="127.0.0.1", port=8000)
            self._tools: Dict[str, Any] = {}

        def tool(self):
            def _decorator(fn):
                self._tools[fn.__name__] = fn
                return fn

            return _decorator

        def run(self, transport: str = "stdio") -> None:
            raise RuntimeError(
                f"Cannot run MCP transport '{transport}': 'mcp' SDK is not installed. "
                "Install with: pip install -r mcp/requirements.txt"
            )

sys.path.insert(0, str(_THIS_DIR))
sys.path.append(str(_REPO_ROOT))
from mcp_security import (
    MCPInputValidator,
    MCPSecurityError,
    get_security_gateway,
)

# ── Debate layer imports ─────────────────────────────────────────────────────
from debate.judge_agent import JudgeAgent
from debate.manifest_reliability import (
    DEFAULT_AUTHORITY_TIERS,
    DEFAULT_BASE_WEIGHTS,
    ManifestReliabilityEngine,
)
from debate.schemas import (
    CourtAdmissibleVerdict,
    ForensicClaim,
    JudgeReport,
    OperatingConditions,
)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("aegis.mcp.server")

# ── Module-level singletons ─────────────────────────────────────────────────
MANIFESTS_DIR = _REPO_ROOT / "capability_manifests"

_judge: Optional[JudgeAgent] = None
_reliability_engine: Optional[ManifestReliabilityEngine] = None


def _get_judge() -> JudgeAgent:
    global _judge
    if _judge is None:
        judge_mode = os.environ.get("AEGIS_JUDGE_MODE", "deterministic")
        _judge = JudgeAgent(mode=judge_mode, manifests_dir=MANIFESTS_DIR)
        logger.info("JudgeAgent singleton initialised (mode=%s)", judge_mode)
    return _judge


def _get_reliability_engine() -> ManifestReliabilityEngine:
    global _reliability_engine
    if _reliability_engine is None:
        _reliability_engine = ManifestReliabilityEngine(
            manifests=ManifestReliabilityEngine.load_default_manifests(MANIFESTS_DIR)
        )
        logger.info("ManifestReliabilityEngine singleton initialised")
    return _reliability_engine


# ── FastMCP Server ───────────────────────────────────────────────────────────
mcp_server = FastMCP(
    name="aegis-debate",
    instructions=(
        "AEGIS Debate & Arbitration MCP Server — exposes multimodal deepfake "
        "forensic arbitration and detector capability manifests as MCP tools."
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _verdict_to_dict(verdict: CourtAdmissibleVerdict) -> Dict[str, Any]:
    """Serialize a CourtAdmissibleVerdict to a JSON-safe dict."""
    d = verdict.model_dump(mode="json")
    if hasattr(verdict.final_verdict, "value"):
        d["final_verdict"] = verdict.final_verdict.value
    return d


def _report_to_dict(report: JudgeReport) -> Dict[str, Any]:
    """Serialize a JudgeReport to a JSON-safe dict."""
    return report.model_dump(mode="json")


# ── Tool 1: arbitrate_evidence ───────────────────────────────────────────────
@mcp_server.tool()
def arbitrate_evidence(
    claims: Union[List[Dict[str, Any]], str],
    operating_conditions: Optional[Union[Dict[str, Any], str]] = None,
    auth_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Arbitrate conflicting detector claims using the AEGIS Forensic Debate Protocol.

    Accepts a list of detector claims (each matching the ForensicClaim schema)
    along with optional operating conditions, routes them through the full 3-round
    structured debate (Claim Submission -> Cross-Examination -> Adjudication), and
    returns a structured court-admissible verdict with forensic justification.
    """
    gateway = get_security_gateway()
    raw_args = {
        "claims": claims,
        "operating_conditions": operating_conditions,
        "auth_token": auth_token,
    }

    def _run(_principal, sec_flags: List[str]) -> Dict[str, Any]:
        # Handle JSON string inputs (e.g. from some MCP clients)
        parsed_claims = claims
        if isinstance(claims, str):
            MCPInputValidator.check_no_ssrf(claims, "claims")
            try:
                parsed_claims = json.loads(claims)
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to parse 'claims' JSON string: {e}",
                    "verdict": None,
                    "report": None,
                }

        if not isinstance(parsed_claims, list):
            return {
                "status": "error",
                "error": f"Parameter 'claims' must be a list of claim dicts, got {type(parsed_claims).__name__}.",
                "verdict": None,
                "report": None,
            }

        sanitized_claims, claim_flags = MCPInputValidator.sanitize_and_validate_claims(parsed_claims)
        sec_flags.extend(claim_flags)

        # Handle empty claims gracefully (Edge Case 1)
        if len(sanitized_claims) == 0:
            judge = _get_judge()
            report = judge.judge_claims([], conditions=None)
            verdict_dict = _verdict_to_dict(report.verdict)
            return {
                "status": "ok",
                "verdict": verdict_dict,
                "report": _report_to_dict(report),
                "final_verdict": verdict_dict["final_verdict"],
                "calibrated_score": verdict_dict["calibrated_score"],
                "forensic_justification": verdict_dict["forensic_justification"],
                "arbitration_mode": verdict_dict["arbitration_mode"],
            }

        # Build ForensicClaim objects (validating schemas)
        forensic_claims: List[ForensicClaim] = []
        for i, raw_claim in enumerate(sanitized_claims):
            if isinstance(raw_claim, ForensicClaim):
                MCPInputValidator.validate_job_id(raw_claim.job_id, f"claims[{i}].job_id")
                forensic_claims.append(raw_claim)
                continue
            if not isinstance(raw_claim, dict):
                return {
                    "status": "error",
                    "error": f"Claim at index {i} is not a dict: {type(raw_claim).__name__}",
                    "verdict": None,
                    "report": None,
                }
            if isinstance(raw_claim.get("job_id"), str) and raw_claim.get("job_id"):
                MCPInputValidator.validate_job_id(raw_claim["job_id"], f"claims[{i}].job_id")
            try:
                fc = ForensicClaim(**raw_claim)
                forensic_claims.append(fc)
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Invalid claim at index {i}: {e}",
                    "verdict": None,
                    "report": None,
                }

        # Build OperatingConditions
        conditions: Optional[OperatingConditions] = None
        parsed_cond = operating_conditions
        if isinstance(operating_conditions, str):
            MCPInputValidator.check_no_ssrf(operating_conditions, "operating_conditions")
            try:
                parsed_cond = json.loads(operating_conditions)
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to parse 'operating_conditions' JSON string: {e}",
                    "verdict": None,
                    "report": None,
                }

        if parsed_cond is not None:
            if isinstance(parsed_cond, OperatingConditions):
                conditions = parsed_cond
            elif isinstance(parsed_cond, dict):
                try:
                    conditions = OperatingConditions(**parsed_cond)
                except Exception as e:
                    return {
                        "status": "error",
                        "error": f"Invalid operating_conditions: {e}",
                        "verdict": None,
                        "report": None,
                    }
            else:
                return {
                    "status": "error",
                    "error": f"operating_conditions must be a dict, got {type(parsed_cond).__name__}",
                    "verdict": None,
                    "report": None,
                }

        # Run the Judge Agent (Deterministic fallback if LLM key is absent)
        judge = _get_judge()
        job_id = forensic_claims[0].job_id if forensic_claims else "mcp-arbitration-job"
        report: JudgeReport = judge.judge_claims(
            claims=forensic_claims,
            conditions=conditions,
            job_id=job_id,
        )

        verdict_dict = _verdict_to_dict(report.verdict)
        return {
            "status": "ok",
            "verdict": verdict_dict,
            "report": _report_to_dict(report),
            "final_verdict": verdict_dict["final_verdict"],
            "calibrated_score": verdict_dict["calibrated_score"],
            "forensic_justification": verdict_dict["forensic_justification"],
            "arbitration_mode": verdict_dict["arbitration_mode"],
        }

    return gateway.execute_guarded("arbitrate_evidence", raw_args, auth_token, _run)


# ── Tool 2: capabilities ─────────────────────────────────────────────────────
@mcp_server.tool()
def capabilities(auth_token: Optional[str] = None) -> Dict[str, Any]:
    """Return detector capability manifests and reliability metrics."""
    gateway = get_security_gateway()

    def _run(_principal, _sec_flags: List[str]) -> Dict[str, Any]:
        engine = _get_reliability_engine()
        manifests = dict(engine.manifests)

        detectors_out = {}
        for det_id, manifest in manifests.items():
            detectors_out[det_id] = {
                "manifest": manifest,
                "default_weight": DEFAULT_BASE_WEIGHTS.get(det_id, 1.0),
                "authority_tier": DEFAULT_AUTHORITY_TIERS.get(det_id, "primary"),
            }

        return {
            "status": "ok",
            "detectors": detectors_out,
            "default_weights": DEFAULT_BASE_WEIGHTS,
            "authority_tiers": DEFAULT_AUTHORITY_TIERS,
            "total_detectors": len(detectors_out),
        }

    return gateway.execute_guarded("capabilities", {"auth_token": auth_token}, auth_token, _run)


# ── Tool 3: verify_media ─────────────────────────────────────────────────────
@mcp_server.tool()
def verify_media(
    file_path: str,
    modality: Optional[str] = None,
    planner_mode: str = "rule_based",
    risk_profile: str = "standard",
    compute_budget_s: Optional[float] = None,
    job_id: Optional[str] = None,
    auth_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit a multimodal media file to the AEGIS verification pipeline."""
    gateway = get_security_gateway()
    raw_args = {
        "file_path": file_path,
        "modality": modality,
        "planner_mode": planner_mode,
        "risk_profile": risk_profile,
        "compute_budget_s": compute_budget_s,
        "job_id": job_id,
        "auth_token": auth_token,
    }

    def _run(principal, _sec_flags: List[str]) -> Dict[str, Any]:
        clean_path = MCPInputValidator.validate_file_path(file_path, field_name="file_path")
        clean_job_id = (
            MCPInputValidator.validate_job_id(job_id, field_name="job_id")
            if job_id is not None
            else None
        )
        if modality is not None and modality not in {"video", "image", "audio", "text", "multimodal"}:
            raise MCPSecurityError("INVALID_MODALITY", f"Unsupported modality: '{modality}'.")
        if planner_mode not in {"rule_based", "rule", "rules", "baseline", "llm"}:
            raise MCPSecurityError("INVALID_PLANNER_MODE", f"Unsupported planner_mode: '{planner_mode}'.")
        if risk_profile not in {"low", "standard", "high"}:
            raise MCPSecurityError("INVALID_RISK_PROFILE", f"Unsupported risk_profile: '{risk_profile}'.")

        from job_store import get_job_store
        store = get_job_store()
        return store.submit_job(
            file_path=clean_path,
            modality=modality,
            planner_mode=planner_mode,
            risk_profile=risk_profile,
            compute_budget_s=compute_budget_s,
            job_id=clean_job_id,
            owner_principal=principal.principal_id,
        )

    return gateway.execute_guarded("verify_media", raw_args, auth_token, _run)


# ── Tool 4: get_report ───────────────────────────────────────────────────────
@mcp_server.tool()
def get_report(
    job_id: str,
    auth_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Poll for the forensic report of a media verification job."""
    gateway = get_security_gateway()
    raw_args = {"job_id": job_id, "auth_token": auth_token}

    def _run(principal, sec_flags: List[str]) -> Dict[str, Any]:
        clean_job_id = MCPInputValidator.validate_job_id(job_id, field_name="job_id")
        from job_store import get_job_store
        store = get_job_store()
        res = store.get_report(
            job_id=clean_job_id,
            caller_principal=principal.principal_id,
            is_admin=principal.is_admin,
        )
        if res.get("error_code") == "CONFUSED_DEPUTY_TENANT_MISMATCH":
            sec_flags.extend(res.get("security_flags", ["confused_deputy_blocked"]))
        return res

    return gateway.execute_guarded("get_report", raw_args, auth_token, _run)


# ── Tool 5: check_stream_integrity ───────────────────────────────────────────
@mcp_server.tool()
def check_stream_integrity(
    job_id: Optional[str] = None,
    video_path: Optional[str] = None,
    manifest_path: Optional[str] = None,
    auth_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify cryptographic hash-chain integrity for live streams or archived jobs."""
    gateway = get_security_gateway()
    raw_args = {
        "job_id": job_id,
        "video_path": video_path,
        "manifest_path": manifest_path,
        "auth_token": auth_token,
    }

    def _run(_principal, _sec_flags: List[str]) -> Dict[str, Any]:
        clean_job_id = (
            MCPInputValidator.validate_job_id(job_id, field_name="job_id")
            if job_id is not None
            else None
        )
        clean_video = (
            MCPInputValidator.validate_file_path(video_path, field_name="video_path")
            if video_path is not None
            else None
        )
        clean_manifest = (
            MCPInputValidator.validate_file_path(manifest_path, field_name="manifest_path")
            if manifest_path is not None
            else None
        )
        from job_store import get_job_store
        store = get_job_store()
        return store.check_stream_integrity(
            job_id=clean_job_id,
            video_path=clean_video,
            manifest_path=clean_manifest,
        )

    return gateway.execute_guarded("check_stream_integrity", raw_args, auth_token, _run)


# ── Attach to sys.modules["mcp.server"] for flexible import compatibility ────
try:
    import mcp.server as _sdk_mcp_server
    _sdk_mcp_server.arbitrate_evidence = arbitrate_evidence          # type: ignore[attr-defined]
    _sdk_mcp_server.capabilities = capabilities                      # type: ignore[attr-defined]
    _sdk_mcp_server.verify_media = verify_media                      # type: ignore[attr-defined]
    _sdk_mcp_server.get_report = get_report                          # type: ignore[attr-defined]
    _sdk_mcp_server.check_stream_integrity = check_stream_integrity  # type: ignore[attr-defined]
    _sdk_mcp_server.mcp_server = mcp_server                          # type: ignore[attr-defined]
except Exception:
    pass


# ── CLI entry point ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AEGIS Debate & Arbitration MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport mode (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE transport (default: 8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    args = parser.parse_args()

    logger.info("Starting AEGIS MCP server (transport=%s)", args.transport)

    if args.transport == "sse":
        mcp_server.settings.port = args.port
        mcp_server.settings.host = args.host
        mcp_server.run(transport="sse")
    else:
        mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()
