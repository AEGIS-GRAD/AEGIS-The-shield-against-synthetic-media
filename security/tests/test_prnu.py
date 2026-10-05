import pytest
import numpy as np
from security.forensics.prnu import PRNUExtractor

@pytest.fixture
def prnu_extractor():
    return PRNUExtractor(level=2, wavelet="db4")

def test_prnu_pce_correlation(prnu_extractor):
    """
    Test that the Peak-to-Correlation Energy (PCE) correctly matches
    a frame to its camera baseline, and rejects frames from other cameras.
    """
    # 1. Simulate Camera A's authentic hardware fingerprint (baseline)
    # We use a fixed seed to represent Camera A's physical sensor defect pattern
    np.random.seed(42)
    camera_a_baseline = np.random.normal(0, 5, (256, 256)).astype(np.float32)

    # Simulate a frame taken from Camera A (baseline + some temporary thermal noise)
    frame_a_residual = camera_a_baseline + np.random.normal(0, 10, (256, 256)).astype(np.float32)

    # 2. Simulate Camera B's hardware fingerprint
    np.random.seed(99)
    camera_b_baseline = np.random.normal(0, 5, (256, 256)).astype(np.float32)

    # 3. Test Authentic Match (Camera A frame vs Camera A baseline)
    pce_authentic = prnu_extractor.compute_pce(frame_a_residual, camera_a_baseline)
    
    # 4. Test Spoof/Deepfake (Camera A frame vs Camera B baseline)
    pce_spoof = prnu_extractor.compute_pce(frame_a_residual, camera_b_baseline)

    # The authentic match should have a massively higher PCE score than the spoof
    assert pce_authentic > pce_spoof
    assert pce_authentic > 100.0  # Authentic PCE is typically very high
    assert pce_spoof < 50.0       # Spoof PCE is typically very low
