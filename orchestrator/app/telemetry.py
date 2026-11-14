"""
AEGIS Orchestrator Telemetry & Prometheus Metrics Export.
Provides metrics for:
- AI Planner latency (LLM vs Rule-Based, fallback rate)
- Judge Agent debate adjudication latency
- Circuit Breaker states per detector (Closed=0, Half-Open=1, Open=2)
- Detector invocation latency, volume, and error rates
- Overall orchestration requests and verdicts
"""

import time
import logging
from prometheus_client import Histogram, Gauge, Counter, make_asgi_app

logger = logging.getLogger("aegis.orchestrator.telemetry")

# Latency buckets tailored for LLM planning and detector network calls (0.01s to 60s)
PLANNER_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0)
DISPATCH_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0)
JUDGE_LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0)

# 1. AI Planner Metrics
PLANNER_LATENCY = Histogram(
    "aegis_planner_latency_seconds",
    "Time taken by the Orchestrator Planner to decide detector dispatch plan",
    ["planner_mode", "fallback"],
    buckets=PLANNER_LATENCY_BUCKETS,
)
PLANNER_FALLBACKS = Counter(
    "aegis_planner_fallbacks_total",
    "Total times the LLM Planner fell back to rule-based fallback logic",
    ["reason"],
)

# 2. Circuit Breaker State Gauge (0 = CLOSED, 1 = HALF_OPEN, 2 = OPEN)
CIRCUIT_BREAKER_STATE = Gauge(
    "aegis_circuit_breaker_state",
    "Current state of the detector circuit breaker (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
    ["detector"],
)
CIRCUIT_BREAKER_FAILURES = Counter(
    "aegis_circuit_breaker_failures_total",
    "Total failure events recorded by circuit breakers",
    ["detector"],
)

# 3. Detector Invocation Metrics from Orchestrator perspective
DETECTOR_CALLS_TOTAL = Counter(
    "aegis_detector_calls_total",
    "Total detector dispatches from the orchestrator",
    ["detector", "status"],
)
DETECTOR_CALL_LATENCY = Histogram(
    "aegis_detector_latency_seconds",
    "End-to-end latency of detector requests observed by orchestrator",
    ["detector"],
    buckets=DISPATCH_LATENCY_BUCKETS,
)

# 4. Multi-Agent Judge Adjudication Metrics
JUDGE_ADJUDICATION_LATENCY = Histogram(
    "aegis_judge_adjudication_latency_seconds",
    "Time taken for Judge Agent multi-round debate adjudication",
    ["judge_mode", "verdict"],
    buckets=JUDGE_LATENCY_BUCKETS,
)

# 5. Global Orchestration Requests
ORCHESTRATOR_REQUESTS_TOTAL = Counter(
    "aegis_orchestrator_requests_total",
    "Total requests processed by the orchestrator",
    ["modality", "status", "verdict"],
)

# Prometheus ASGI app for mounting on FastAPI
metrics_app = make_asgi_app()


def update_circuit_breaker_metrics(breakers_dict: dict):
    """Reflect current states of all registered circuit breakers in the Prometheus Gauge."""
    state_mapping = {
        "CLOSED": 0,
        "HALF_OPEN": 1,
        "OPEN": 2,
    }
    for name, breaker in breakers_dict.items():
        state_str = breaker.state.name if hasattr(breaker.state, "name") else str(breaker.state)
        val = state_mapping.get(state_str, 0)
        CIRCUIT_BREAKER_STATE.labels(detector=name).set(val)
