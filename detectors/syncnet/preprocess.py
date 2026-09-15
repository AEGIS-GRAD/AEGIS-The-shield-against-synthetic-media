"""
SyncNet Preprocessor — Video Lip-ROI & Audio MFCC Feature Extraction.

Pipelines:
1. Video Pipeline:
   - Extract frames at 25 fps.
   - Detect face (MTCNN or OpenCV Haar cascade fallback).
   - Crop mouth region (lower 40% of face box).
   - Resize to 112x112 and normalize.
   - Form 5-frame sliding window tensors: shape (15, 112, 112).

2. Audio Pipeline:
   - Extract 16 kHz mono 16-bit PCM audio from video using ffmpeg or direct audio loader.
   - Explicitly detect videos with no audio track -> returns None / has_audio=False.
   - Compute 13 MFCC features with 25ms window & 10ms hop (100 Hz).
   - 0.2s of audio (20 frames of MFCC) corresponds to 5 video frames at 25 fps.
   - Slices shape (1, 13, 20).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np
import scipy.fftpack
import scipy.io.wavfile
import torch

logger = logging.getLogger(__name__)

# Optional MTCNN detector from facenet-pytorch (OpenCV Haar cascade is primary fallback)
try:
    _facenet_pytorch = __import__("facenet_pytorch")
    MTCNN = getattr(_facenet_pytorch, "MTCNN", None)
    HAS_MTCNN = MTCNN is not None
except Exception:
    MTCNN = None
    HAS_MTCNN = False


def find_ffmpeg_path() -> Optional[str]:
    """Finds available ffmpeg executable in system PATH or common installation locations."""
    which_path = shutil.which("ffmpeg")
    if which_path:
        return which_path

    env_path = os.getenv("FFMPEG_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    common_locations = [
        r"C:\Program Files\Softdeluxe\Free Download Manager\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"/usr/bin/ffmpeg",
        r"/usr/local/bin/ffmpeg",
    ]
    for loc in common_locations:
        if os.path.isfile(loc):
            return loc
    return None


class SyncNetPreprocessor:
    """Preprocesses video and audio streams for SyncNet audio-visual synchronization inference."""

    def __init__(
        self,
        device: Optional[torch.device] = None,
        target_fps: float = 25.0,
        sample_rate: int = 16000,
    ) -> None:
        self.target_fps = target_fps
        self.sample_rate = sample_rate
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Initialize face detector
        self.mtcnn = None
        if HAS_MTCNN:
            try:
                self.mtcnn = MTCNN(
                    keep_all=False,
                    select_largest=True,
                    device=str(self.device),
                )
            except Exception as e:
                logger.warning(f"Could not initialize MTCNN: {e}. Haar cascade will be used.")

        # OpenCV Haar cascade fallback
        self.face_cascade = None
        try:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            if os.path.exists(cascade_path):
                self.face_cascade = cv2.CascadeClassifier(cascade_path)
        except Exception as e:
            logger.warning(f"Failed to load OpenCV Haar cascade: {e}")

    # ------------------------------------------------------------------
    # Video & Lip-ROI Extraction
    # ------------------------------------------------------------------

    def extract_frames(self, video_path: str) -> Tuple[List[np.ndarray], float]:
        """Extracts RGB frames from video file and detects native FPS."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path}")

        native_fps = cap.get(cv2.CAP_PROP_FPS) or self.target_fps
        frames: List[np.ndarray] = []
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frames.append(rgb)
        finally:
            cap.release()

        return frames, native_fps

    def detect_face_box(self, frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """Detects primary face bounding box (x, y, w, h)."""
        h, w, _ = frame.shape

        if self.mtcnn is not None:
            try:
                boxes, _ = self.mtcnn.detect(frame)
                if boxes is not None and len(boxes) > 0:
                    box = boxes[0].astype(int)
                    x1, y1 = max(0, box[0]), max(0, box[1])
                    x2, y2 = min(w, box[2]), min(h, box[3])
                    if x2 > x1 and y2 > y1:
                        return (x1, y1, x2 - x1, y2 - y1)
            except Exception as exc:
                logger.debug(f"MTCNN detection error: {exc}")

        if self.face_cascade is not None:
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                faces = self.face_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=3, minSize=(40, 40)
                )
                if len(faces) > 0:
                    # Return largest face
                    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
                    fx, fy, fw, fh = faces[0]
                    return (int(fx), int(fy), int(fw), int(fh))
            except Exception as exc:
                logger.debug(f"Haar cascade detection error: {exc}")

        # Fallback: center region
        side = int(min(h, w) * 0.6)
        x = (w - side) // 2
        y = (h - side) // 2
        return (x, y, side, side)

    def crop_mouth_roi(self, frame: np.ndarray, face_box: Optional[Tuple[int, int, int, int]]) -> np.ndarray:
        """Crops mouth region from frame based on detected face bounding box.

        SyncNet specifies the mouth ROI as the lower half/lower 40% of the face crop,
        resized to 112x112 RGB pixels.
        """
        h, w, _ = frame.shape
        if face_box is None:
            face_box = self.detect_face_box(frame)

        if face_box is not None:
            fx, fy, fw, fh = face_box
            # Mouth is centered in the lower 40% of the face
            my1 = max(0, fy + int(0.55 * fh))
            my2 = min(h, fy + fh)
            mx1 = max(0, fx + int(0.15 * fw))
            mx2 = min(w, fx + int(0.85 * fw))

            if my2 > my1 and mx2 > mx1:
                crop = frame[my1:my2, mx1:mx2]
                return cv2.resize(crop, (112, 112), interpolation=cv2.INTER_LINEAR)

        # Fallback mouth crop: bottom-middle portion of frame
        my1 = int(h * 0.5)
        my2 = int(h * 0.85)
        mx1 = int(w * 0.3)
        mx2 = int(w * 0.7)
        crop = frame[my1:my2, mx1:mx2]
        return cv2.resize(crop, (112, 112), interpolation=cv2.INTER_LINEAR)

    def extract_lip_sequences(self, frames: List[np.ndarray]) -> List[torch.Tensor]:
        """Extracts 5-frame concatenated lip sequences for SyncNet's video branch.

        Each sample has shape (15, 112, 112) representing 5 consecutive 3-channel frames.
        """
        if len(frames) < 5:
            return []

        # Find mouth ROIs for all frames
        last_box = None
        mouth_crops: List[np.ndarray] = []
        for i, frame in enumerate(frames):
            # Detect face every 5 frames or reuse last box for speed
            if i % 5 == 0 or last_box is None:
                last_box = self.detect_face_box(frame)
            crop = self.crop_mouth_roi(frame, last_box)
            # Normalize to [0, 1]
            norm = crop.astype(np.float32) / 255.0
            # Transpose HWC -> CHW (3, 112, 112)
            norm = np.transpose(norm, (2, 0, 1))
            mouth_crops.append(norm)

        # Create 5-frame sliding window sequences
        sequences: List[torch.Tensor] = []
        for i in range(len(mouth_crops) - 4):
            # Concatenate 5 frames along channel dimension -> (15, 112, 112)
            window = np.concatenate(mouth_crops[i : i + 5], axis=0)
            tensor = torch.from_numpy(window).float()
            sequences.append(tensor)

        return sequences

    # ------------------------------------------------------------------
    # Audio Extraction & MFCC Processing
    # ------------------------------------------------------------------

    def extract_audio_waveform(self, video_path: str) -> Optional[np.ndarray]:
        """Extracts 16 kHz mono 16-bit PCM audio from video file.

        Returns:
            1D numpy float32 array in [-1.0, 1.0], or None if no audio track exists.
        """
        # If input is already a WAV file, read directly
        if str(video_path).lower().endswith(".wav"):
            try:
                sr, data = scipy.io.wavfile.read(video_path)
                if data is None or len(data) == 0:
                    return None
                if len(data.shape) > 1:
                    data = data.mean(axis=1)
                # Resample or convert to float32
                if data.dtype == np.int16:
                    data = data.astype(np.float32) / 32768.0
                elif data.dtype == np.int32:
                    data = data.astype(np.float32) / 2147483648.0
                elif data.dtype == np.uint8:
                    data = (data.astype(np.float32) - 128.0) / 128.0
                return data.astype(np.float32)
            except Exception as e:
                logger.warning(f"Error reading WAV file directly: {e}")

        ffmpeg_bin = find_ffmpeg_path()
        if not ffmpeg_bin:
            logger.warning("ffmpeg not found on system. Audio extraction unavailable.")
            return None

        # Create temporary file for extracted WAV
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
            tmp_wav_path = tmp_wav.name

        try:
            cmd = [
                ffmpeg_bin,
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                str(self.sample_rate),
                "-ac",
                "1",
                tmp_wav_path,
            ]
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            # Check if audio extraction succeeded and output file is not empty
            if res.returncode != 0 or not os.path.exists(tmp_wav_path) or os.path.getsize(tmp_wav_path) < 44:
                stderr_text = res.stderr.decode("utf-8", errors="ignore")
                if "does not contain any stream" in stderr_text or "Output file is empty" in stderr_text:
                    logger.info("Video contains no audio track.")
                else:
                    logger.info(f"Audio extraction yielded no audio: {stderr_text[:200]}")
                return None

            sr, data = scipy.io.wavfile.read(tmp_wav_path)
            if data is None or len(data) == 0:
                return None

            if len(data.shape) > 1:
                data = data.mean(axis=1)

            if data.dtype == np.int16:
                float_data = data.astype(np.float32) / 32768.0
            else:
                float_data = data.astype(np.float32)

            return float_data

        except Exception as exc:
            logger.warning(f"Audio extraction exception: {exc}")
            return None
        finally:
            if os.path.exists(tmp_wav_path):
                try:
                    os.remove(tmp_wav_path)
                except Exception:
                    pass

    @staticmethod
    def compute_mfcc(
        audio: np.ndarray,
        sample_rate: int = 16000,
        n_mfcc: int = 13,
        win_length: float = 0.025,
        hop_length: float = 0.010,
        n_mels: int = 40,
        n_fft: int = 512,
    ) -> np.ndarray:
        """Computes 13 MFCC features with 25ms window and 10ms hop (100 Hz).

        Returns:
            np.ndarray of shape (n_frames, n_mfcc).
        """
        # Pre-emphasis
        emphasized = np.append(audio[0], audio[1:] - 0.97 * audio[:-1])

        win_samples = int(win_length * sample_rate)
        hop_samples = int(hop_length * sample_rate)
        num_frames = 1 + int((len(emphasized) - win_samples) / hop_samples)
        if num_frames <= 0:
            return np.zeros((0, n_mfcc), dtype=np.float32)

        # Framing & Hamming window
        indices = (
            np.tile(np.arange(0, win_samples), (num_frames, 1))
            + np.tile(np.arange(0, num_frames * hop_samples, hop_samples), (win_samples, 1)).T
        )
        frames = emphasized[indices.astype(np.int32, copy=False)]
        frames *= np.hamming(win_samples)

        # FFT & Power spectrum
        mag_frames = np.absolute(np.fft.rfft(frames, n_fft))
        pow_frames = (1.0 / n_fft) * (mag_frames ** 2)

        # Mel filterbanks
        low_freq_mel = 0.0
        high_freq_mel = 2595.0 * np.log10(1.0 + (sample_rate / 2.0) / 700.0)
        mel_points = np.linspace(low_freq_mel, high_freq_mel, n_mels + 2)
        hz_points = 700.0 * (10.0 ** (mel_points / 2595.0) - 1.0)
        bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)

        fbank = np.zeros((n_mels, int(np.floor(n_fft / 2 + 1))))
        for m in range(1, n_mels + 1):
            f_m_minus = bin_points[m - 1]
            f_m = bin_points[m]
            f_m_plus = bin_points[m + 1]

            for k in range(f_m_minus, f_m):
                fbank[m - 1, k] = (k - bin_points[m - 1]) / (bin_points[m] - bin_points[m - 1])
            for k in range(f_m, f_m_plus):
                fbank[m - 1, k] = (bin_points[m + 1] - k) / (bin_points[m + 1] - bin_points[m])

        filter_banks = np.dot(pow_frames, fbank.T)
        filter_banks = np.where(filter_banks == 0, np.finfo(float).eps, filter_banks)
        filter_banks = 20 * np.log10(filter_banks)

        # Discrete Cosine Transform (DCT)
        mfcc = scipy.fftpack.dct(filter_banks, type=2, axis=1, norm="ortho")[:, :n_mfcc]

        # Cepstral liftering
        cep_lifter = 22
        n = np.arange(n_mfcc)
        lift = 1 + (cep_lifter / 2) * np.sin(np.pi * n / cep_lifter)
        mfcc *= lift

        return mfcc.astype(np.float32)

    def extract_audio_sequences(self, audio: np.ndarray, num_video_frames: int) -> List[torch.Tensor]:
        """Extracts 20-frame MFCC slices corresponding to 5-frame video windows.

        At 25 fps video and 100 Hz MFCC, 1 video frame corresponds to 4 MFCC frames.
        A 5-frame video window corresponds to 5 * 4 = 20 MFCC frames.
        Returns tensors of shape (1, 13, 20).
        """
        mfcc = self.compute_mfcc(audio, sample_rate=self.sample_rate)
        sequences: List[torch.Tensor] = []

        num_windows = max(0, num_video_frames - 4)
        for i in range(num_windows):
            start_mfcc = i * 4
            end_mfcc = start_mfcc + 20
            if end_mfcc <= len(mfcc):
                slice_mfcc = mfcc[start_mfcc:end_mfcc]  # (20, 13)
                # SyncNet expects (1, 13, 20): (Channel=1, N_mfcc=13, Time=20)
                tensor = torch.from_numpy(slice_mfcc.T).unsqueeze(0).float()
                sequences.append(tensor)
            else:
                break

        return sequences

    def preprocess(
        self, video_path: Union[str, Path]
    ) -> Tuple[List[torch.Tensor], Optional[List[torch.Tensor]], bool]:
        """Runs full preprocessing on video file.

        Returns:
            Tuple of:
            - vid_sequences: List of video tensors each of shape (15, 112, 112).
            - aud_sequences: List of audio tensors each of shape (1, 13, 20), or None if no audio track.
            - has_audio: Boolean flag indicating presence of an audio track.
        """
        frames, _ = self.extract_frames(str(video_path))
        if not frames:
            raise ValueError("No video frames could be extracted from input.")

        vid_sequences = self.extract_lip_sequences(frames)

        waveform = self.extract_audio_waveform(str(video_path))
        if waveform is None or len(waveform) == 0:
            return vid_sequences, None, False

        aud_sequences = self.extract_audio_sequences(waveform, len(frames))
        if not aud_sequences:
            return vid_sequences, None, False

        return vid_sequences, aud_sequences, True
