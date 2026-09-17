import time
import logging
from enum import Enum
from functools import wraps

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class CircuitBreakerOpenException(Exception):
    """Raised when the circuit breaker is OPEN and rejecting calls."""
    pass

class CircuitBreaker:
    def __init__(
        self, 
        name: str = "detector_service", 
        # TODO (Month 2): These thresholds are currently hardcoded for Week 3.
        # In Month 2, they must be updated to be dynamic and telemetry-driven,
        # fetching the limits automatically based on Grafana/Prometheus rolling averages.
        failure_threshold: int = 3, 
        recovery_timeout_sec: float = 5.0,
        latency_threshold_sec: float = 3.0,
        latency_window_size: int = 3
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.latency_threshold_sec = latency_threshold_sec
        self.latency_window_size = latency_window_size
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.recent_latencies = []

    def record_failure(self):
        """Records a failure and trips the breaker if threshold is reached."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warning(f"[CircuitBreaker:{self.name}] Failure recorded. Count: {self.failure_count}/{self.failure_threshold}")
        
        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
            self._transition_to(CircuitState.OPEN)

    def record_success(self):
        """Records a success and heals the breaker if it was testing recovery."""
        if self.state == CircuitState.HALF_OPEN:
            logger.info(f"[CircuitBreaker:{self.name}] Recovery successful!")
            self._transition_to(CircuitState.CLOSED)
        self.failure_count = 0

    def _transition_to(self, new_state: CircuitState):
        logger.error(f"[CircuitBreaker:{self.name}] STATE TRANSITION: {self.state.name} -> {new_state.name}")
        self.state = new_state
        if new_state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
            self.failure_count = 0
            self.recent_latencies.clear()

    def can_execute(self) -> bool:
        """Determines if the call is allowed to pass through to the detector."""
        if self.state == CircuitState.CLOSED:
            return True
            
        if self.state == CircuitState.OPEN:
            # Check if enough time has passed to test recovery (HALF_OPEN)
            if time.time() - self.last_failure_time >= self.recovery_timeout_sec:
                self._transition_to(CircuitState.HALF_OPEN)
                return True
            return False
            
        if self.state == CircuitState.HALF_OPEN:
            return True

    def call(self, func, *args, **kwargs):
        """Wraps the function call with circuit breaker logic (latency & errors)."""
        if not self.can_execute():
            logger.error(f"[CircuitBreaker:{self.name}] Request instantly skipped. Circuit is OPEN.")
            raise CircuitBreakerOpenException(f"Service {self.name} is currently unavailable.")

        start_time = time.time()
        try:
            # Actually call the detector service
            result = func(*args, **kwargs)
        except Exception as e:
            # If the detector crashes or network fails, record the error
            self.record_failure()
            raise e
            
        # Check Latency (Rolling Average)
        self._record_latency(start_time)

        # If it was fast and successful
        self.record_success()
        return result

    async def call_async(self, func, *args, **kwargs):
        """Wraps an asynchronous function call with circuit breaker logic."""
        if not self.can_execute():
            logger.error(f"[CircuitBreaker:{self.name}] Request instantly skipped. Circuit is OPEN.")
            raise CircuitBreakerOpenException(f"Service {self.name} is currently unavailable.")

        start_time = time.time()
        try:
            # Actually await the detector service
            result = await func(*args, **kwargs)
        except Exception as e:
            self.record_failure()
            raise e
            
        self._record_latency(start_time)
        self.record_success()
        return result

    def _record_latency(self, start_time: float):
        latency = time.time() - start_time
        self.recent_latencies.append(latency)
        if len(self.recent_latencies) > self.latency_window_size:
            self.recent_latencies.pop(0)
            
        avg_latency = sum(self.recent_latencies) / len(self.recent_latencies)
        if avg_latency > self.latency_threshold_sec:
            logger.warning(
                f"[CircuitBreaker:{self.name}] High rolling average latency "
                f"({avg_latency:.2f}s) exceeded limit ({self.latency_threshold_sec}s)."
            )
            self.record_failure()

# Decorator for easy wrapping of functions
def with_circuit_breaker(**cb_kwargs):
    breaker = CircuitBreaker(**cb_kwargs)
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator
