import asyncio
import inspect
import logging
import time
from functools import wraps
from prometheus_client import Counter, Gauge, Histogram

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

logger = logging.getLogger(__name__)

INFERENCE_TIME = Histogram(
    "detector_inference_latency_seconds",
    "Time spent in the actual AI model inference",
    ["model_name"]
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


def track_inference(model_name: str):
    """Tracks latency, invocation counts, and GPU memory for sync and async endpoints."""
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                CALL_COUNT.labels(model_name=model_name).inc()
                start = time.perf_counter()
                try:
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
                start = time.perf_counter()
                try:
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
