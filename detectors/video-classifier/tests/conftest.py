import os
import pytest
import cv2
import numpy as np

def pytest_configure(config):
    config.addinivalue_line("markers", "slow: mark test as slow (model download/inference)")


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory):
    """Creates a temporary directory with valid synthetic MP4 files for testing."""
    tmp_dir = tmp_path_factory.mktemp("video_fixtures")
    
    def create_synthetic_mp4(filename, num_frames=30, width=320, height=240, draw_face=True):
        file_path = str(tmp_dir / filename)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(file_path, fourcc, 10.0, (width, height))
        
        for _ in range(num_frames):
            # Create a simple frame
            frame = np.full((height, width, 3), 200, dtype=np.uint8)
            
            if draw_face:
                # Draw a simple circle representing a face
                cv2.circle(frame, (width // 2, height // 2), 50, (100, 150, 200), -1)
                
            out.write(frame)
            
        out.release()
        return file_path

    # Generate test files
    clean_path = create_synthetic_mp4("clean_sample.mp4", draw_face=True)
    compressed_path = create_synthetic_mp4("compressed_sample.mp4", draw_face=True)
    no_face_path = create_synthetic_mp4("no_face_sample.mp4", draw_face=False)
    
    return {
        "clean": clean_path,
        "compressed": compressed_path,
        "no_face": no_face_path
    }

@pytest.fixture
def clean_video(fixtures_dir):
    return fixtures_dir["clean"]

@pytest.fixture
def compressed_video(fixtures_dir):
    return fixtures_dir["compressed"]

@pytest.fixture
def no_face_video(fixtures_dir):
    return fixtures_dir["no_face"]