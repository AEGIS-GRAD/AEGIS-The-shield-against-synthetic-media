"""Prometheus telemetry aligned with AEGIS orchestrator/security metric expectations."""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from functools import wraps
from typing import Any, Callable

from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

try:
    import torch

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

logger = logging.getLogger("detector_text.telemetry")

LATENCY_BUCKETS = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    3.0,
    5.0,
    7.5,
    10.0,
    15.0,
    20.0,
    30.0,
    45.0,
    60.0,
    120.0,
)

INFERENCE_TIME = Histogram(
    "detector_inference_latency_seconds",
    "Time spent in the actual AI model inference",
    ["model_name"],
    buckets=LATENCY_BUCKETS,
)
GPU_MEMORY = Gauge(
    "detector_gpu_memory_allocated_bytes",
    "GPU memory allocated by PyTorch",
    ["model_name"],
)
CALL_COUNT = Counter(
    "detector_inference_calls_total",
    "Total number of inference calls",
    ["model_name"],
)

metrics_app = make_asgi_app()


def _get_artificial_delay_sec() -> float:
    """Read artificial delay injection hook for orchestrator slowdown testing."""
    raw = os.environ.get("AEGIS_ARTIFICIAL_DELAY_MS", "0").strip()
    try:
        return max(0.0, float(raw) / 1000.0)
    except ValueError:
        return 0.0


def _record_post_inference(model_name: str, started_at: float) -> None:
    duration = time.perf_counter() - started_at
    INFERENCE_TIME.labels(model_name=model_name).observe(duration)
    if HAS_TORCH and torch.cuda.is_available():
        try:
            GPU_MEMORY.labels(model_name=model_name).set(torch.cuda.memory_allocated())
        except Exception as exc:  # pragma: no cover - defensive NVML guard
            logger.warning("Failed to read GPU memory: %s", exc)


def track_inference(model_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator tracking call counts, latency histogram, and GPU memory for sync/async routes."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                CALL_COUNT.labels(model_name=model_name).inc()
                delay_sec = _get_artificial_delay_sec()
                started_at = time.perf_counter()
                try:
                    if delay_sec > 0:
                        logger.warning(
                            "[TELEMETRY_HOOK] Injecting %.1fms delay into %s",
                            delay_sec * 1000.0,
                            model_name,
                        )
                        await asyncio.sleep(delay_sec)
                    return await func(*args, **kwargs)
                finally:
                    _record_post_inference(model_name, started_at)

            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            CALL_COUNT.labels(model_name=model_name).inc()
            delay_sec = _get_artificial_delay_sec()
            started_at = time.perf_counter()
            try:
                if delay_sec > 0:
                    logger.warning(
                        "[TELEMETRY_HOOK] Injecting %.1fms delay into %s",
                        delay_sec * 1000.0,
                        model_name,
                    )
                    time.sleep(delay_sec)
                return func(*args, **kwargs)
            finally:
                _record_post_inference(model_name, started_at)

        return sync_wrapper

    return decorator
