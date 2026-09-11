import pytest
import os

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

@pytest.fixture
def clean_audio():
    return os.path.join(FIXTURE_DIR, "clean_sample.wav")

@pytest.fixture
def short_audio():
    return os.path.join(FIXTURE_DIR, "short_sample.wav")

@pytest.fixture
def odd_samplerate_audio():
    return os.path.join(FIXTURE_DIR, "odd_samplerate.wav")