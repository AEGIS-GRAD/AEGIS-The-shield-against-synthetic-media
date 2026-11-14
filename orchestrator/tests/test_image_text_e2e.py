"""
Integration tests verifying end-to-end orchestration for Image and Text modalities:
1. Uploaded image file produces a verdict end to end in both planner modes (rule_based, llm).
2. Uploaded text file produces a verdict end to end in both planner modes (rule_based, llm).
"""
import io
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from models import DetectorResult, DetectorEvidence
from main import app

client = TestClient(app)


def test_image_end_to_end_rule_based_mode():
    """Verify image file routes to detector_image and returns verdict in rule_based mode."""
    dummy_image = ("sample.jpg", io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 100), "image/jpeg")

    def mock_dispatch(detectors, job_id, modality, file_path):
        assert detectors == ["detector_image"]
        assert modality == "image"
        return [
            DetectorResult(
                detector="detector_image",
                status="ok",
                job_id=job_id,
                confidence=0.88,
                raw_score=0.82,
                latency_ms=85,
                model_version="mirror-dinov3-v1",
                evidence=DetectorEvidence(
                    claim="MIRROR detected frequency upsampling grid artifacts.",
                    flags=["frequency_anomaly", "exif_missing"],
                ),
            )
        ]

    with patch("main.call_all_detectors", side_effect=mock_dispatch):
        res = client.post(
            "/orchestrate?planner_mode=rule_based",
            files={"file": dummy_image},
            headers={"X-API-Key": "dev_default_key"},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["metadata"]["modality"] == "image"
        assert data["planner_mode"] == "rule_based"
        assert data["detectors_called"] == ["detector_image"]
        assert len(data["raw_results"]) == 1
        assert data["raw_results"][0]["detector"] == "detector_image"
        assert data["raw_results"][0]["status"] == "ok"
        assert data["aggregated_verdict"] in ("AUTHENTIC", "SYNTHETIC", "UNCERTAIN", "INTEGRITY_UNKNOWN")
        assert data["judge_verdict"] is not None


def test_image_end_to_end_llm_mode():
    """Verify image file routes to detector_image in LLM mode."""
    dummy_image = ("sample.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100), "image/png")

    def mock_dispatch(detectors, job_id, modality, file_path):
        assert "detector_image" in detectors
        return [
            DetectorResult(
                detector="detector_image",
                status="ok",
                job_id=job_id,
                confidence=0.91,
                raw_score=0.12,
                latency_ms=65,
                model_version="mirror-dinov3-v1",
                evidence=DetectorEvidence(
                    claim="Clean camera sensor spectrum; authentic EXIF header verified.",
                    flags=[],
                ),
            )
        ]

    with patch("main.call_all_detectors", side_effect=mock_dispatch):
        res = client.post(
            "/orchestrate?planner_mode=llm",
            files={"file": dummy_image},
            headers={"X-API-Key": "dev_default_key"},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["metadata"]["modality"] == "image"
        assert data["planner_mode"] == "llm"
        assert "detector_image" in data["detectors_called"]
        assert data["aggregated_verdict"] in ("AUTHENTIC", "SYNTHETIC", "UNCERTAIN", "INTEGRITY_UNKNOWN")


def test_text_end_to_end_rule_based_mode():
    """Verify text file routes to detector_text and returns verdict in rule_based mode."""
    dummy_text = ("essay.txt", io.BytesIO(b"In this modern world, artificial intelligence plays a crucial role..."), "text/plain")

    def mock_dispatch(detectors, job_id, modality, file_path):
        assert detectors == ["detector_text"]
        assert modality == "text"
        return [
            DetectorResult(
                detector="detector_text",
                status="ok",
                job_id=job_id,
                confidence=0.94,
                raw_score=0.89,
                latency_ms=45,
                model_version="desklib-deberta-v1.01",
                evidence=DetectorEvidence(
                    claim="Text classified as synthetic with high n-gram repetition.",
                    flags=["stylometry_synthetic", "low_vocabulary_diversity"],
                ),
            )
        ]

    with patch("main.call_all_detectors", side_effect=mock_dispatch):
        res = client.post(
            "/orchestrate?planner_mode=rule_based",
            files={"file": dummy_text},
            headers={"X-API-Key": "dev_default_key"},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["metadata"]["modality"] == "text"
        assert data["planner_mode"] == "rule_based"
        assert data["detectors_called"] == ["detector_text"]
        assert len(data["raw_results"]) == 1
        assert data["raw_results"][0]["detector"] == "detector_text"
        assert data["raw_results"][0]["status"] == "ok"
        assert data["aggregated_verdict"] in ("AUTHENTIC", "SYNTHETIC", "UNCERTAIN", "INTEGRITY_UNKNOWN")


def test_text_end_to_end_llm_mode():
    """Verify text file routes to detector_text in LLM mode."""
    dummy_text = ("report.md", io.BytesIO(b"# Technical Specifications\nDetailed breakdown of components..."), "text/markdown")

    def mock_dispatch(detectors, job_id, modality, file_path):
        assert "detector_text" in detectors
        return [
            DetectorResult(
                detector="detector_text",
                status="ok",
                job_id=job_id,
                confidence=0.86,
                raw_score=0.22,
                latency_ms=50,
                model_version="desklib-deberta-v1.01",
                evidence=DetectorEvidence(
                    claim="Natural human stylistic variation detected.",
                    flags=[],
                ),
            )
        ]

    with patch("main.call_all_detectors", side_effect=mock_dispatch):
        res = client.post(
            "/orchestrate?planner_mode=llm",
            files={"file": dummy_text},
            headers={"X-API-Key": "dev_default_key"},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["metadata"]["modality"] == "text"
        assert data["planner_mode"] == "llm"
        assert "detector_text" in data["detectors_called"]
        assert data["aggregated_verdict"] in ("AUTHENTIC", "SYNTHETIC", "UNCERTAIN", "INTEGRITY_UNKNOWN")
