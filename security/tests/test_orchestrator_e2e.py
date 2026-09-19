import requests
import sys
import os
import time

API_URL = "http://localhost:8000/orchestrate"
DUMMY_VIDEO_PATH = "detectors/video-classifier/tests/fixtures/clean_sample.mp4"

def run_test():
    print("[START] Starting AEGIS E2E Integration Test...")

    if not os.path.exists(DUMMY_VIDEO_PATH):
        print(f"[FATAL] Sample video not found at {DUMMY_VIDEO_PATH}")
        sys.exit(1)

    # Wait for the orchestrator to be fully up
    max_retries = 10
    for attempt in range(max_retries):
        try:
            health = requests.get("http://localhost:8000/health", timeout=2)
            if health.status_code == 200:
                print("[OK] Orchestrator is healthy.")
                break
        except requests.exceptions.RequestException:
            print(f"[WAIT] Waiting for Orchestrator to boot... (Attempt {attempt+1}/{max_retries})")
            time.sleep(3)
    else:
        print("[FATAL] Orchestrator did not become healthy in time.")
        sys.exit(1)

    print(f"[UPLOAD] Uploading {DUMMY_VIDEO_PATH} to Orchestrator...")
    try:
        with open(DUMMY_VIDEO_PATH, "rb") as f:
            files = {"file": ("clean.mp4", f, "video/mp4")}
            response = requests.post(API_URL, files=files, timeout=30)
            
        if response.status_code != 200:
            print(f"[FATAL] Orchestrator returned HTTP {response.status_code}")
            print(response.text)
            sys.exit(1)
            
        data = response.json()
        print("[OK] Received successful response from Orchestrator!")
        
        # Assertions
        detectors_called = data.get("detectors_called", [])
        
        if len(detectors_called) == 0:
            print("[FATAL] Orchestrator did not call any detectors.")
            sys.exit(1)
            
        print(f"[SUCCESS] E2E Test Passed! Successfully called detectors: {detectors_called}")
        print(f"[SUCCESS] Aggregated Verdict: {data.get('aggregated_verdict')}")
        
    except Exception as e:
        print(f"[FATAL] Test failed due to exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_test()
