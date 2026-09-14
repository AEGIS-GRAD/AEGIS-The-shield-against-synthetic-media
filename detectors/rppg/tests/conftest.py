"""Pytest configuration and shared fixtures for the rPPG detector tests."""
import os
import cv2
import numpy as np
import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow (requires real video / full pipeline execution)",
    )


@pytest.fixture(scope="session")
def synthetic_video_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Create a minimal synthetic MP4 with a skin-tone face region for testing.

    The video contains 90 frames at 30 fps (3 seconds) — long enough for
    the CHROM bandpass filter to operate meaningfully.  A filled circle
    simulates a face region with a mild sinusoidal colour oscillation to
    mimic skin-tone fluctuation.
    """
    tmp_dir = tmp_path_factory.mktemp("rppg_fixtures")
    video_path = str(tmp_dir / "synthetic_face.mp4")

    fps = 30
    n_frames = 90
    width, height = 320, 240
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(video_path, fourcc, float(fps), (width, height))

    for i in range(n_frames):
        # Skin-tone base colour with small sinusoidal oscillation (~1 Hz)
        # simulating a plausible (if not physiologically accurate) rPPG signal.
        osc = int(5 * np.sin(2 * np.pi * 1.0 * i / fps))
        frame = np.full((height, width, 3), 200, dtype=np.uint8)
        # Face circle: BGR skin tone + oscillation
        cv2.circle(
            frame,
            (width // 2, height // 2),
            60,
            (100 + osc, 140 + osc, 180 + osc),
            -1,
        )
        out.write(frame)

    out.release()
    return video_path


@pytest.fixture(scope="session")
def real_video_path() -> str:
    """Path to a real video from the eval dataset for slow/plausibility tests.

    Returns the absolute path to eval/data/video_subset/real/006.mp4 relative
    to the repo root.  The test is skipped automatically if the file is absent.
    """
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    path = os.path.join(repo_root, "eval", "data", "video_subset", "real", "006.mp4")
    return path
