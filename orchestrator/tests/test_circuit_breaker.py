import asyncio
import time
from circuit_breaker import CircuitBreaker, CircuitBreakerOpenException

async def mock_network_call(should_fail: bool = False, delay: float = 0.1):
    """Simulates a network call to an AI model."""
    await asyncio.sleep(delay)
    if should_fail:
        raise ConnectionError("Mock AI Model is down!")
    return {"status": "success"}

async def run_tests():
    print("=" * 60)
    print("STARTING CIRCUIT BREAKER INTEGRATION TESTS")
    print("=" * 60)
    
    # Initialize a breaker with a very short recovery timeout for testing
    cb = CircuitBreaker(name="syncnet-test", failure_threshold=3, recovery_timeout_sec=2.0)
    
    print("\n--- TEST 1: The 'Happy Path' (Normal Traffic) ---")
    for i in range(2):
        try:
            res = await cb.call_async(mock_network_call, should_fail=False)
            print(f"[req {i+1}] Success. State is: {cb.state.name}")
        except Exception as e:
            print(f"[req {i+1}] Error: {e}")
            
    print("\n--- TEST 2: The 'Catastrophic Crash' (Tripping the Breaker) ---")
    for i in range(3):
        try:
            print(f"[req {i+1}] Simulating crash...")
            await cb.call_async(mock_network_call, should_fail=True)
        except Exception as e:
            print(f"[req {i+1}] Caught Exception: {type(e).__name__} -> Current State: {cb.state.name}")
            
    print("\n--- TEST 3: The 'Instant Rejection' (Preventing DDOS) ---")
    try:
        start_time = time.time()
        print("Sending request while circuit is OPEN...")
        await cb.call_async(mock_network_call, should_fail=False)
    except CircuitBreakerOpenException as e:
        latency = time.time() - start_time
        print(f"REJECTED INSTANTLY in {latency:.4f} seconds!")
        print(f"Caught: {e}")
        
    print("\n--- TEST 4: The 'Self-Healing' (Half-Open Recovery) ---")
    print(f"Waiting 2.1 seconds for recovery timeout...")
    await asyncio.sleep(2.1)
    
    try:
        print("Sending test request (Should trigger HALF_OPEN)...")
        res = await cb.call_async(mock_network_call, should_fail=False)
        print(f"Recovery Request Succeeded! Current State: {cb.state.name}")
    except Exception as e:
        print(f"Error: {e}")
        
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_tests())
