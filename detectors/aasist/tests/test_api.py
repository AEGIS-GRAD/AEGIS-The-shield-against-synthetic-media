"""
API and contract schema tests for AASIST microservice.
"""

import os
import json
import base64
import pytest
from fastapi.testclient import TestClient
import jsonschema

from app import app, load_model, state

client = TestClient(app)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
BONAFIDE_FILE = os.path.join(FIXTURES_DIR, "bonafide_p228_227.wav")
SPOOF_FILE = os.path.join(FIXTURES_DIR, "spoof_SS_1_p229_c0001.wav")

def _find_schema_path():
    candidate_paths = [
        "/shared/json-api-contracts-schema/detector_response.schema.json",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../shared/json-api-contracts-schema/detector_response.schema.json")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "detector_response.schema.json")),
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            return p
    return candidate_paths[0]

SCHEMA_PATH = _find_schema_path()


@pytest.fixture(scope="session", autouse=True)
def initialize_model():
    """Ensure model is loaded for test execution."""
    weights_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../weights/AASIST.pth")
    )
    load_model(weights_path)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["model_loaded"] is True
    assert data["model_version"] == "aasist-v1.0"
    assert "device" in data


def test_detect_valid_base64_bonafide():
    with open(BONAFIDE_FILE, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "job_id": "test-bonafide-uuid-1",
        "modality": "audio",
        "payload": audio_b64
    }
    response = client.post("/detect", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["job_id"] == "test-bonafide-uuid-1"
    assert 0.0 <= data["confidence"] <= 1.0
    assert isinstance(data["raw_score"], float)
    assert isinstance(data["latency_ms"], int) and data["latency_ms"] >= 0
    assert data["model_version"] == "aasist-v1.0"
    assert "claim" in data["evidence"]
    assert isinstance(data["evidence"]["claim"], str)
    assert isinstance(data["evidence"]["flags"], list)


def test_detect_valid_base64_spoof():
    with open(SPOOF_FILE, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "job_id": "test-spoof-uuid-2",
        "modality": "audio",
        "payload": audio_b64
    }
    response = client.post("/detect", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["job_id"] == "test-spoof-uuid-2"
    assert 0.0 <= data["confidence"] <= 1.0
    assert data["confidence"] > 0.5  # Expect high confidence for spoof


def test_detect_file_path():
    payload = {
        "job_id": "test-filepath-uuid-3",
        "modality": "audio",
        "payload": os.path.abspath(BONAFIDE_FILE)
    }
    response = client.post("/detect", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "test-filepath-uuid-3"


def test_detect_invalid_modality():
    payload = {
        "job_id": "test-invalid-modality",
        "modality": "video",
        "payload": "dummy_data"
    }
    response = client.post("/detect", json=payload)
    assert response.status_code == 422


def test_detect_invalid_base64_payload():
    payload = {
        "job_id": "test-invalid-payload",
        "modality": "audio",
        "payload": "not_valid_base64_audio_$$$!!!"
    }
    response = client.post("/detect", json=payload)
    assert response.status_code == 400


def test_detect_schema_conformance():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)

    with open(BONAFIDE_FILE, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "job_id": "test-schema-conformance-uuid",
        "modality": "audio",
        "payload": audio_b64
    }
    response = client.post("/detect", json=payload)
    assert response.status_code == 200
    data = response.json()

    # Strictly validate against AEGIS API contract schema
    jsonschema.validate(instance=data, schema=schema)
