import asyncio
import inspect
import logging
import os
import time
from functools import wraps
from prometheus_client import Histogram, Gauge, Counter, make_asgi_app

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

logger = logging.getLogger(__name__)

# Extended histogram buckets supporting sub-second audio inference up to 120s video deepfake inference
LATENCY_BUCKETS = (
    0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 120.0
)

INFERENCE_TIME = Histogram(
    "detector_inference_latency_seconds",
    "Time spent in the actual AI model inference",
    ["model_name"],
    buckets=LATENCY_BUCKETS
)
GPU_MEMORY = Gauge(
    "detector_gpu_memory_allocated_bytes",
    "GPU memory allocated by PyTorch",
    ["model_name"]
)
CALL_COUNT = Counter(
    "detector_inference_calls_total",
    "Total number of inference calls",
    ["model_name"]
)

metrics_app = make_asgi_app()


def _get_artificial_delay_sec() -> float:
    """Read artificial delay injection hook for slowdown testing."""
    val = os.environ.get("AEGIS_ARTIFICIAL_DELAY_MS", "0").strip()
    try:
        ms = float(val)
        return max(0.0, ms / 1000.0)
    except ValueError:
        return 0.0


def track_inference(model_name: str):
    """Decorator tracking latency, invocation counts, and GPU memory for both sync and async endpoints."""
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                CALL_COUNT.labels(model_name=model_name).inc()
                delay_sec = _get_artificial_delay_sec()
                start = time.perf_counter()
                try:
                    if delay_sec > 0:
                        logger.warning(
                            f"[TELEMETRY_HOOK] Injecting artificial delay of {delay_sec*1000:.1f}ms into {model_name}"
                        )
                        await asyncio.sleep(delay_sec)
                    return await func(*args, **kwargs)
                finally:
                    duration = time.perf_counter() - start
                    INFERENCE_TIME.labels(model_name=model_name).observe(duration)
                    if HAS_TORCH and torch.cuda.is_available():
                        try:
                            GPU_MEMORY.labels(model_name=model_name).set(torch.cuda.memory_allocated())
                        except Exception as e:
                            logger.warning(f"Failed to read GPU memory: {e}")
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                CALL_COUNT.labels(model_name=model_name).inc()
                delay_sec = _get_artificial_delay_sec()
                start = time.perf_counter()
                try:
                    if delay_sec > 0:
                        logger.warning(
                            f"[TELEMETRY_HOOK] Injecting artificial delay of {delay_sec*1000:.1f}ms into {model_name}"
                        )
                        time.sleep(delay_sec)
                    return func(*args, **kwargs)
                finally:
                    duration = time.perf_counter() - start
                    INFERENCE_TIME.labels(model_name=model_name).observe(duration)
                    if HAS_TORCH and torch.cuda.is_available():
                        try:
                            GPU_MEMORY.labels(model_name=model_name).set(torch.cuda.memory_allocated())
                        except Exception as e:
                            logger.warning(f"Failed to read GPU memory: {e}")
            return sync_wrapper
    return decorator
