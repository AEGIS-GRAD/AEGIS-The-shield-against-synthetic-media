# Orchestrator Circuit Breaker (Week 3)

## What is this?
This is a lightweight Circuit Breaker module designed to protect the Orchestrator from cascading failures. 

If one of the AI Microservices (e.g., `video-classifier` or `aasist`) crashes or experiences massive GPU latency spikes, the Orchestrator will normally get stuck waiting for a response. If multiple users upload videos while the AI model is stuck, the Orchestrator will run out of memory and the entire system will crash.

This module provides a Python Decorator (`@with_circuit_breaker`) that wraps the Orchestrator's network calls to the AI models.

## How it works (State Machine)
1. **CLOSED (Normal):** Requests pass through to the AI model normally. The breaker tracks the response latency of every request.
2. **OPEN (Tripped):** If the AI model fails or its rolling-average latency exceeds the threshold (e.g. 3 seconds), the breaker trips. Any new requests sent by the Orchestrator are instantly skipped (raising `CircuitBreakerOpenException`) to save the Orchestrator from getting stuck waiting.
3. **HALF-OPEN (Recovery):** After a cooldown period, the breaker lets exactly one test request through. If the AI model responds quickly, the breaker closes (heals) and goes back to normal. If it is still slow, it trips again.

## Usage
Simply import the decorator and wrap your HTTP requests to the AI detectors.

```python
from circuit_breaker import with_circuit_breaker

@with_circuit_breaker(
    name="video_classifier", 
    failure_threshold=3, 
    recovery_timeout_sec=5.0, 
    latency_threshold_sec=3.0
)
def fetch_video_classifier(video_payload):
    # Your httpx/requests call here
    pass
```

## Demo
Run `python demo.py` to see a simulated mathematical proof of the circuit breaker tripping under artificial network latency.

> **Note for Month 2 (TODO):** The thresholds for latency and failures are currently hardcoded. In Month 2, they must be updated to dynamically pull from Grafana/Prometheus telemetry data.
