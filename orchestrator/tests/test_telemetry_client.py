"""
Tests for orchestrator/app/telemetry_client.py and telemetry-driven eligibility
"""

import pytest
import httpx
from unittest.mock import MagicMock

from orchestrator.app.telemetry_client import (
    PrometheusTelemetryClient,
    DetectorTelemetry,
    BASELINE_LATENCIES_MS,
    get_telemetry_snapshot,
)
from orchestrator.app.eligibility import apply_telemetry_constraints


def test_baseline_fallback_on_unreachable_prometheus():
    """When Prometheus cannot be reached, fallback safely to baseline with 0 crashes."""
    client = PrometheusTelemetryClient(prometheus_url="http://127.0.0.1:59999", timeout_s=0.1)
    snapshot = client.get_telemetry_snapshot()

    assert len(snapshot) == 4
    for det in ["video-classifier", "rppg", "aasist", "syncnet"]:
        assert det in snapshot
        t = snapshot[det]
        assert t.detector_name == det
        assert t.source == "baseline_fallback"
        assert t.status == "healthy"
        assert t.p95_latency_ms == BASELINE_LATENCIES_MS[det]["p95"]
        assert t.avg_latency_ms == BASELINE_LATENCIES_MS[det]["avg"]
        assert t.up is True


def test_successful_mocked_prometheus_parsing():
    """Mock Prometheus HTTP query responses and verify accurate parsing."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        query = request.url.params.get("query", "")

        # 1. p95 query
        if "histogram_quantile" in query:
            return httpx.Response(200, json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {"metric": {"model_name": "aasist"}, "value": [1700000000, "8.2"]},
                        {"metric": {"model_name": "video-classifier"}, "value": [1700000000, "7.1"]}
                    ]
                }
            })
        # 2. avg query
        if "_sum" in query:
            return httpx.Response(200, json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {"metric": {"model_name": "aasist"}, "value": [1700000000, "8.0"]},
                        {"metric": {"model_name": "video-classifier"}, "value": [1700000000, "6.5"]}
                    ]
                }
            })
        # 3. calls query
        if "increase" in query:
            return httpx.Response(200, json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {"metric": {"model_name": "aasist"}, "value": [1700000000, "15"]},
                        {"metric": {"model_name": "video-classifier"}, "value": [1700000000, "4"]}
                    ]
                }
            })
        # 4. up query
        if "up{" in query:
            return httpx.Response(200, json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {"metric": {"job": "aegis_detector_aasist"}, "value": [1700000000, "1"]},
                        {"metric": {"job": "aegis_detector_video_classifier"}, "value": [1700000000, "1"]},
                        {"metric": {"job": "aegis_detector_syncnet"}, "value": [1700000000, "0"]}
                    ]
                }
            })
        # 5. memory query
        if "process_resident_memory_bytes" in query:
            return httpx.Response(200, json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {"metric": {"job": "aegis_detector_aasist"}, "value": [1700000000, str(256 * 1024 * 1024)]}
                    ]
                }
            })

        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    client = PrometheusTelemetryClient(http_client=mock_client)
    snapshot = client.get_telemetry_snapshot()

    # AASIST has 8.2s p95 vs 0.334s baseline -> ratio ~ 24.5x -> DEGRADED
    aasist_tel = snapshot["aasist"]
    assert aasist_tel.source == "live_prometheus"
    assert aasist_tel.status == "degraded"
    assert aasist_tel.p95_latency_ms == 8200.0
    assert aasist_tel.avg_latency_ms == 8000.0
    assert aasist_tel.calls_count == 15
    assert aasist_tel.ram_usage_mb == 256.0
    assert aasist_tel.degradation_ratio > 20.0
    assert aasist_tel.up is True

    # video-classifier has 7.1s p95 vs 14.9s baseline -> ratio ~ 0.47x -> HEALTHY
    vc_tel = snapshot["video-classifier"]
    assert vc_tel.source == "live_prometheus"
    assert vc_tel.status == "healthy"
    assert vc_tel.p95_latency_ms == 7100.0

    # SyncNet had up=0 in Prometheus -> DOWN
    sync_tel = snapshot["syncnet"]
    assert sync_tel.status == "down"
    assert sync_tel.up is False


def test_circuit_breaker_open_overrides_to_down():
    """If a detector's circuit breaker is OPEN, it is immediately marked as DOWN."""
    mock_cb = MagicMock()
    mock_cb.state = MagicMock()
    mock_cb.state.name = "OPEN"

    client = PrometheusTelemetryClient(prometheus_url="http://127.0.0.1:59999", timeout_s=0.1)
    snapshot = client.get_telemetry_snapshot(circuit_breakers={"aasist": mock_cb})

    assert snapshot["aasist"].status == "down"
    assert snapshot["aasist"].source == "circuit_breaker"
    assert snapshot["aasist"].up is False


def test_apply_telemetry_constraints_hard_excludes_down():
    """Eligible list excludes 'down' detectors but retains 'degraded' ones."""
    eligible = [
        {"detector_name": "video-classifier"},
        {"detector_name": "aasist"},
        {"detector_name": "rppg"},
    ]
    excluded = []

    telemetry = {
        "video-classifier": DetectorTelemetry(
            detector_name="video-classifier", status="healthy", p95_latency_ms=7000.0,
            avg_latency_ms=6000.0, ram_usage_mb=500.0, vram_usage_mb=None, calls_count=10,
            source="live_prometheus", degradation_ratio=0.5, up=True, last_updated=0
        ),
        "aasist": DetectorTelemetry(
            detector_name="aasist", status="degraded", p95_latency_ms=8200.0,
            avg_latency_ms=8000.0, ram_usage_mb=200.0, vram_usage_mb=None, calls_count=20,
            source="live_prometheus", degradation_ratio=24.5, up=True, last_updated=0
        ),
        "rppg": DetectorTelemetry(
            detector_name="rppg", status="down", p95_latency_ms=6600.0,
            avg_latency_ms=6600.0, ram_usage_mb=None, vram_usage_mb=None, calls_count=0,
            source="live_prometheus", degradation_ratio=None, up=False, last_updated=0
        ),
    }

    new_eligible, new_excluded = apply_telemetry_constraints(eligible, excluded, telemetry)

    eligible_names = [d["detector_name"] for d in new_eligible]
    excluded_names = [d["detector_name"] for d in new_excluded]

    # video-classifier (healthy) and aasist (degraded) remain eligible
    assert "video-classifier" in eligible_names
    assert "aasist" in eligible_names

    # rppg (down) is excluded
    assert "rppg" not in eligible_names
    assert "rppg" in excluded_names
    assert "offline/down" in new_excluded[0]["reason"]
