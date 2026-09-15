# AEGIS SyncNet Audio-Visual Synchronization Detector

This microservice wraps the **SyncNet** audio-visual consistency detector for the AEGIS system, based on the research by Joon Son Chung & Andrew Zisserman (*"Out of Time: Automated Lip Sync in the Wild"*, ACCV 2016).

It evaluates the temporal synchrony between speech audio and visible lip movements to detect desynchronization, dubbing, and synthetic manipulation in video media.

---

## Overview

- **Input Modality**: Video (`.mp4`, `.mov`, etc.) provided via standard JSON contract (`modality: "video"`, `payload: <path_or_base64>`) or multipart form upload (`file`).
- **Video Branch**:
  - Extracts frames at 25 fps.
  - Detects facial boundaries (MTCNN or Haar cascade fallback).
  - Crops the mouth ROI (lower 40% of face bounding box) and normalizes.
  - Constructs 5-frame sliding window tensors of shape `(15, H, W)` feeding into SyncNet's video CNN (`netcnnvid`).
- **Audio Branch**:
  - Extracts 16 kHz mono 16-bit PCM audio.
  - Computes 13 MFCC features with a 25ms window and 10ms hop (100 Hz).
  - Matches 20-frame MFCC slices `(1, 13, 20)` with 5-frame video windows feeding into SyncNet's audio CNN (`netcnnaud`).
- **Alignment Scoring**:
  - Evaluates cross-correlation distance across temporal shifts $\pm 15$ frames ($\pm 0.6$ seconds).
  - Computes optimal offset $\arg\min_v d(v)$, minimum distance, and alignment confidence.
  - Maps sync offset and distance into normalized $P(\text{synthetic})$ in $[0.0, 1.0]$.
- **Silent Video / No-Audio Guarantee**:
  - If the input video contains no audio track, the service explicitly returns HTTP 200 with:
    - `confidence`: `0.5`
    - `raw_score`: `0.0`
    - `evidence.flags`: `["not_applicable"]`
    - `evidence.claim`: `"No audio track detected in submitted file — lip-sync analysis skipped."`
  - It never throws an unhandled 500 error or outputs a false-positive detection.

---

## API Contract (Conforms to `shared/json-api-contracts-schema/`)

### 1. `GET /health`
Liveness and readiness probe for Docker and the Orchestrator.

**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "syncnet",
  "model_loaded": true,
  "model_version": "syncnet-v1.3",
  "device": "cpu"
}
```

### 2. `GET /metrics`
Prometheus metrics endpoint exposing latency histograms, GPU memory gauges, and invocation counters.

### 3. `POST /detect`
Performs audio-visual sync analysis.

**Sample Request (JSON):**
```json
{
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "modality": "video",
  "payload": "/shared_volume/tmp/sample.mp4"
}
```

**Sample Response (In-Sync / Authentic Video):**
```json
{
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "confidence": 0.12,
  "raw_score": 0.0,
  "latency_ms": 145,
  "ram_usage_mb": 420.5,
  "vram_usage_mb": null,
  "model_version": "syncnet-v1.3",
  "evidence": {
    "claim": "Lip movements tightly synchronized with audio phonemes (offset: 0 frames, dist: 0.18).",
    "flags": ["lip_sync_verified"]
  }
}
```

**Sample Response (Dubbed / Mismatched Video):**
```json
{
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "confidence": 0.92,
  "raw_score": 8.0,
  "latency_ms": 152,
  "ram_usage_mb": 425.0,
  "vram_usage_mb": null,
  "model_version": "syncnet-v1.3",
  "evidence": {
    "claim": "Severe lip-sync discrepancy detected: audio leads video by 8 frames (320ms), strongly indicating dubbed audio or synthetic generation.",
    "flags": ["sync_offset_detected", "audio_visual_mismatch"]
  }
}
```

**Sample Response (Silent Video):**
```json
{
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "confidence": 0.5,
  "raw_score": 0.0,
  "latency_ms": 32,
  "ram_usage_mb": 390.0,
  "vram_usage_mb": null,
  "model_version": "syncnet-v1.3",
  "evidence": {
    "claim": "No audio track detected in submitted file — lip-sync analysis skipped.",
    "flags": ["not_applicable"]
  }
}
```

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `SYNCNET_WEIGHTS_PATH` | Path to local SyncNet weights checkpoint | `weights/syncnet_v2.model` |
| `SYNCNET_WEIGHTS_URL` | Public checkpoint download mirror | `http://www.robots.ox.ac.uk/~vgg/software/lipsync/data/syncnet_v2.model` |
| `INTERNAL_API_KEY` | Optional inter-service authentication token (`X-Internal-Token`) | None |
| `FFMPEG_PATH` | Custom path to ffmpeg binary | Discovered automatically |

---

## Running Tests

Run the test suite using pytest:

```bash
# From workspace root
python -m pytest detectors/syncnet/tests -v

# Or from detectors/syncnet
cd detectors/syncnet
python -m pytest tests -v
```
