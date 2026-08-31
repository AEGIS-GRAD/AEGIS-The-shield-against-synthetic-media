# AEGIS Inter-Service API Contract

This document defines the strict API contract that all microservices within the AEGIS architecture (specifically `Orchestrator` ↔ `Detectors`) must adhere to. 

> [!IMPORTANT]
> **Strict Conformance Required:** The Orchestrator will instantly reject any detector response that does not match this schema. This ensures the Debate and Inference Engine telemetry loops function correctly.

---

## 1. Security Requirements

To protect the Inference Engine from DoS attacks and malicious payloads, the following security constraints are enforced at the Orchestrator level before any media reaches the detectors:

*   **Authentication:** All internal endpoints must require an API key passed via the `X-Internal-Token` header.
*   **Max Payload Size:** 50 MB hard limit.
*   **Explicit Allowlist & Magic Bytes:** Only `.mp4`, `.mov`, `.wav`, `.mp3`, `.jpg`, `.png`, and `.txt` are permitted. The Orchestrator **MUST** verify the file's magic bytes (file signature) to ensure a malicious executable isn't simply renamed to `.mp4`.
*   **Path Traversal Prevention:** If accepting an internal file path, the Orchestrator **MUST** sanitize the input and ensure the path is strictly confined to the authorized `/shared_volume/` directory to prevent directory traversal (`../../`) attacks.

---

## 2. The Request Schema (Orchestrator → Detector)

When the Orchestrator dispatches a task to a detector, it will send a JSON payload in the following format.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DetectorRequest",
  "type": "object",
  "properties": {
    "job_id": {
      "type": "string",
      "description": "Unique UUID for tracing the request across the debate loop."
    },
    "modality": {
      "type": "string",
      "enum": ["audio", "video", "image", "text"],
      "description": "The modality of the media."
    },
    "payload": {
      "type": "string",
      "description": "The Base64 encoded string of the media file, OR an absolute internal file path (if using shared Docker volumes)."
    }
  },
  "required": ["job_id", "modality", "payload"]
}
```

### Sample Request:
```json
{
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "modality": "video",
  "payload": "/shared_volume/tmp/live_stream_frame_104.mp4"
}
```

---

## 3. The Response Schema (Detector → Orchestrator)

When a detector finishes its inference, it **must** return a JSON object in this exact format. The `latency_ms` and `evidence` fields are critical for the hardware-aware telemetry loop and the Debate Agents.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DetectorResponse",
  "type": "object",
  "properties": {
    "job_id": {
      "type": "string",
      "description": "The exact UUID provided in the Request, used by the Orchestrator to correlate asynchronous responses."
    },
    "confidence": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0,
      "description": "The normalized confidence score. 0.0 = Authentic, 1.0 = Synthetic/Deepfake."
    },
    "raw_score": {
      "type": "number",
      "description": "The unnormalized logit or raw score from the PyTorch model."
    },
    "latency_ms": {
      "type": "integer",
      "description": "The exact time in milliseconds the inference took. Used by the Orchestrator for budget planning."
    },
    "ram_usage_mb": {
      "type": "number",
      "description": "The peak system RAM (in Megabytes) consumed. Optional, though critical for Unified Memory architectures like NVIDIA Jetson."
    },
    "vram_usage_mb": {
      "type": "number",
      "description": "The peak GPU memory (in Megabytes) consumed. Optional, as not all detectors utilize a GPU."
    },
    "model_version": {
      "type": "string",
      "description": "The version of the detector (e.g., 'aasist-v1.2')."
    },
    "evidence": {
      "type": "object",
      "description": "Contextual reasoning for the Debate Agent.",
      "properties": {
        "claim": {
          "type": "string",
          "description": "A human-readable claim (e.g., 'rPPG signal present but highly irregular')."
        },
        "flags": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Specific heuristic flags triggered (e.g., ['face_swap_detected', 'compression_mismatch'])."
        }
      },
      "required": ["claim"]
    }
  },
  "required": ["job_id", "confidence", "raw_score", "latency_ms", "model_version", "evidence"]
}
```

### Sample Response:
```json
{
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "confidence": 0.94,
  "raw_score": 12.84,
  "latency_ms": 145,
  "ram_usage_mb": 2048.0,
  "vram_usage_mb": 840.5,
  "model_version": "rppg-resnet-v2",
  "evidence": {
    "claim": "rPPG signal present but highly irregular, suggesting artificial generation of the facial region.",
    "flags": ["heart_rate_anomaly", "spatial_inconsistency"]
  }
}
```
