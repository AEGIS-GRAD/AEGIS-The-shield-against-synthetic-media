import time
from functools import wraps
from prometheus_client import Histogram, Gauge, Counter
import logging

# We will try to import torch to check GPU memory, but fail gracefully if not available.
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
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            CALL_COUNT.labels(model_name=model_name).inc()
            start = time.time()
            try:
                result = func(*args, **kwargs)
            finally:
                duration = time.time() - start
                INFERENCE_TIME.labels(model_name=model_name).observe(duration)
                
                if HAS_TORCH and torch.cuda.is_available():
                    try:
                        mem = torch.cuda.memory_allocated()
                        GPU_MEMORY.labels(model_name=model_name).set(mem)
                    except Exception as e:
                        logger.warning(f"Failed to read GPU memory: {e}")
            return result
        return wrapper
    return decorator
