"""
Telemetry metrics helper for text-detector matching Prometheus standards in AEGIS.
"""
import time
from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter(
    "text_detector_requests_total",
    "Total number of text detector requests",
    ["status"]
)

REQUEST_LATENCY = Histogram(
    "text_detector_request_duration_seconds",
    "Histogram of text detector latency in seconds",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

PREDICTION_COUNT = Counter(
    "text_detector_predictions_total",
    "Predictions made by text detector",
    ["prediction"]
)
