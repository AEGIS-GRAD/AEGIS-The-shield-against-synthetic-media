import time
from circuit_breaker import with_circuit_breaker, CircuitBreakerOpenException

# We configure a strict breaker: trips after 2 strikes (errors or slow responses), 
# and requires 3 seconds to attempt a recovery.
@with_circuit_breaker(
    name="mock_video_classifier", 
    failure_threshold=2, 
    recovery_timeout_sec=3.0, 
    latency_threshold_sec=1.0, 
    latency_window_size=2
)
def call_detector(request_id: int, simulate_failure: bool = False, simulate_slow: bool = False):
    print(f"\n---> [Orchestrator] Sending Request {request_id} to Video Classifier...")
    if simulate_failure:
        print("     [Network] Connection Refused! Detector crashed.")
        raise ConnectionError("Detector offline")
    
    if simulate_slow:
        print("     [Network] Detector is struggling... taking 2 seconds to respond.")
        time.sleep(2.0)
    else:
        print("     [Network] Detector responded instantly.")
        time.sleep(0.1)
        
    return {"verdict": "synthetic", "score": 0.99}

def run_demo():
    print("=== STARTING CIRCUIT BREAKER DEMO ===")
    
    # 1. Normal Operations
    for i in range(1, 3):
        call_detector(i)
        
    # 2. Simulate Latency Spikes (Detector slows down)
    print("\n=== INJECTING ARTIFICIAL LATENCY (Detector slows down) ===")
    for i in range(3, 5):
        # 2 slow responses will push the rolling average > 1.0s and trip the breaker
        call_detector(i, simulate_slow=True)
        
    # 3. Breaker is now OPEN. Subsequent requests should be instantly skipped.
    print("\n=== TESTING OPEN CIRCUIT (Detector is dead, requests should be instantly skipped) ===")
    for i in range(5, 7):
        try:
            call_detector(i)
        except CircuitBreakerOpenException:
            print(f"     [Orchestrator] Caught Exception: Skipped Request {i} successfully. Didn't wait for timeout!")
            
    # 4. Wait for Recovery Timeout
    print("\n=== WAITING FOR RECOVERY TIMEOUT (3 SECONDS) ===")
    time.sleep(3.5)
    
    # 5. Half-Open test (Send 1 request. If it succeeds, circuit Closes).
    print("\n=== TESTING HALF-OPEN (Testing recovery) ===")
    call_detector(7)
    
    # 6. Back to Normal
    print("\n=== CIRCUIT RECOVERED (Normal Operations) ===")
    call_detector(8)

if __name__ == "__main__":
    run_demo()
