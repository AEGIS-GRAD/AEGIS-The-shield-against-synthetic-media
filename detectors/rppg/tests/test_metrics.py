"""
Tests for rPPG Prometheus /metrics endpoint and telemetry tracking
"""

import os
import pytest
from fastapi.testclient import TestClient

from main import app
from telemetry import track_inference, INFERENCE_TIME, CALL_COUNT

client = TestClient(app)


def test_rppg_metrics_endpoint_exposed():
    """Verify that /metrics endpoint is mounted and returns Prometheus metrics."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    content = response.text
    assert "detector_inference_latency_seconds" in content
    assert "detector_inference_calls_total" in content


def test_rppg_track_inference_decorator_records_call():
    """Verify @track_inference decorator increments counter and observes latency."""
    calls_before = CALL_COUNT.labels(model_name="test_rppg")._value.get()

    @track_inference("test_rppg")
    def sample_func():
        return 42

    result = sample_func()
    assert result == 42
    calls_after = CALL_COUNT.labels(model_name="test_rppg")._value.get()
    assert calls_after == calls_before + 1


def test_rppg_track_inference_artificial_delay_hook():
    """Verify that AEGIS_ARTIFICIAL_DELAY_MS delays execution and observes latency."""
    import asyncio
    import time

    os.environ["AEGIS_ARTIFICIAL_DELAY_MS"] = "150"  # 150ms delay
    try:
        @track_inference("test_rppg_delay")
        async def async_sample():
            return "delayed"

        t0 = time.perf_counter()
        res = asyncio.run(async_sample())
        duration = time.perf_counter() - t0

        assert res == "delayed"
        assert duration >= 0.14  # At least 140ms
    finally:
        del os.environ["AEGIS_ARTIFICIAL_DELAY_MS"]

