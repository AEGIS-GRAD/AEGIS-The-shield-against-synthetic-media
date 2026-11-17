"""
AEGIS MCP Example Client.
=========================
Independent client script demonstrating standard MCP integration with the
AEGIS Debate and Arbitration Server.

This script does NOT depend on the AEGIS orchestrator. It uses the standard
Python MCP SDK (`mcp.client.session.ClientSession`) to:
1. Connect to the AEGIS MCP server over stdio (or SSE transport).
2. Discover available tools.
3. Query `capabilities()` to inspect registered detectors and reliability metrics.
4. Submit conflicting forensic claims to `arbitrate_evidence()`.
5. Display the structured court-admissible verdict and justification narrative.

Usage:
    # Standard stdio mode (launches server subprocess automatically):
    python mcp/example_client.py

    # Connect to an existing SSE server:
    python mcp/example_client.py --transport sse --url http://127.0.0.1:8000/sse
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from mcp import StdioServerParameters, stdio_client
from mcp.client.session import ClientSession


def get_sample_conflicting_claims() -> List[Dict[str, Any]]:
    """Generate realistic conflicting claims simulating a donor-body face-swap attack."""
    return [
        {
            "job_id": "job-external-agent-001",
            "detector_id": "video-classifier",
            "model_version": "xception-ff++-v1",
            "domain": "spatial_pixel",
            "polarity": "SYNTHETIC",
            "confidence": 0.94,
            "raw_score": 0.94,
            "claim": (
                "Frame-level analysis found strong spatial evidence of face manipulation "
                "(estimated 94% probability of synthetic content across sampled frames)."
            ),
            "flags": ["high_fake_probability", "boundary_artifact"],
        },
        {
            "job_id": "job-external-agent-001",
            "detector_id": "rppg",
            "model_version": "rppg-toolbox-physnet-v1",
            "domain": "physiological_bvp",
            "polarity": "AUTHENTIC",
            "confidence": 0.18,
            "raw_score": 0.18,
            "claim": (
                "A stable periodic pulse consistent with a live face was detected "
                "(signal quality 82%, estimated 72 BPM)."
            ),
            "flags": ["stable_pulse_detected"],
        },
        {
            "job_id": "job-external-agent-001",
            "detector_id": "syncnet",
            "model_version": "syncnet-v1",
            "domain": "audiovisual_sync",
            "polarity": "AUTHENTIC",
            "confidence": 0.25,
            "raw_score": 0.0,
            "claim": "Lip movements are tightly synchronized with the audio track.",
            "flags": ["lip_sync_verified"],
        },
    ]


def get_sample_operating_conditions() -> Dict[str, Any]:
    """Environmental context for the media file being evaluated."""
    return {
        "duration_seconds": 6.5,
        "mean_luminance": 110.0,
        "face_detected": True,
        "audio_present": True,
        "video_bitrate_kbps": 2200.0,
    }


def _parse_tool_result(result: Any) -> Dict[str, Any]:
    """Extract JSON payload from MCP CallToolResult."""
    # FastMCP returns content as a list of TextContent objects
    if hasattr(result, "content") and result.content:
        first = result.content[0]
        text = getattr(first, "text", None) or str(first)
        try:
            return json.loads(text)
        except Exception:
            return {"raw_text": text}
    if hasattr(result, "structuredContent") and result.structuredContent:
        return result.structuredContent
    return {"raw": str(result)}


async def run_client_session(session: ClientSession) -> None:
    """Execute the full capabilities query and evidence arbitration workflow."""
    print("=" * 70)
    print(" AEGIS MCP CLIENT — Debate & Arbitration Layer Integration")
    print("=" * 70)

    # 1. Initialize MCP session
    init_result = await session.initialize()
    print(f"\n[1] Connected to server: {init_result.serverInfo.name} v{init_result.serverInfo.version}")

    # 2. List tools
    tools_response = await session.list_tools()
    tool_names = [t.name for t in tools_response.tools]
    print(f"[2] Available tools ({len(tool_names)}): {', '.join(tool_names)}")

    # 3. Call capabilities()
    print("\n" + "-" * 70)
    print(" [3] Querying Detector Capabilities & Reliability Metrics")
    print("-" * 70)
    cap_raw = await session.call_tool("capabilities", {})
    cap_data = _parse_tool_result(cap_raw)

    if cap_data.get("status") == "ok":
        detectors = cap_data.get("detectors", {})
        print(f"Total registered detectors: {cap_data.get('total_detectors', len(detectors))}")
        print("\nDetector Summary:")
        print(f"  {'DETECTOR ID':<20} {'TIER':<18} {'DEFAULT WEIGHT':<15}")
        print(f"  {'-'*18:<20} {'-'*16:<18} {'-'*14:<15}")
        for det_id, meta in sorted(detectors.items()):
            tier = meta.get("authority_tier", "primary")
            weight = meta.get("default_weight", 1.0)
            print(f"  {det_id:<20} {tier:<18} {weight:<15.2f}")
    else:
        print(f"Failed to query capabilities: {cap_data.get('error')}")

    # 4. Submit conflicting claims to arbitrate_evidence()
    print("\n" + "-" * 70)
    print(" [4] Submitting Conflicting Claims to arbitrate_evidence()")
    print("-" * 70)
    claims = get_sample_conflicting_claims()
    conditions = get_sample_operating_conditions()

    print(f"Job ID: {claims[0]['job_id']}")
    print(f"Number of detector claims: {len(claims)}")
    for c in claims:
        print(f"  * {c['detector_id']:<18} -> Polarity: {c['polarity']:<12} "
              f"P(synth)={c['confidence']:.2f} | Claim: {c['claim'][:50]}...")

    print("\nRouting claims through AEGIS 3-Round Multi-Agent Arbitration...")
    arb_raw = await session.call_tool(
        "arbitrate_evidence",
        {
            "claims": claims,
            "operating_conditions": conditions,
        },
    )
    verdict_resp = _parse_tool_result(arb_raw)

    # 5. Display Structured Court-Admissible Verdict
    print("\n" + "=" * 70)
    print(" [5] COURT-ADMISSIBLE VERDICT REPORT")
    print("=" * 70)

    if verdict_resp.get("status") != "ok":
        print(f"ERROR: Arbitration failed: {verdict_resp.get('error')}")
        return

    verdict = verdict_resp.get("verdict", {})
    final_verdict = verdict.get("final_verdict")
    calibrated_score = verdict.get("calibrated_score", 0.0)
    interval = verdict.get("confidence_interval", [0.0, 1.0])
    mode = verdict.get("arbitration_mode")
    siem_tier = verdict.get("siem_alert_tier")
    justification = verdict.get("forensic_justification", "")
    evidence_hash = verdict.get("evidence_manifest_hash", "")
    adjudications = verdict.get("adjudications", [])

    print(f"Final Verdict:       {final_verdict}")
    print(f"Calibrated Score:    {calibrated_score:.4f}  (P(synthetic) in [0.0, 1.0])")
    print(f"Confidence Interval: [{interval[0]:.3f}, {interval[1]:.3f}]")
    print(f"Arbitration Mode:    {mode}")
    print(f"SIEM Alert Tier:     {siem_tier}")
    print(f"Evidence Hash:       {evidence_hash}")

    print("\nClaim Adjudications:")
    for adj in adjudications:
        det = adj.get("detector_id")
        orig_p = adj.get("original_polarity")
        orig_c = adj.get("original_confidence")
        acc_c = adj.get("accepted_confidence")
        w = adj.get("weight_assigned")
        reason = adj.get("discount_reason") or "Accepted at full authority"
        print(f"  * {det}: original={orig_p} (p={orig_c:.2f}) -> accepted_p={acc_c:.2f}, weight={w:.2f}")
        print(f"    Reason: {reason}")

    print("\nForensic Justification:")
    for line in justification.splitlines():
        print(f"  {line}")

    # 6. Demonstrate Pipeline Tools (Task 2): check_stream_integrity & verify_media
    print("\n" + "=" * 70)
    print(" [6] PIPELINE TOOLS (verify_media / get_report / check_stream_integrity)")
    print("=" * 70)

    # Demonstrate check_stream_integrity
    integrity_resp = await session.call_tool("check_stream_integrity", {"job_id": "test-job-e2e-001"})
    int_data = _parse_tool_result(integrity_resp)
    print(f"Check Stream Integrity status: {int_data.get('status')}")

    # Demonstrate verify_media on a sample text file
    sample_txt = Path(__file__).resolve().parent / "sample_verification.txt"
    sample_txt.write_text("Artificial intelligence generated text evaluation sample.", encoding="utf-8")
    try:
        vm_raw = await session.call_tool(
            "verify_media",
            {
                "file_path": str(sample_txt),
                "modality": "text",
                "planner_mode": "rule_based",
            },
        )
        vm_data = _parse_tool_result(vm_raw)
        print(f"verify_media submitted: job_id={vm_data.get('job_id')}, status={vm_data.get('status')}")

        if vm_data.get("job_id"):
            rep_raw = await session.call_tool("get_report", {"job_id": vm_data["job_id"]})
            rep_data = _parse_tool_result(rep_raw)
            print(f"get_report initial poll: status={rep_data.get('status')}")
    finally:
        if sample_txt.exists():
            sample_txt.unlink()

    print("=" * 70)
    print(" Arbitration and Pipeline workflow completed successfully.")
    print("=" * 70)


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="AEGIS MCP Example Client")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport to use (default: stdio)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://127.0.0.1:8000/sse",
        help="SSE URL when using sse transport (default: http://127.0.0.1:8000/sse)",
    )
    args = parser.parse_args()

    if args.transport == "sse":
        from mcp.client.sse import sse_client
        print(f"Connecting to SSE server at {args.url}...")
        async with sse_client(args.url) as (read, write):
            async with ClientSession(read, write) as session:
                await run_client_session(session)
    else:
        repo_root = Path(__file__).resolve().parent.parent
        server_script = repo_root / "mcp" / "server.py"
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(server_script)],
            env=None,
        )
        print(f"Launching MCP server subprocess ({sys.executable} {server_script})...")
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await run_client_session(session)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
