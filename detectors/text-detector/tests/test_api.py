"""API, JSON Schema contract, auth, and Prometheus telemetry tests for detector_text."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from app import ServiceRuntime, create_app
from config import TextDetectorConfig
from conftest import (
    REPO_ROOT,
    StubBinocularsScorer,
    StubDesklibRunner,
    StubPerplexityScorer,
    b64,
    make_words,
)

SCHEMA_DIR = REPO_ROOT / "shared" / "json-api-contracts-schema"
REQ_SCHEMA = json.loads((SCHEMA_DIR / "detector_request.schema.json").read_text(encoding="utf-8"))
RESP_SCHEMA = json.loads((SCHEMA_DIR / "detector_response.schema.json").read_text(encoding="utf-8"))


def _build_test_client(
    cfg: TextDetectorConfig,
    prob: float = 0.89,
    enable_bino: bool = False,
) -> TestClient:
    runtime = ServiceRuntime(
        config=cfg,
        desklib=StubDesklibRunner(prob=prob),
        perplexity=StubPerplexityScorer(),
        binoculars=StubBinocularsScorer() if enable_bino else None,
    )
    return TestClient(create_app(runtime=runtime))


def test_health_endpoint_reports_readiness(test_config: TextDetectorConfig):
    with _build_test_client(test_config) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "detector_text"
    assert body["model_loaded"] is True


def test_detect_validates_strictly_against_json_contracts_and_populates_metrics(
    test_config: TextDetectorConfig,
):
    payload_obj = {
        "job_id": "job-contract-1",
        "modality": "text",
        "payload": b64(make_words(180)),
    }
    jsonschema.validate(instance=payload_obj, schema=REQ_SCHEMA)

    with _build_test_client(test_config, prob=0.89, enable_bino=True) as client:
        resp = client.post("/detect", json=payload_obj)
        assert resp.status_code == 200
        data = resp.json()
        jsonschema.validate(instance=data, schema=RESP_SCHEMA)
        assert data["status"] == "ok"
        assert data["confidence"] == pytest.approx(0.89)
        assert data["raw_score"] == pytest.approx(0.89)
        assert data["signals"]["perplexity"]["available"] is True
        assert data["signals"]["stylometry"]["vocabulary_diversity"]["total_words"] >= 150

        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200
        metrics_txt = metrics_resp.text
        assert 'detector_inference_calls_total{model_name="detector_text"}' in metrics_txt
        assert 'detector_inference_latency_seconds_bucket' in metrics_txt
        assert 'model_name="detector_text"' in metrics_txt


def test_detect_short_text_returns_not_applicable_without_calling_model(
    test_config: TextDetectorConfig,
):
    stub_runner = StubDesklibRunner(prob=0.95)
    rt = ServiceRuntime(
        config=test_config,
        desklib=stub_runner,
        perplexity=StubPerplexityScorer(),
        binoculars=None,
    )
    payload_obj = {
        "job_id": "job-short-1",
        "modality": "text",
        "payload": b64("Too short to verify reliably."),
    }
    with TestClient(create_app(runtime=rt)) as client:
        resp = client.post("/detect", json=payload_obj)
    assert resp.status_code == 200
    body = resp.json()
    jsonschema.validate(instance=body, schema=RESP_SCHEMA)
    assert body["status"] == "not_applicable"
    assert body["confidence"] == 0.5
    assert "text_too_short" in body["evidence"]["flags"]
    assert stub_runner.calls == []


def test_detect_marginal_length_attenuates_and_legacy_analyze_works(test_config: TextDetectorConfig):
    payload_obj = {
        "job_id": "job-marginal-1",
        "modality": "text",
        "payload": b64(make_words(75)),
    }
    with _build_test_client(test_config, prob=0.90) as client:
        resp = client.post("/detect", json=payload_obj)
        assert resp.status_code == 200
        data = resp.json()
        jsonschema.validate(instance=data, schema=RESP_SCHEMA)
        assert data["status"] == "ok"
        assert data["confidence"] == pytest.approx(0.70)
        assert "short_text_attenuated" in data["evidence"]["flags"]

        legacy = client.post("/analyze", json={"text": make_words(180)})
        assert legacy.status_code == 200
        assert legacy.json()["confidence"] == pytest.approx(0.90)


def test_detect_enforces_internal_token_and_rejects_bad_requests(
    shared_dir: Path, tmp_path: Path
):
    cfg = TextDetectorConfig(
        preload_models=False,
        shared_volume_root=shared_dir,
        calibration_path=tmp_path / "no_cal.json",
        internal_api_key="super-secret-token",
        mesh_strict=False,
        max_chars=800,
    )
    body = {"job_id": "auth-1", "modality": "text", "payload": b64(make_words(60))}

    with _build_test_client(cfg) as client:
        assert client.post("/detect", json=body).status_code == 401
        assert client.post("/detect", json=body, headers={"X-Internal-Token": "wrong"}).status_code == 401
        assert (
            client.post("/detect", json=body, headers={"X-Internal-Token": "super-secret-token"}).status_code
            == 200
        )

        # Wrong modality
        assert (
            client.post(
                "/detect",
                json={"job_id": "m-1", "modality": "audio", "payload": b64("some audio payload")},
                headers={"X-Internal-Token": "super-secret-token"},
            ).status_code
            == 400
        )

        # Traversal rejected
        assert (
            client.post(
                "/detect",
                json={"job_id": "t-1", "modality": "text", "payload": "/etc/passwd"},
                headers={"X-Internal-Token": "super-secret-token"},
            ).status_code
            == 400
        )

        # Oversized returns 413
        assert (
            client.post(
                "/detect",
                json={"job_id": "big-1", "modality": "text", "payload": b64("word " * 300)},
                headers={"X-Internal-Token": "super-secret-token"},
            ).status_code
            == 413
        )

    # Strict mTLS disables shared token check cleanly
    strict_cfg = TextDetectorConfig(
        preload_models=False,
        shared_volume_root=shared_dir,
        calibration_path=tmp_path / "no_cal.json",
        internal_api_key="ignored-in-strict-mtls",
        mesh_strict=True,
    )
    with _build_test_client(strict_cfg) as strict_client:
        assert strict_client.post("/detect", json=body).status_code == 200


def test_detect_degrades_gracefully_when_auxiliary_signals_raise(test_config: TextDetectorConfig):
    class ExplodingBinoculars(StubBinocularsScorer):
        def score(self, text: str):
            raise RuntimeError("simulated binoculars vram error")

    rt = ServiceRuntime(
        config=test_config,
        desklib=StubDesklibRunner(prob=0.82),
        perplexity=StubPerplexityScorer(raises=RuntimeError("simulated gpt2 failure")),
        binoculars=ExplodingBinoculars(),
    )
    payload_obj = {"job_id": "degrade-1", "modality": "text", "payload": b64(make_words(170))}
    with TestClient(create_app(runtime=rt)) as client:
        resp = client.post("/detect", json=payload_obj)
    assert resp.status_code == 200
    body = resp.json()
    jsonschema.validate(instance=body, schema=RESP_SCHEMA)
    assert body["status"] == "ok"
    assert body["confidence"] == pytest.approx(0.82)
    assert body["signals"]["perplexity"]["available"] is False
    assert body["signals"]["binoculars_small"]["available"] is False

