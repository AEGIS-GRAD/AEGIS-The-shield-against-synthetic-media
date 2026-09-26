"""
Audio preprocessing pipeline for AASIST detector.
Handles audio ingestion (file path, raw bytes, or Base64), resampling to 16 kHz,
mono conversion, normalization, and padding/truncation to 64,600 samples (4.0375s).
"""

import io
import os
import soundfile as sf
import numpy as np
import torch
import torchaudio.transforms as T


TARGET_SAMPLE_RATE = 16000
NB_SAMP = 64600  # AASIST standard input length (~4.04s at 16kHz)


def load_audio(source: str | bytes) -> tuple[np.ndarray, int]:
    """
    Loads an audio file from a file path or in-memory bytes.
    If source is a video file or soundfile reading fails, attempts audio extraction via ffmpeg.
    If no audio track exists, returns a silent waveform.
    
    Returns:
        waveform (np.ndarray): Audio data as float32 numpy array.
        sample_rate (int): Sample rate of the audio file.
    """
    if isinstance(source, bytes):
        audio_stream = io.BytesIO(source)
        try:
            waveform, sample_rate = sf.read(audio_stream, dtype="float32")
            return waveform, sample_rate
        except Exception:
            return np.zeros(NB_SAMP, dtype=np.float32), TARGET_SAMPLE_RATE

    elif isinstance(source, str):
        if not os.path.exists(source):
            raise FileNotFoundError(f"Audio file not found: {source}")
        
        # First try direct soundfile load
        try:
            waveform, sample_rate = sf.read(source, dtype="float32")
            return waveform, sample_rate
        except Exception:
            pass

        # Try extracting audio with ffmpeg if available
        try:
            import imageio_ffmpeg, subprocess, tempfile
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_wav = tmp.name
            cmd = [ffmpeg_exe, "-y", "-i", source, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", tmp_wav]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode == 0 and os.path.exists(tmp_wav) and os.path.getsize(tmp_wav) > 0:
                waveform, sample_rate = sf.read(tmp_wav, dtype="float32")
                try:
                    os.remove(tmp_wav)
                except Exception:
                    pass
                return waveform, sample_rate
        except Exception:
            pass

        # Fallback for silent video / unreadable audio
        return np.zeros(NB_SAMP, dtype=np.float32), TARGET_SAMPLE_RATE

    else:
        raise ValueError(f"Unsupported audio source type: {type(source)}")


def convert_to_mono(waveform: np.ndarray) -> np.ndarray:
    """
    Converts multi-channel audio to mono by averaging channels.
    """
    if waveform.ndim == 1:
        return waveform
    elif waveform.ndim == 2:
        # soundfile returns (samples, channels)
        return np.mean(waveform, axis=1)
    else:
        raise ValueError(f"Unexpected waveform dimensions: {waveform.shape}")


def pad_or_truncate(x: np.ndarray, max_len: int = NB_SAMP) -> np.ndarray:
    """
    Pads or truncates waveform to exactly max_len samples.
    Follows ClovaAI AASIST implementation:
    - If length >= max_len: truncate to [:max_len]
    - If length < max_len: repeat waveform until >= max_len, then truncate.
    """
    x_len = len(x)
    if x_len == 0:
        return np.zeros(max_len, dtype=np.float32)

    if x_len >= max_len:
        return x[:max_len]

    num_repeats = int(np.ceil(max_len / x_len))
    padded = np.tile(x, num_repeats)[:max_len]
    return padded


def resample_waveform(waveform: np.ndarray, orig_sr: int, target_sr: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    """
    Resamples audio waveform to target_sr using torchaudio or scipy.
    """
    if orig_sr == target_sr:
        return waveform

    waveform_tensor = torch.from_numpy(waveform).float().unsqueeze(0)  # (1, T)
    resampler = T.Resample(orig_freq=orig_sr, new_freq=target_sr)
    resampled_tensor = resampler(waveform_tensor)
    return resampled_tensor.squeeze(0).numpy()


def preprocess_audio(source: str | bytes) -> torch.Tensor:
    """
    Full audio preprocessing pipeline for AASIST:
    1. Load audio from file path or bytes.
    2. Convert to mono.
    3. Resample to 16 kHz if necessary.
    4. Repeat-pad or truncate to exactly 64,600 samples.
    5. Convert to PyTorch Tensor of shape (1, 64600).
    
    Returns:
        torch.FloatTensor: Shape (1, 64600)
    """
    waveform, sample_rate = load_audio(source)
    waveform = convert_to_mono(waveform)
    
    if sample_rate != TARGET_SAMPLE_RATE:
        waveform = resample_waveform(waveform, orig_sr=sample_rate, target_sr=TARGET_SAMPLE_RATE)

    waveform = pad_or_truncate(waveform, max_len=NB_SAMP)
    waveform_tensor = torch.from_numpy(waveform.astype(np.float32)).unsqueeze(0)  # (1, 64600)
    return waveform_tensor
