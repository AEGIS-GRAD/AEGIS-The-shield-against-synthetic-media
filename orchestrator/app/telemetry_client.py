"""
telemetry_client.py — Live Prometheus Inference Telemetry Client
================================================================
Fetches real-time latency, memory, and health telemetry from Prometheus
(and merges circuit-breaker states) to ground the LLM planner in actual system load.

Design Principles:
1. Fail-Safe: NEVER raise exceptions that break the orchestrator or planner.
   If Prometheus is offline, times out, or returns NaN, seamlessly fall back to
   Month 1 benchmark baseline values with clear source attribution.
2. Real-Time Grounding: Computes rolling p95 latency and average latency over a
   configurable window (e.g., 2m or 5m).
3. Status Categorization:
   - "healthy" : live p95 <= DEGRADATION_FACTOR * baseline p95
   - "degraded": live p95 >  DEGRADATION_FACTOR * baseline p95 (default threshold: 2.0x)
   - "down"    : Prometheus reports up==0 OR circuit-breaker is OPEN
   - "no_data" : no inference calls recorded in the current window (cold start)
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Default Prometheus connection & query parameters
DEFAULT_PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
DEFAULT_WINDOW = os.environ.get("TELEMETRY_WINDOW", "2m")
DEFAULT_DEGRADATION_FACTOR = float(os.environ.get("DEGRADATION_FACTOR", "2.0"))
TELEMETRY_TIMEOUT_S = float(os.environ.get("TELEMETRY_TIMEOUT_S", "2.0"))

# Month 1 benchmark baseline latencies (ms) from eval/reports/week_benchmark_report.md
BASELINE_LATENCIES_MS: Dict[str, Dict[str, float]] = {
    "video-classifier": {"avg": 7028.6, "p95": 14961.0},
    "rppg": {"avg": 6607.7, "p95": 15850.0},
    "aasist": {"avg": 234.8, "p95": 334.0},
    "syncnet": {"avg": 9587.4, "p95": 22834.0},
}

# Mapping Prometheus jobs/targets to canonical detector names
JOB_TO_DETECTOR = {
    "aegis_detector_aasist": "aasist",
    "aegis_detector_video_classifier": "video-classifier",
    "aegis_detector_rppg": "rppg",
    "aegis_detector_syncnet": "syncnet",
}


@dataclass
class DetectorTelemetry:
    detector_name: str
    status: str                         # "healthy" | "degraded" | "down" | "no_data"
    p95_latency_ms: Optional[float]
    avg_latency_ms: Optional[float]
    ram_usage_mb: Optional[float]
    vram_usage_mb: Optional[float]
    calls_count: int
    source: str                         # "live_prometheus" | "baseline_fallback" | "circuit_breaker"
    degradation_ratio: Optional[float]  # live_p95 / baseline_p95
    up: bool
    last_updated: float

    def to_dict(self) -> dict:
        return asdict(self)


class PrometheusTelemetryClient:
    """Queries Prometheus HTTP API and constructs unified telemetry snapshots."""

    def __init__(
        self,
        prometheus_url: str = DEFAULT_PROMETHEUS_URL,
        window: str = DEFAULT_WINDOW,
        degradation_factor: float = DEFAULT_DEGRADATION_FACTOR,
        timeout_s: float = TELEMETRY_TIMEOUT_S,
        http_client: Optional[httpx.Client] = None,
    ):
        self.prometheus_url = prometheus_url.rstrip("/")
        self.window = window
        self.degradation_factor = degradation_factor
        self.timeout_s = timeout_s
        self._custom_client = http_client

    def _query(self, client: httpx.Client, query_str: str) -> Optional[List[dict]]:
        """Execute a PromQL query synchronously and return result vector or None on failure."""

        url = f"{self.prometheus_url}/api/v1/query"
        try:
            resp = client.get(url, params={"query": query_str}, timeout=self.timeout_s)
            if resp.status_code != 200:
                logger.debug(f"[TELEMETRY] Prometheus query returned status {resp.status_code}")
                return None
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", {}).get("result", [])
        except Exception as exc:
            logger.debug(f"[TELEMETRY] PromQL query error for '{query_str}': {exc}")
        return None

    def _parse_float_vector(self, results: Optional[List[dict]], label_key: str) -> Dict[str, float]:
        """Extract {label_value: float_val} from Prometheus query result vector."""
        if results is None:
            return {}
        out = {}
        for item in results:
            metric = item.get("metric", {})
            name = metric.get(label_key)
            val_tuple = item.get("value")
            if name and val_tuple and len(val_tuple) == 2:
                try:
                    val = float(val_tuple[1])
                    if not (math.isnan(val) or math.isinf(val)):
                        out[name] = val
                except (ValueError, TypeError):
                    continue
        return out

    def get_telemetry_snapshot(
        self,
        detector_names: Optional[List[str]] = None,
        circuit_breakers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, DetectorTelemetry]:
        """
        Produce a telemetry snapshot for requested detectors.
        Always returns a complete dictionary with entries for all detectors.
        """
        targets = detector_names or list(BASELINE_LATENCIES_MS.keys())
        snapshot: Dict[str, DetectorTelemetry] = {}
        now = time.time()

        live_data_available = False
        p95_by_model: Dict[str, float] = {}
        avg_by_model: Dict[str, float] = {}
        calls_by_model: Dict[str, float] = {}
        up_by_job: Dict[str, float] = {}
        ram_by_job: Dict[str, float] = {}

        try:
            client_ctx = (
                self._custom_client
                if self._custom_client is not None
                else httpx.Client(timeout=self.timeout_s)
            )
            # If managed locally, wrap in context; if injected, use directly
            is_injected = self._custom_client is not None
            client = client_ctx if is_injected else client_ctx.__enter__()

            try:
                # 1. p95 Latency Query
                p95_q = (
                    f"histogram_quantile(0.95, sum by (le, model_name) "
                    f"(rate(detector_inference_latency_seconds_bucket[{self.window}])))"
                )
                p95_res = self._query(client, p95_q)
                p95_by_model = self._parse_float_vector(p95_res, "model_name")

                # 2. Average Latency Query
                avg_q = (
                    f"sum by (model_name) (rate(detector_inference_latency_seconds_sum[{self.window}])) / "
                    f"sum by (model_name) (rate(detector_inference_latency_seconds_count[{self.window}]))"
                )
                avg_res = self._query(client, avg_q)
                avg_by_model = self._parse_float_vector(avg_res, "model_name")

                # 3. Call Count Query
                calls_q = f"sum by (model_name) (increase(detector_inference_calls_total[{self.window}]))"
                calls_res = self._query(client, calls_q)
                calls_by_model = self._parse_float_vector(calls_res, "model_name")

                # 4. Up/Liveness Query
                up_q = 'up{job=~"aegis_detector_.*"}'
                up_res = self._query(client, up_q)
                up_by_job = self._parse_float_vector(up_res, "job")

                # 5. Resident Memory Query (bytes -> MB)
                ram_q = 'process_resident_memory_bytes{job=~"aegis_detector_.*"}'
                ram_res = self._query(client, ram_q)
                ram_by_job = self._parse_float_vector(ram_res, "job")

                # If all queries returned None, Prometheus is offline/unreachable
                if any(r is not None for r in (p95_res, avg_res, calls_res, up_res, ram_res)):
                    live_data_available = True
            finally:
                if not is_injected:
                    client_ctx.__exit__(None, None, None)

        except Exception as exc:
            logger.debug(f"[TELEMETRY] Failed to fetch Prometheus metrics: {exc}")
            live_data_available = False

        # Build telemetry state for each target detector

        for det in targets:
            base_p95 = BASELINE_LATENCIES_MS.get(det, {}).get("p95", 1000.0)
            base_avg = BASELINE_LATENCIES_MS.get(det, {}).get("avg", 500.0)

            # Check circuit breaker first
            cb_open = False
            if circuit_breakers and det in circuit_breakers:
                cb = circuit_breakers[det]
                if hasattr(cb, "state") and getattr(cb.state, "name", "") == "OPEN":
                    cb_open = True

            if cb_open:
                snapshot[det] = DetectorTelemetry(
                    detector_name=det,
                    status="down",
                    p95_latency_ms=base_p95,
                    avg_latency_ms=base_avg,
                    ram_usage_mb=None,
                    vram_usage_mb=None,
                    calls_count=0,
                    source="circuit_breaker",
                    degradation_ratio=None,
                    up=False,
                    last_updated=now,
                )
                continue

            # Check Prometheus job liveness
            det_job = f"aegis_detector_{det.replace('-', '_')}"
            is_up = bool(up_by_job.get(det_job, 1.0) == 1.0) if det_job in up_by_job else True

            if det_job in up_by_job and up_by_job[det_job] == 0.0:
                snapshot[det] = DetectorTelemetry(
                    detector_name=det,
                    status="down",
                    p95_latency_ms=base_p95,
                    avg_latency_ms=base_avg,
                    ram_usage_mb=None,
                    vram_usage_mb=None,
                    calls_count=0,
                    source="live_prometheus",
                    degradation_ratio=None,
                    up=False,
                    last_updated=now,
                )
                continue

            # Evaluate latency metrics if live in Prometheus
            live_p95_s = p95_by_model.get(det)
            live_avg_s = avg_by_model.get(det)
            calls = int(calls_by_model.get(det, 0))

            ram_bytes = ram_by_job.get(det_job)
            ram_mb = round(ram_bytes / (1024 * 1024), 1) if ram_bytes else None

            if live_p95_s is not None and live_p95_s > 0:
                live_p95_ms = live_p95_s * 1000.0
                live_avg_ms = (live_avg_s * 1000.0) if live_avg_s is not None else live_p95_ms
                degradation_ratio = round(live_p95_ms / max(1.0, base_p95), 2)

                status = "degraded" if degradation_ratio >= self.degradation_factor else "healthy"

                snapshot[det] = DetectorTelemetry(
                    detector_name=det,
                    status=status,
                    p95_latency_ms=round(live_p95_ms, 1),
                    avg_latency_ms=round(live_avg_ms, 1),
                    ram_usage_mb=ram_mb,
                    vram_usage_mb=None,
                    calls_count=calls,
                    source="live_prometheus",
                    degradation_ratio=degradation_ratio,
                    up=is_up,
                    last_updated=now,
                )
            else:
                # No live samples in current window -> safe baseline fallback
                snapshot[det] = DetectorTelemetry(
                    detector_name=det,
                    status="healthy" if not live_data_available else "no_data",
                    p95_latency_ms=base_p95,
                    avg_latency_ms=base_avg,
                    ram_usage_mb=ram_mb,
                    vram_usage_mb=None,
                    calls_count=0,
                    source="baseline_fallback",
                    degradation_ratio=1.0,
                    up=is_up,
                    last_updated=now,
                )

        return snapshot


# Module-level convenience singleton
_default_client = PrometheusTelemetryClient()


def get_telemetry_snapshot(
    detector_names: Optional[List[str]] = None,
    circuit_breakers: Optional[Dict[str, Any]] = None,
) -> Dict[str, DetectorTelemetry]:
    """Convenience wrapper to get a telemetry snapshot using default client settings."""
    return _default_client.get_telemetry_snapshot(detector_names, circuit_breakers)
