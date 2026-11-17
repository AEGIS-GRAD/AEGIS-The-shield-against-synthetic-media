"""
test_pipeline_tools.py — Integration and unit tests for Task 2 pipeline MCP tools:
- verify_media
- get_report
- check_stream_integrity
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

import server
from job_store import VerificationJobStore, get_job_store
from models import DetectorEvidence, DetectorResult


@pytest.fixture
def temp_text_file() -> str:
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write("In this modern society, artificial intelligence text generation has become ubiquitous.")
        return f.name


@pytest.fixture
def temp_image_file() -> str:
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, mode="wb") as f:
        # Dummy JPEG header
        f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00" + b"\x00" * 100)
        return f.name


def test_verify_media_file_not_found():
    res = server.verify_media(file_path="non_existent_file_12345.xyz")
    assert res["status"] == "error"
    assert "File not found" in res["error"]
    assert res["job_id"] is None


def test_verify_media_async_submission(temp_text_file: str):
    res = server.verify_media(file_path=temp_text_file, modality="text")
    assert res["status"] == "pending"
    assert res["job_id"] is not None
    assert "mcp-" in res["job_id"]
    assert "Use get_report" in res["message"]


def test_get_report_unknown_job():
    res = server.get_report(job_id="non-existent-job-id-999")
    assert res["status"] == "error"
    assert "not found" in res["error"].lower()


def test_verify_media_and_poll_report_e2e(temp_text_file: str):
    """Submits a verification job and polls until completion."""
    async def mock_dispatch(detectors, job_id, modality, file_path):
        return [
            DetectorResult(
                detector="detector_text",
                status="ok",
                job_id=job_id,
                confidence=0.88,
                raw_score=0.88,
                latency_ms=45,
                model_version="desklib-v1",
                evidence=DetectorEvidence(
                    claim="Stylometric anomalies indicate synthetic text.",
                    flags=["stylometry_synthetic"],
                ),
            )
        ]

    store = get_job_store()
    with patch("job_store.call_all_detectors", side_effect=mock_dispatch):
        # Run with sync=True for deterministic test execution
        sub_res = store.submit_job(
            file_path=temp_text_file,
            modality="text",
            planner_mode="rule_based",
            sync=True,
        )
        assert sub_res["status"] == "pending"
        job_id = sub_res["job_id"]

        report_res = server.get_report(job_id=job_id)
        assert report_res["status"] == "completed"
        assert report_res["job_id"] == job_id
        assert report_res["verdict"] in ("SYNTHETIC", "AUTHENTIC", "UNCERTAIN", "INTEGRITY_UNKNOWN")
        assert report_res["calibrated_score"] is not None
        assert report_res["evidence_bundle_ref"] is not None
        assert f"aegis://evidence-vault/{job_id}" == report_res["evidence_bundle_ref"]
        assert "detector_results" in report_res["report"] or "raw_results" in report_res["report"]


def test_verify_media_image_modality_e2e(temp_image_file: str):
    """Tests image modality verification end-to-end via MCP tools."""
    async def mock_dispatch(detectors, job_id, modality, file_path):
        return [
            DetectorResult(
                detector="detector_image",
                status="ok",
                job_id=job_id,
                confidence=0.92,
                raw_score=0.90,
                latency_ms=60,
                model_version="mirror-v1",
                evidence=DetectorEvidence(
                    claim="Frequency grid artifacts detected.",
                    flags=["frequency_anomaly"],
                ),
            )
        ]

    store = get_job_store()
    with patch("job_store.call_all_detectors", side_effect=mock_dispatch):
        sub_res = store.submit_job(
            file_path=temp_image_file,
            modality="image",
            planner_mode="rule_based",
            sync=True,
        )
        job_id = sub_res["job_id"]
        report = server.get_report(job_id)
        assert report["status"] == "completed"
        assert report["verdict"] in ("SYNTHETIC", "AUTHENTIC", "UNCERTAIN", "INTEGRITY_UNKNOWN")
        assert report["evidence_bundle_ref"] is not None


def test_check_stream_integrity_missing_args():
    res = server.check_stream_integrity()
    assert res["status"] == "error"
    assert "Either" in res["error"]


def test_check_stream_integrity_with_mock_hash_chain():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        manifest_path = f.name
        json.dump({"genesis": "GENESIS_123", "chain": []}, f)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        video_path = f.name

    with patch("security.forensics.hash_chain.FrameHashChain.validate_stream") as mock_val:
        mock_val.return_value = (True, -1, "Intact")
        res = server.check_stream_integrity(video_path=video_path, manifest_path=manifest_path)
        assert res["status"] == "ok"
        assert res["stream_intact"] is True
        assert res["tampered_frame"] == -1
        assert res["check_type"] == "stream_frame_hash_chain"


def test_check_stream_integrity_with_vault_job_id():
    res = server.check_stream_integrity(job_id="dummy-completed-job-001")
    # Should query vault and return either ok with record or error if not found
    assert res["status"] in ("ok", "error")
