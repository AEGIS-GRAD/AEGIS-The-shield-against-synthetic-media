"""
End-to-End integration tests for the AEGIS MCP Server using official MCP ClientSession.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest
from mcp import StdioServerParameters, stdio_client
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

import server


def _extract_tool_payload(result: Any) -> Dict[str, Any]:
    """Helper to unwrap JSON text content from an MCP CallToolResult."""
    assert not result.isError, f"Tool execution failed: {result}"
    assert len(result.content) > 0, "No content returned by tool"
    text = result.content[0].text
    return json.loads(text)


def test_in_memory_mcp_session_list_tools():
    """Verify tool discovery over an in-memory MCP ClientSession."""
    async def _run():
        async with create_connected_server_and_client_session(server.mcp_server._mcp_server) as session:
            tools_resp = await session.list_tools()
            tool_names = [t.name for t in tools_resp.tools]

            assert "arbitrate_evidence" in tool_names
            assert "capabilities" in tool_names

            for tool in tools_resp.tools:
                assert tool.description is not None
                assert len(tool.description) > 10

    asyncio.run(_run())


def test_in_memory_mcp_session_capabilities():
    """Verify capabilities() execution over MCP ClientSession."""
    async def _run():
        async with create_connected_server_and_client_session(server.mcp_server._mcp_server) as session:
            result = await session.call_tool("capabilities", {})
            payload = _extract_tool_payload(result)

            assert payload["status"] == "ok"
            assert payload["total_detectors"] >= 5
            assert "video-classifier" in payload["detectors"]
            assert "rppg" in payload["detectors"]

    asyncio.run(_run())


def test_in_memory_mcp_session_arbitrate_conflicting(
    sample_video_classifier_synthetic, sample_rppg_authentic, sample_nominal_conditions
):
    """Verify arbitrate_evidence() conflicting claims over MCP ClientSession."""
    async def _run():
        async with create_connected_server_and_client_session(server.mcp_server._mcp_server) as session:
            result = await session.call_tool(
                "arbitrate_evidence",
                {
                    "claims": [sample_video_classifier_synthetic, sample_rppg_authentic],
                    "operating_conditions": sample_nominal_conditions,
                },
            )
            payload = _extract_tool_payload(result)

            assert payload["status"] == "ok"
            assert payload["final_verdict"] == "SYNTHETIC"
            assert payload["calibrated_score"] >= 0.85
            assert "verdict" in payload
            assert "evidence_manifest_hash" in payload["verdict"]

    asyncio.run(_run())


def test_stdio_subprocess_client_e2e(
    sample_video_classifier_synthetic, sample_rppg_authentic, sample_nominal_conditions
):
    """Verify end-to-end stdio transport communication with mcp/server.py subprocess."""
    async def _run():
        repo_root = Path(__file__).resolve().parent.parent.parent
        server_script = repo_root / "mcp" / "server.py"

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(server_script)],
            env=None,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # 1. Initialize
                init_res = await session.initialize()
                assert init_res.serverInfo.name == "aegis-debate"

                # 2. List tools
                tools = await session.list_tools()
                names = [t.name for t in tools.tools]
                assert "arbitrate_evidence" in names
                assert "capabilities" in names

                # 3. Call capabilities
                cap_res = await session.call_tool("capabilities", {})
                cap_data = _extract_tool_payload(cap_res)
                assert cap_data["status"] == "ok"
                assert cap_data["total_detectors"] >= 5

                # 4. Call arbitrate_evidence
                arb_res = await session.call_tool(
                    "arbitrate_evidence",
                    {
                        "claims": [sample_video_classifier_synthetic, sample_rppg_authentic],
                        "operating_conditions": sample_nominal_conditions,
                    },
                )
                arb_data = _extract_tool_payload(arb_res)
                assert arb_data["status"] == "ok"
                assert arb_data["final_verdict"] == "SYNTHETIC"
                assert arb_data["verdict"]["arbitration_mode"] == "expert_deterministic_judge"

    asyncio.run(_run())
