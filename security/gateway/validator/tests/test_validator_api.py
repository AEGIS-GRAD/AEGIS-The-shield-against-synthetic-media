"""
API-level tests for the gateway validator.

Upstream detector calls are mocked with respx so this suite runs standalone
in CI - it never needs a live video-classifier/aasist container. It covers
the "5+ malicious input cases" deliverable plus a couple of positive
controls so a passing suite can't just mean "everything gets rejected".
"""

import base64

import respx
from fastapi.testclient import TestClient
from httpx import Response

from app import config
from app.main import app

client = TestClient(app)

JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 20
MP4_HEADER = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20
WAV_HEADER = b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE" + b"\x00" * 20


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


# ---------------------------------------------------------------------------
# Malicious input cases (video)
# ---------------------------------------------------------------------------


def test_spoofed_extension_video_is_rejected():
    """A JPEG's real bytes, renamed to claim it's an .mp4."""
    resp = client.post(
        "/validate/video",
        files={"file": ("clip.mp4", JPEG_HEADER, "video/mp4")},
    )
    assert resp.status_code == 415
    assert "error" in resp.json()


def test_disallowed_extension_video_is_rejected():
    """An extension nowhere on the allowlist, e.g. an executable."""
    resp = client.post(
        "/validate/video",
        files={"file": ("payload.exe", b"MZ" + b"\x90" * 30, "application/octet-stream")},
    )
    assert resp.status_code == 415


def test_oversized_video_upload_is_rejected():
    oversized = MP4_HEADER + b"\x00" * (config.MAX_UPLOAD_BYTES + 1)
    resp = client.post(
        "/validate/video",
        files={"file": ("clip.mp4", oversized, "video/mp4")},
    )
    assert resp.status_code == 413


def test_path_traversal_filename_video_is_rejected():
    resp = client.post(
        "/validate/video",
        files={"file": ("../../etc/passwd.mp4", MP4_HEADER, "video/mp4")},
    )
    assert resp.status_code == 400


def test_empty_video_upload_is_rejected():
    resp = client.post(
        "/validate/video",
        files={"file": ("clip.mp4", b"", "video/mp4")},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Malicious input cases (audio)
# ---------------------------------------------------------------------------


def test_spoofed_audio_payload_is_rejected():
    """Declares modality=audio but the decoded payload is actually a JPEG."""
    payload_b64 = base64.b64encode(JPEG_HEADER).decode()
    resp = client.post(
        "/validate/audio",
        json={"job_id": "job-1", "modality": "audio", "payload": payload_b64},
    )
    assert resp.status_code == 415


def test_audio_path_traversal_is_rejected():
    resp = client.post(
        "/validate/audio",
        json={
            "job_id": "job-2",
            "modality": "audio",
            "payload": f"{config.SHARED_VOLUME_ROOT}/../../etc/passwd",
        },
    )
    assert resp.status_code == 400


def test_audio_malformed_base64_is_rejected():
    resp = client.post(
        "/validate/audio",
        json={"job_id": "job-3", "modality": "audio", "payload": "not-valid-base64!!"},
    )
    assert resp.status_code == 400


def test_audio_wrong_modality_is_rejected():
    payload_b64 = base64.b64encode(WAV_HEADER).decode()
    resp = client.post(
        "/validate/audio",
        json={"job_id": "job-4", "modality": "video", "payload": payload_b64},
    )
    assert resp.status_code == 400


def test_audio_oversized_payload_is_rejected():
    oversized = base64.b64encode(WAV_HEADER + b"\x00" * (config.MAX_UPLOAD_BYTES + 1)).decode()
    resp = client.post(
        "/validate/audio",
        json={"job_id": "job-5", "modality": "audio", "payload": oversized},
    )
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Positive controls - a passing suite must not mean "everything is rejected"
# ---------------------------------------------------------------------------


@respx.mock
def test_valid_video_upload_is_forwarded_to_detector():
    respx.post(config.VIDEO_DETECTOR_URL).mock(
        return_value=Response(200, json={"score": 0.1, "verdict": "authentic", "confidence": 0.8})
    )
    resp = client.post(
        "/validate/video",
        files={"file": ("clip.mp4", MP4_HEADER, "video/mp4")},
    )
    assert resp.status_code == 200
    assert resp.json()["verdict"] == "authentic"


@respx.mock
def test_valid_audio_upload_is_forwarded_to_detector():
    respx.post(config.AUDIO_DETECTOR_URL).mock(
        return_value=Response(
            200,
            json={
                "job_id": "job-6",
                "confidence": 0.2,
                "raw_score": -1.2,
                "latency_ms": 12,
                "model_version": "aasist-v1.0",
                "evidence": {"claim": "bonafide"},
            },
        )
    )
    payload_b64 = base64.b64encode(WAV_HEADER).decode()
    resp = client.post(
        "/validate/audio",
        json={"job_id": "job-6", "modality": "audio", "payload": payload_b64},
    )
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "job-6"
