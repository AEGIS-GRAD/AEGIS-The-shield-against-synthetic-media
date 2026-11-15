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

LATENCY_BUCKETS = (
    0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 60.0
)

INFERENCE_TIME = Histogram(
    "image_detector_inference_latency_seconds",
    "Time spent in AI model inference for image detector",
    ["model_name"],
    buckets=LATENCY_BUCKETS
)
GPU_MEMORY = Gauge(
    "image_detector_gpu_memory_allocated_bytes",
    "GPU memory allocated by PyTorch for image detector",
    ["model_name"]
)
CALL_COUNT = Counter(
    "image_detector_inference_calls_total",
    "Total number of inference calls to image detector",
    ["model_name"]
)

metrics_app = make_asgi_app()


def _get_artificial_delay_sec() -> float:
    val = os.environ.get("AEGIS_ARTIFICIAL_DELAY_MS", "0").strip()
    try:
        return max(0.0, float(val) / 1000.0)
    except ValueError:
        return 0.0


def track_inference(model_name: str):
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                CALL_COUNT.labels(model_name=model_name).inc()
                delay_sec = _get_artificial_delay_sec()
                start = time.perf_counter()
                try:
                    if delay_sec > 0:
                        await asyncio.sleep(delay_sec)
                    return await func(*args, **kwargs)
                finally:
                    duration = time.perf_counter() - start
                    INFERENCE_TIME.labels(model_name=model_name).observe(duration)
                    if HAS_TORCH and torch.cuda.is_available():
                        try:
                            GPU_MEMORY.labels(model_name=model_name).set(
                                torch.cuda.memory_allocated()
                            )
                        except Exception:
                            pass
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                CALL_COUNT.labels(model_name=model_name).inc()
                start = time.perf_counter()
                try:
                    return func(*args, **kwargs)
                finally:
                    duration = time.perf_counter() - start
                    INFERENCE_TIME.labels(model_name=model_name).observe(duration)
            return sync_wrapper
    return decorator