import os
import json
import sys

# Add root to pythonpath so we can import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from security.forensics.hash_chain import FrameHashChain

DUMMY_VIDEO = "detectors/video-classifier/tests/fixtures/clean_sample.mp4"
MANIFEST_PATH = "security/tests/fixtures/manifest.json"
TAMPERED_MANIFEST = "security/tests/fixtures/tampered_manifest.json"

def setup_dirs():
    os.makedirs("security/tests/fixtures", exist_ok=True)

def test_happy_path():
    chain = FrameHashChain()
    
    print("1. Generating hash chain manifest...")
    chain.generate_manifest(DUMMY_VIDEO, MANIFEST_PATH)
    
    print("2. Validating clean video against manifest...")
    is_valid, bad_idx, msg = chain.validate_stream(DUMMY_VIDEO, MANIFEST_PATH)
    assert is_valid, f"Validation failed on clean video: {msg}"
    print(f"   [OK] Clean video passed! Status: {msg}")

def test_tampering_dropped_frame():
    # Simulate a dropped frame attack by corrupting the manifest.
    # We remove frame index 5, so the validator's 6th hash computation 
    # will not match what it expects.
    with open(MANIFEST_PATH, 'r') as f:
        data = json.load(f)
        
    data["chain"].pop(5) 
    
    with open(TAMPERED_MANIFEST, 'w') as f:
        json.dump(data, f)
        
    chain = FrameHashChain()
    print("\n3. Validating tampered stream (dropped frame simulation)...")
    is_valid, bad_idx, msg = chain.validate_stream(DUMMY_VIDEO, TAMPERED_MANIFEST)
    
    assert not is_valid, "Failed to detect dropped frame!"
    assert bad_idx == 5, f"Expected anomaly at frame 5, got {bad_idx}"
    print(f"   [OK] Tampering detected exactly where expected! Status: {msg}")

if __name__ == "__main__":
    setup_dirs()
    if not os.path.exists(DUMMY_VIDEO):
        print(f"Skipping tests, dummy video {DUMMY_VIDEO} not found.")
    else:
        test_happy_path()
        test_tampering_dropped_frame()
