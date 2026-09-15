import os
import shutil
import subprocess
import tempfile
import cv2
import numpy as np
import pytest
import scipy.io.wavfile

from preprocess import find_ffmpeg_path


def create_face_video(filepath: str, num_frames: int = 50, fps: float = 25.0, mouth_pulsing: bool = True):
    """Creates a synthetic video of a face with animated mouth opening/closing."""
    width, height = 320, 240
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(filepath, fourcc, fps, (width, height))

    face_center = (width // 2, height // 2)
    mouth_center = (width // 2, height // 2 + 40)

    for i in range(num_frames):
        # Blank canvas
        frame = np.full((height, width, 3), 220, dtype=np.uint8)

        # Head / face
        cv2.circle(frame, face_center, 60, (180, 200, 230), -1)

        # Eyes
        cv2.circle(frame, (face_center[0] - 25, face_center[1] - 15), 6, (40, 40, 40), -1)
        cv2.circle(frame, (face_center[0] + 25, face_center[1] - 15), 6, (40, 40, 40), -1)

        # Mouth: opens and closes periodically
        if mouth_pulsing:
            # 2 Hz oscillation: mouth height varies
            phase = np.sin(2.0 * np.pi * (i / fps) * 2.0)
            mouth_h = int(6 + 10 * max(0.0, phase))
            cv2.ellipse(frame, mouth_center, (20, mouth_h), 0, 0, 360, (50, 50, 180), -1)
        else:
            cv2.ellipse(frame, mouth_center, (20, 4), 0, 0, 360, (50, 50, 180), -1)

        out.write(frame)

    out.release()


def create_pulsed_audio(filepath: str, duration_sec: float = 2.0, sample_rate: int = 16000, shift_sec: float = 0.0):
    """Creates an audio track with 2 Hz amplitude-modulated tone matching the mouth oscillation."""
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
    # Carrier: 440 Hz sine tone
    carrier = np.sin(2.0 * np.pi * 440.0 * t)
    # Modulator: 2 Hz pulse shifted by shift_sec
    mod_t = t - shift_sec
    modulator = np.maximum(0.0, np.sin(2.0 * np.pi * 2.0 * mod_t))
    signal = carrier * modulator * 0.8
    int16_sig = (signal * 32767.0).astype(np.int16)
    scipy.io.wavfile.write(filepath, sample_rate, int16_sig)


@pytest.fixture(scope="session")
def sample_clips(tmp_path_factory):
    """Generates authentic, dubbed (shifted audio), and silent video test fixtures."""
    tmp_dir = tmp_path_factory.mktemp("syncnet_fixtures")
    ffmpeg = find_ffmpeg_path()

    # 1. Generate silent video (no audio track at all)
    silent_path = str(tmp_dir / "silent_sample.mp4")
    create_face_video(silent_path, num_frames=50, mouth_pulsing=True)

    # Temporary raw audio and video files
    raw_video = str(tmp_dir / "temp_video.mp4")
    create_face_video(raw_video, num_frames=50, mouth_pulsing=True)

    audio_sync = str(tmp_dir / "audio_sync.wav")
    create_pulsed_audio(audio_sync, duration_sec=2.0, shift_sec=0.0)

    audio_desync = str(tmp_dir / "audio_desync.wav")
    # Shift audio by 0.5 seconds (12.5 frames out of sync)
    create_pulsed_audio(audio_desync, duration_sec=2.0, shift_sec=0.5)

    authentic_mp4 = str(tmp_dir / "authentic_sync.mp4")
    dubbed_mp4 = str(tmp_dir / "dubbed_mismatch.mp4")

    if ffmpeg:
        # Mux audio and video into authentic MP4
        subprocess.run(
            [ffmpeg, "-y", "-i", raw_video, "-i", audio_sync, "-c:v", "copy", "-c:a", "aac", authentic_mp4],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        # Mux desynchronized audio into dubbed MP4
        subprocess.run(
            [ffmpeg, "-y", "-i", raw_video, "-i", audio_desync, "-c:v", "copy", "-c:a", "aac", dubbed_mp4],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        # If ffmpeg is unavailable, use raw_video as fallback
        shutil.copy(raw_video, authentic_mp4)
        shutil.copy(raw_video, dubbed_mp4)

    return {
        "silent": silent_path,
        "authentic": authentic_mp4 if os.path.exists(authentic_mp4) else raw_video,
        "dubbed": dubbed_mp4 if os.path.exists(dubbed_mp4) else raw_video,
        "audio_sync": audio_sync,
        "audio_desync": audio_desync,
    }
