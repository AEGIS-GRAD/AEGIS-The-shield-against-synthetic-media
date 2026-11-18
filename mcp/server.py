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

# Ensure repo root and mcp dir are on sys.path
for p in [str(_REPO_ROOT), str(_THIS_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ── MCP SDK imports ──────────────────────────────────────────────────────────
from mcp.server.fastmcp import FastMCP

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

# ── Hardening (Week 11 Cyber Task 1): auth, scopes, rate limits, validation, audit ──
from hardening import (  # noqa: E402
    SCOPE_ARBITRATE,
    SCOPE_CAPABILITIES,
    UNTRUSTED_NOTICE,
    HardeningError,
    build_sse_app,
    guarded_tool,
    validate_claims_payload,
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
@guarded_tool("arbitrate_evidence", SCOPE_ARBITRATE)
def arbitrate_evidence(
    claims: Union[List[Dict[str, Any]], str],
    operating_conditions: Optional[Union[Dict[str, Any], str]] = None,
) -> Dict[str, Any]:
    """Arbitrate conflicting detector claims using the AEGIS Forensic Debate Protocol.

    Accepts a list of detector claims (each matching the ForensicClaim schema)
    along with optional operating conditions, routes them through the full 3-round
    structured debate (Claim Submission -> Cross-Examination -> Adjudication), and
    returns a structured court-admissible verdict with forensic justification.

    Args:
        claims: List of detector claim dicts (or a JSON-encoded string thereof).
            Each claim dict must include:
            - detector_id (str): e.g. "video-classifier", "rppg", "syncnet", "aasist",
              "detector_image", "detector_text"
            - job_id (str): Job identifier
            - model_version (str): Model version string
            - domain (str): Evidence domain (e.g. "spatial_pixel", "physiological_bvp")
            - polarity (str): "AUTHENTIC", "SYNTHETIC", "INCONCLUSIVE", or "NOT_APPLICABLE"
            - confidence (float): P(synthetic) in [0.0, 1.0]
            - claim (str): Human-readable forensic claim text
        operating_conditions: Optional dict (or JSON string) with environmental context:
            - duration_seconds (float): Media duration
            - mean_luminance (float): Average brightness [0-255]
            - face_detected (bool): Whether a face was found
            - audio_present (bool): Whether audio track exists
            - video_bitrate_kbps (float): Video bitrate

    Returns:
        Dict containing:
            - status: "ok" or "error"
            - verdict: The full CourtAdmissibleVerdict object
            - report: The complete JudgeReport with 3-round debate transcript
            - final_verdict: Verdict string ("AUTHENTIC", "SYNTHETIC", "INTEGRITY_UNKNOWN", "UNCERTAIN")
            - calibrated_score: Ensemble calibrated synthetic probability
            - forensic_justification: Forensic reasoning narrative
            - arbitration_mode: "consensus_fast_path" or "expert_deterministic_judge"
            - error: Error message if status is "error"
    """
    try:
        # Handle JSON string inputs (e.g. from some MCP clients)
        parsed_claims = claims
        if isinstance(claims, str):
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

        # Structural limits, detector allowlist, one claim per detector, finite numbers,
        # prompt-injection redaction and URL neutralisation (raises HardeningError).
        cond_for_check = operating_conditions
        if isinstance(cond_for_check, str):
            try:
                cond_for_check = json.loads(cond_for_check)
            except Exception:
                cond_for_check = None  # reported below by the original parser
        parsed_claims, _, security_notes = validate_claims_payload(
            parsed_claims, cond_for_check if isinstance(cond_for_check, dict) else None
        )

        # Handle empty claims gracefully (Edge Case 1)
        if len(parsed_claims) == 0:
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
        for i, raw_claim in enumerate(parsed_claims):
            if isinstance(raw_claim, ForensicClaim):
                forensic_claims.append(raw_claim)
                continue
            if not isinstance(raw_claim, dict):
                return {
                    "status": "error",
                    "error": f"Claim at index {i} is not a dict: {type(raw_claim).__name__}",
                    "verdict": None,
                    "report": None,
                }
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
            "security_notes": security_notes,
            "untrusted_content_notice": UNTRUSTED_NOTICE,
        }

    except HardeningError:
        raise  # handled (and audited) by guarded_tool
    except Exception as exc:
        logger.error("arbitrate_evidence failed: %s\n%s", exc, traceback.format_exc())
        return {
            "status": "error",
            "error": f"Internal arbitration error: {exc}",
            "verdict": None,
            "report": None,
        }


# ── Tool 2: capabilities ─────────────────────────────────────────────────────
@mcp_server.tool()
@guarded_tool("capabilities", SCOPE_CAPABILITIES)
def capabilities() -> Dict[str, Any]:
    """Return detector capability manifests and reliability metrics.

    Reads the capability_manifests/*.json files and returns each detector's
    manifest (input constraints, known failure modes, authority tier,
    calibration config, condition-specific reliability rules) along with
    the runtime default weights and authority tiers used by the arbitration engine.

    Returns:
        Dict containing:
            - status: "ok" or "error"
            - detectors: Dict mapping detector_id -> manifest data with runtime metrics
            - default_weights: Default detector weight assignments
            - authority_tiers: Default authority tier assignments
            - total_detectors: Total count of active detectors in registry
    """
    try:
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

    except Exception as exc:
        logger.error("capabilities failed: %s\n%s", exc, traceback.format_exc())
        return {
            "status": "error",
            "error": f"Failed to load capabilities: {exc}",
            "detectors": {},
            "default_weights": {},
            "authority_tiers": {},
            "total_detectors": 0,
        }


# ── Attach to sys.modules["mcp.server"] for flexible import compatibility ────
try:
    import mcp.server as _sdk_mcp_server
    _sdk_mcp_server.arbitrate_evidence = arbitrate_evidence  # type: ignore[attr-defined]
    _sdk_mcp_server.capabilities = capabilities              # type: ignore[attr-defined]
    _sdk_mcp_server.mcp_server = mcp_server                  # type: ignore[attr-defined]
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
    parser.add_argument("--ssl-certfile", default=None, help="TLS certificate for the SSE transport")
    parser.add_argument("--ssl-keyfile", default=None, help="TLS private key for the SSE transport")
    args = parser.parse_args()

    logger.info("Starting AEGIS MCP server (transport=%s)", args.transport)

    if args.transport == "sse":
        import uvicorn

        app = build_sse_app(mcp_server)  # refuses to start without bearer tokens
        if args.host not in ("127.0.0.1", "localhost", "::1") and not args.ssl_certfile:
            logger.warning("SSE bound to %s without TLS: bearer tokens will cross the network in clear text.", args.host)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning",
                    ssl_certfile=args.ssl_certfile, ssl_keyfile=args.ssl_keyfile)
    else:
        mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()
