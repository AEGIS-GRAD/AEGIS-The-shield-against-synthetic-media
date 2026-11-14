import base64
from io import BytesIO
from unittest.mock import patch, MagicMock
from PIL import Image
import pytest
import torch
from fastapi.testclient import TestClient


def make_b64_image():
    buf = BytesIO()
    Image.new("RGB", (100, 100), color=(120, 150, 180)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def client():
    mock_model = MagicMock()
    mock_model.return_value = torch.tensor([[1.45]])  # Fake logit
    mock_state = {
        "model": mock_model,
        "device": torch.device("cpu"),
        "model_loaded": True
    }
    with patch("app.state", mock_state), \
         patch("app.load_model", return_value=(mock_model, torch.device("cpu"))):
        from app import app
        with TestClient(app) as c:
            yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["model_loaded"] is True


def test_detect_image_contract(client):
    req = {
        "job_id": "test-uuid-role1",
        "modality": "image",
        "payload": make_b64_image()
    }
    r = client.post("/detect", json=req)
    assert r.status_code == 200
    data = r.json()
    assert data["job_id"] == "test-uuid-role1"
    assert 0.0 <= data["confidence"] <= 1.0
    assert "claim" in data["evidence"]


def test_detect_unparseable_image_returns_not_applicable(client):
    req = {
        "job_id": "test-uuid-not-app",
        "modality": "image",
        "payload": "not_an_image_base64_data_here"
    }
    r = client.post("/detect", json=req)
    assert r.status_code == 200
    data = r.json()
    assert "not_applicable" in data["evidence"]["flags"]


def test_detect_invalid_modality_returns_422(client):
    req = {
        "job_id": "test-uuid-bad-mod",
        "modality": "audio",
        "payload": make_b64_image()
    }
    r = client.post("/detect", json=req)
    assert r.status_code == 422