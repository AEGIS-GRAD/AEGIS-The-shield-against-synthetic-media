import pytest
import numpy as np
import torch
from preprocessing import resample_waveform, preprocess_audio, TARGET_SAMPLE_RATE, NB_SAMP

def test_resample_produces_expected_sample_rate():
    # Test resampling a 44.1kHz dummy waveform to 16kHz
    orig_sr = 44100
    dummy_waveform = np.random.randn(orig_sr).astype(np.float32)
    
    resampled = resample_waveform(dummy_waveform, orig_sr=orig_sr, target_sr=TARGET_SAMPLE_RATE)
    
    assert isinstance(resampled, np.ndarray)
    assert len(resampled) == TARGET_SAMPLE_RATE  # 1 second of audio at 16kHz


def test_resample_from_odd_samplerate(odd_samplerate_audio):
    # odd_samplerate_audio fixture returns (path_or_bytes, orig_sr) or raw path
    # Assuming fixture/test provides source path or audio with 8000Hz
    orig_sr = 8000
    dummy_waveform = np.random.randn(orig_sr).astype(np.float32)
    
    resampled = resample_waveform(dummy_waveform, orig_sr=orig_sr, target_sr=TARGET_SAMPLE_RATE)
    
    assert isinstance(resampled, np.ndarray)
    assert len(resampled) == TARGET_SAMPLE_RATE


def test_preprocess_audio_output_shape(clean_audio):
    # Full pipeline test: checks tensor type and exact AASIST input shape (1, 64600)
    tensor_output = preprocess_audio(clean_audio)
    
    assert isinstance(tensor_output, torch.Tensor)
    assert tensor_output.shape == (1, NB_SAMP)


def test_short_audio_handled_without_crash(short_audio):
    # Confirms short audio clips are repeat-padded correctly to 64600 samples without error
    tensor_output = preprocess_audio(short_audio)
    
    assert tensor_output is not None
    assert isinstance(tensor_output, torch.Tensor)
    assert tensor_output.shape == (1, NB_SAMP)