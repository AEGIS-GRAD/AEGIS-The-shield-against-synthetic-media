"""
Unit tests for AASIST audio preprocessing pipeline.
"""

import io
import numpy as np
import soundfile as sf
import torch
import pytest

from preprocessing import (
    convert_to_mono,
    pad_or_truncate,
    resample_waveform,
    load_audio,
    preprocess_audio,
    TARGET_SAMPLE_RATE,
    NB_SAMP,
)


def _generate_synthetic_wav_bytes(num_samples: int = 16000, sr: int = 16000, channels: int = 1) -> bytes:
    """Generates synthetic in-memory WAV audio bytes."""
    if channels == 1:
        data = np.sin(2 * np.pi * 440 * np.arange(num_samples) / sr).astype(np.float32)
    else:
        data = np.stack([
            np.sin(2 * np.pi * 440 * np.arange(num_samples) / sr),
            np.sin(2 * np.pi * 880 * np.arange(num_samples) / sr)
        ], axis=1).astype(np.float32)

    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV")
    return buf.getvalue()


def test_convert_to_mono_1d():
    mono = np.random.randn(1000).astype(np.float32)
    out = convert_to_mono(mono)
    assert out.shape == (1000,)
    np.testing.assert_array_equal(out, mono)


def test_convert_to_mono_2d():
    ch1 = np.ones(1000, dtype=np.float32)
    ch2 = np.ones(1000, dtype=np.float32) * 3
    stereo = np.column_stack([ch1, ch2])
    out = convert_to_mono(stereo)
    assert out.shape == (1000,)
    np.testing.assert_allclose(out, np.ones(1000) * 2.0)


def test_pad_or_truncate_short():
    short_audio = np.random.randn(10000).astype(np.float32)
    out = pad_or_truncate(short_audio, max_len=NB_SAMP)
    assert len(out) == NB_SAMP
    # The first 10,000 samples must match the original short audio
    np.testing.assert_array_equal(out[:10000], short_audio)
    # The repeated part must match the start
    np.testing.assert_array_equal(out[10000:20000], short_audio)


def test_pad_or_truncate_long():
    long_audio = np.random.randn(80000).astype(np.float32)
    out = pad_or_truncate(long_audio, max_len=NB_SAMP)
    assert len(out) == NB_SAMP
    np.testing.assert_array_equal(out, long_audio[:NB_SAMP])


def test_pad_or_truncate_exact():
    exact_audio = np.random.randn(NB_SAMP).astype(np.float32)
    out = pad_or_truncate(exact_audio, max_len=NB_SAMP)
    assert len(out) == NB_SAMP
    np.testing.assert_array_equal(out, exact_audio)


def test_pad_or_truncate_empty():
    empty_audio = np.array([], dtype=np.float32)
    out = pad_or_truncate(empty_audio, max_len=NB_SAMP)
    assert len(out) == NB_SAMP
    assert np.all(out == 0.0)


def test_resample_waveform():
    orig_sr = 8000
    target_sr = 16000
    audio_8k = np.sin(2 * np.pi * 400 * np.arange(8000) / 8000).astype(np.float32)
    resampled = resample_waveform(audio_8k, orig_sr=orig_sr, target_sr=target_sr)
    # 1 second at 8kHz resampled to 16kHz should have ~16000 samples
    assert abs(len(resampled) - 16000) < 50


def test_load_audio_from_bytes():
    wav_bytes = _generate_synthetic_wav_bytes(num_samples=16000, sr=16000)
    waveform, sr = load_audio(wav_bytes)
    assert sr == 16000
    assert len(waveform) == 16000
    assert isinstance(waveform, np.ndarray)


def test_preprocess_audio_end_to_end():
    # 0.5s stereo audio at 44.1 kHz
    wav_bytes = _generate_synthetic_wav_bytes(num_samples=22050, sr=44100, channels=2)
    tensor = preprocess_audio(wav_bytes)
    
    assert isinstance(tensor, torch.Tensor)
    assert tensor.shape == (1, NB_SAMP)
    assert tensor.dtype == torch.float32
    # Values should be normalized within standard audio bounds
    assert torch.all(tensor >= -1.5) and torch.all(tensor <= 1.5)
