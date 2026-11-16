# AEGIS Debate & Arbitration MCP Server

The **AEGIS Debate & Arbitration Model Context Protocol (MCP) Server** exposes the AEGIS multimodal forensic debate and arbitration layer as standardized MCP tools. This enables external AI agents, orchestrators, forensic platforms, and client applications to query detector capabilities and arbitrate conflicting deepfake evidence over standardized transports (stdio and SSE).

---

## Table of Contents

- [Overview](#overview)
- [Architecture & Protocol](#architecture--protocol)
- [Installation & Dependencies](#installation--dependencies)
- [Running the Server](#running-the-server)
  - [Stdio Transport (Default)](#stdio-transport-default)
  - [SSE Transport (Server-Sent Events)](#sse-transport-server-sent-events)
- [Tool Specifications](#tool-specifications)
  - [`capabilities()`](#1-capabilities)
  - [`arbitrate_evidence(claims, operating_conditions)`](#2-arbitrate_evidenceclaims-operating_conditions)
- [Edge Cases & Fallbacks](#edge-cases--fallbacks)
- [Verification with MCP Inspector](#verification-with-mcp-inspector)
- [Example External Client](#example-external-client)
- [Testing](#testing)

---

## Overview

In deepfake forensics, single detectors frequently provide contradictory signals—for example, when a face-swap retains the real physiological pulse of the donor actor while exhibiting visual boundary artifacts, or when poor lighting attenuates camera color signals.

The AEGIS Debate & Arbitration MCP server encapsulates the **Forensic Precedence Matrix** and **3-Round Multi-Agent Structured Debate Protocol**:
1. **Round 1 (Claim Ingestion):** Normalizes heterogeneous detector outputs across spatial, physiological, audio-visual, acoustic, image, and text domains.
2. **Round 2 (Cross-Examination):** Contextualizes claims against detector capability manifests, operating limits, and known failure modes.
3. **Round 3 (Forensic Adjudication):** Evaluates legal precedence rules, applies anti-default integrity guards, and yields an ISO/IEC 27037 compliant `CourtAdmissibleVerdict`.

---

## Architecture & Protocol

```
+-------------------------------------------------------------+
|                     External Agent / Client                 |
|  (Claude Desktop, Cursor, Custom Agent, example_client.py)  |
+------------------------------+------------------------------+
                               | MCP Protocol (stdio or SSE)
+------------------------------v------------------------------+
|                   AEGIS FastMCP Server                      |
|                     (mcp/server.py)                         |
+------------------------------+------------------------------+
                               |
        +----------------------+----------------------+
        |                                             |
+-------v---------------------+         +-------------v---------------+
|        capabilities()       |         |   arbitrate_evidence()      |
| Returns detector manifests  |         | 3-Round Debate Arbitration  |
| and reliability metrics     |         +-------------+---------------+
+-------+---------------------+                       |
        |                               +-------------v---------------+
+-------v---------------------+         |  debate.judge_agent.        |
|  capability_manifests/*.json|         |         JudgeAgent          |
|  (AASIST, rPPG, SyncNet,    |         +-------------+---------------+
|   video-classifier, etc.)   |                       |
+-----------------------------+         +-------------v---------------+
                                        |  CourtAdmissibleVerdict     |
                                        |  - Calibrated score & tier  |
                                        |  - Precedence justifications|
                                        |  - Evidence SHA-256 digest  |
                                        +-----------------------------+
```

---

## Installation & Dependencies

Install dependencies using pip:

```bash
# Inside repo root
pip install -r mcp/requirements.txt
```

Core dependencies:
- `mcp[cli]>=1.2.0,<2.0.0`: Official Python MCP SDK (`FastMCP`)
- `pydantic>=2.0.0`: Strict schema parsing and data validation
- `httpx>=0.27.0`: Transport communication
- `pytest>=7.0.0` & `pytest-asyncio>=0.21.0`: Unit and integration testing

---

## Running the Server

### Stdio Transport (Default)

Used for local command-line client integrations and desktop hosts (such as Claude Desktop or Cursor):

```bash
python mcp/server.py
# or explicitly:
python mcp/server.py --transport stdio
```

#### Configuring in Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "aegis-debate": {
      "command": "python",
      "args": [
        "C:\\path\\to\\AEGIS-The-shield-against-synthetic-media\\mcp\\server.py"
      ],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\AEGIS-The-shield-against-synthetic-media"
      }
    }
  }
}
```

### SSE Transport (Server-Sent Events)

Used for networked or containerized microservice deployments:

```bash
python mcp/server.py --transport sse --host 127.0.0.1 --port 8000
```

The server exposes:
- SSE stream endpoint: `http://127.0.0.1:8000/sse`
- Message POST endpoint: `http://127.0.0.1:8000/messages/`

---

## Tool Specifications

The server registers two tools:

### 1. `capabilities`

Retrieves each registered detector's capability manifest, input requirements, known failure modes, condition-specific reliability rules, default weights, and authority tier.

- **Parameters:** None
- **Returns:**
  ```json
  {
    "status": "ok",
    "total_detectors": 10,
    "detectors": {
      "video-classifier": {
        "manifest": {
          "detector_name": "video-classifier",
          "modality": ["video"],
          "version": "xception-ff++-v1",
          "authority_tier": "primary",
          "base_reliability_weight": 1.5,
          "input_constraints": { "min_duration_seconds": 0.1 },
          "condition_reliability": { ... }
        },
        "default_weight": 1.5,
        "authority_tier": "primary"
      },
      "rppg": {
        "manifest": {
          "detector_name": "rppg",
          "authority_tier": "secondary_proxy",
          "cannot_solely_certify_synthetic": true,
          "base_reliability_weight": 0.45
        },
        "default_weight": 0.45,
        "authority_tier": "secondary_proxy"
      }
    },
    "default_weights": { "video-classifier": 1.5, "rppg": 0.45, ... },
    "authority_tiers": { "video-classifier": "primary", "rppg": "secondary_proxy", ... }
  }
  ```

---

### 2. `arbitrate_evidence(claims, operating_conditions)`

Evaluates multi-detector evidence through the 3-round debate protocol and outputs a binding court-admissible verdict.

- **Parameters:**
  - `claims` (list of dicts, required): List of forensic claims. Each claim dict must conform to `ForensicClaim`:
    | Field | Type | Description |
    |---|---|---|
    | `detector_id` | `str` | e.g. `"video-classifier"`, `"rppg"`, `"syncnet"`, `"aasist"` |
    | `job_id` | `str` | Evidence correlation identifier |
    | `model_version` | `str` | Model identifier string |
    | `domain` | `str` | `"spatial_pixel"`, `"physiological_bvp"`, `"audiovisual_sync"`, `"audio_acoustic"`, `"image_forensic"`, `"text_forensic"` |
    | `polarity` | `str` | `"AUTHENTIC"`, `"SYNTHETIC"`, `"INCONCLUSIVE"`, or `"NOT_APPLICABLE"` |
    | `confidence` | `float` | Estimated $P(\text{synthetic})$ in $[0.0, 1.0]$ |
    | `claim` | `str` | Human-readable forensic claim summary |
    | `flags` | `list[str]` | Optional forensic anomaly or condition flags |
    | `raw_score` | `float` | Optional uncalibrated raw score |

  - `operating_conditions` (dict, optional): Environmental metadata:
    | Field | Type | Description |
    |---|---|---|
    | `duration_seconds` | `float` | Media duration in seconds |
    | `mean_luminance` | `float` | Mean frame luminance $[0.0, 255.0]$ |
    | `face_detected` | `bool` | Whether human facial features were located |
    | `audio_present` | `bool` | Whether audio channel is present |
    | `video_bitrate_kbps` | `float` | Video bitrate |

- **Returns:**
  ```json
  {
    "status": "ok",
    "final_verdict": "SYNTHETIC",
    "calibrated_score": 0.8500,
    "arbitration_mode": "expert_deterministic_judge",
    "forensic_justification": "ARBITRATION RULING (POLARITY_INVERSION): ... Rule 3 Applied (Face-Swap Inpainting) ...",
    "verdict": {
      "verdict_id": "vrd-447b602174b6",
      "job_id": "job-external-agent-001",
      "final_verdict": "SYNTHETIC",
      "calibrated_score": 0.8500,
      "confidence_interval": [0.597, 1.000],
      "arbitration_mode": "expert_deterministic_judge",
      "adjudications": [
        {
          "detector_id": "video-classifier",
          "original_polarity": "SYNTHETIC",
          "original_confidence": 0.94,
          "accepted_confidence": 0.94,
          "weight_assigned": 1.50,
          "discount_reason": null
        },
        {
          "detector_id": "rppg",
          "original_polarity": "AUTHENTIC",
          "original_confidence": 0.18,
          "accepted_confidence": 0.18,
          "weight_assigned": 0.09,
          "discount_reason": "Discounted under Face-Swap Inpainting Rule"
        }
      ],
      "siem_alert_tier": "P1_CRITICAL",
      "evidence_manifest_hash": "e456c4e2ca8ea88264e094817623def0883bc644bbe4255da65a96efc87ef8d3",
      "signed_timestamp": "2026-11-16T17:43:57.756123+00:00"
    },
    "report": { ... }
  }
  ```

---

## Edge Cases & Fallbacks

1. **Empty Claims (`claims=[]`):**
   - Returns a valid `CourtAdmissibleVerdict` with verdict `INTEGRITY_UNKNOWN`, confidence `0.5`, SIEM alert `P2_ELEVATED`, and justification explaining total absence of evidence.
2. **Malformed Claims:**
   - Any missing mandatory fields, invalid domains, or non-numeric confidences return `{"status": "error", "error": "Invalid claim at index i: ..."}` without crashing the server.
3. **Missing LLM Key Fallback:**
   - The server defaults to zero-latency deterministic arbitration (`mode="deterministic"`).
   - Even if configured for agentic mode (`AEGIS_JUDGE_MODE=llm`), any missing API key or generation timeout automatically falls back to the deterministic forensic precedence matrix (`llm_fallback_used=True`).
4. **Secondary Proxy Guard (Guard 2B):**
   - Secondary signals (such as `rppg`) cannot solo-certify `SYNTHETIC` without corroborating primary modalities (preventing false positives).

---

## Verification with MCP Inspector

You can test and inspect the server using the official Anthropic MCP Inspector:

```bash
# Verify via stdio
npx @modelcontextprotocol/inspector python mcp/server.py

# Or start the SSE server and connect via Inspector URL
python mcp/server.py --transport sse --port 8000
# Open http://localhost:5173 in browser, select transport 'SSE', and connect to:
# http://127.0.0.1:8000/sse
```

Steps to verify:
1. Under **Tools**, click `capabilities` and press **Run Tool**. Confirm all 10 manifests and default weights load.
2. Click `arbitrate_evidence`, enter sample claims JSON, and press **Run Tool**. Verify that the structured verdict returns with adjudications and cryptographic evidence hash.

---

## Example External Client

An independent client script `mcp/example_client.py` is included. It uses the official MCP client SDK without importing orchestrator internals:

```bash
python mcp/example_client.py
```

Sample output:
```
======================================================================
 AEGIS MCP CLIENT — Debate & Arbitration Layer Integration
======================================================================
[1] Connected to server: aegis-debate v1.30.0
[2] Available tools (2): arbitrate_evidence, capabilities
...
Final Verdict:       SYNTHETIC
Calibrated Score:    0.8500  (P(synthetic) in [0.0, 1.0])
Arbitration Mode:    expert_deterministic_judge
SIEM Alert Tier:     P1_CRITICAL
```

---

## Testing

Run the comprehensive test suite covering schema validation, edge cases, precedence rules, and end-to-end client sessions:

```bash
pytest mcp/tests/ -v
```
