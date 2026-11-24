#!/usr/bin/env python3
"""
prepare_multimodal_ablation_dataset.py
--------------------------------------
Constructs a balanced, stratified 60-video multimodal evaluation dataset covering:
  1. Nominal (20 videos: 10 Authentic, 10 Synthetic deepfakes)
  2. No Face (10 videos: 5 Authentic scenery/objects, 5 Synthetic audio over non-face)
  3. Dubbed Audio (15 videos: Authentic facial video + Synthetic / desynchronized audio)
  4. Low Light (15 videos: 7 Authentic, 8 Synthetic under severe underexposure lum < 30)

All videos are generated with standardized duration (~3.5 seconds) and saved to:
  eval/data/multimodal_ablation_set/videos/<video_id>.mp4
Manifest is written to:
  eval/data/multimodal_ablation_set/manifest.json
"""
from __future__ import annotations

import json
import logging
import os
import random
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "eval" / "data" / "multimodal_ablation_set"
VIDEOS_DIR = OUTPUT_DIR / "videos"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

REAL_VIDEOS_DIR = REPO_ROOT / "eval" / "data" / "video_subset" / "real"
FAKE_VIDEOS_DIR = REPO_ROOT / "eval" / "data" / "video_subset" / "fake"
SAMPLE_VIDEOS_DIR = REPO_ROOT / "web" / "public" / "sample_videos"
FIXTURES_DIR = REPO_ROOT / "eval" / "fixtures" / "edge_cases"

BONAFIDE_AUDIO_DIR = REPO_ROOT / "detectors" / "aasist" / "tests" / "fixtures"
SPOOF_AUDIO_DIR = REPO_ROOT / "detectors" / "aasist" / "tests" / "fixtures"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prepare_dataset")


def find_ffmpeg() -> str:
    which_path = shutil.which("ffmpeg")
    if which_path:
        return which_path
    common = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\Softdeluxe\Free Download Manager\ffmpeg.exe",
    ]
    for loc in common:
        if os.path.isfile(loc):
            return loc
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    raise RuntimeError("FFmpeg executable not found!")


def create_dark_video(input_path: str, output_path: str, target_fps: float = 25.0, factor: float = 0.12) -> None:
    """Reads input video, scales down pixel intensities to create underexposed/dark video."""
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {input_path}")
    
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 320
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 240
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, target_fps, (width, height))
    
    frame_count = 0
    max_frames = int(target_fps * 3.5)
    
    while cap.isOpened() and frame_count < max_frames:
        ret, frame = cap.read()
        if not ret:
            break
        # Scale brightness down to severe dark zone
        dark_frame = np.clip(frame.astype(np.float32) * factor, 0, 255).astype(np.uint8)
        out.write(dark_frame)
        frame_count += 1
        
    cap.release()
    out.release()


def create_no_face_video(output_path: str, duration_sec: float = 3.5, target_fps: float = 25.0) -> None:
    """Creates a natural-looking indoor/office background clip with no human face."""
    width, height = 320, 240
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, target_fps, (width, height))
    total_frames = int(duration_sec * target_fps)
    
    # Static room background: desk, window, wall, notebook
    base = np.full((height, width, 3), (180, 190, 195), dtype=np.uint8)
    # Wall division
    cv2.rectangle(base, (0, 0), (width, 140), (220, 225, 230), -1)
    # Window
    cv2.rectangle(base, (20, 20), (100, 110), (245, 240, 220), -1)
    cv2.rectangle(base, (20, 20), (100, 110), (100, 100, 100), 2)
    # Desk
    cv2.rectangle(base, (0, 140), (width, height), (100, 120, 140), -1)
    # Laptop base on desk
    cv2.rectangle(base, (120, 150), (200, 190), (60, 60, 60), -1)
    # Plant pot
    cv2.circle(base, (260, 140), 18, (80, 140, 90), -1)
    cv2.rectangle(base, (250, 140), (270, 170), (50, 70, 120), -1)
    
    for i in range(total_frames):
        # Slight camera jitter / ambient noise
        noise = np.random.randint(-2, 3, size=(height, width, 3), dtype=np.int16)
        frame = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        out.write(frame)
        
    out.release()


def mux_video_audio(ffmpeg_bin: str, video_in: str, audio_in: str, video_out: str, duration: float = 3.5, audio_delay_sec: float = 0.0) -> None:
    """Combines video and audio streams using FFmpeg with optional audio offset."""
    if audio_delay_sec > 0:
        # Delay audio using adelay filter
        delay_ms = int(audio_delay_sec * 1000)
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", "0", "-t", str(duration), "-i", video_in,
            "-ss", "0", "-t", str(duration), "-i", audio_in,
            "-filter_complex", f"[1:a]adelay={delay_ms}|{delay_ms}[delayed]",
            "-map", "0:v", "-map", "[delayed]",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", video_out
        ]
    else:
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", "0", "-t", str(duration), "-i", video_in,
            "-ss", "0", "-t", str(duration), "-i", audio_in,
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", video_out
        ]
        
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg mux error: {res.stderr[:300]}")


def build_dataset() -> None:
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = find_ffmpeg()
    logger.info(f"Using FFmpeg: {ffmpeg_bin}")
    
    bonafide_audios = sorted(BONAFIDE_AUDIO_DIR.glob("bonafide_*.wav"))
    spoof_audios = sorted(SPOOF_AUDIO_DIR.glob("spoof_*.wav"))
    
    real_video_files = sorted(REAL_VIDEOS_DIR.glob("*.mp4"))
    fake_video_files = sorted(FAKE_VIDEOS_DIR.glob("*.mp4"))
    
    # Also add web sample videos if available
    web_real = SAMPLE_VIDEOS_DIR / "authentic_feed.mp4"
    web_fake1 = SAMPLE_VIDEOS_DIR / "deepfake_feed.mp4"
    web_fake2 = SAMPLE_VIDEOS_DIR / "manipulated_feed.mp4"
    
    manifest: List[Dict[str, Any]] = []
    
    # ------------------------------------------------------------------
    # 1. NOMINAL CONDITION (20 videos: 10 Authentic, 10 Synthetic)
    # ------------------------------------------------------------------
    logger.info("Generating Nominal condition videos (10 Authentic, 10 Synthetic)...")
    
    # 10 Nominal Authentic
    for i in range(10):
        vid_id = f"nominal_auth_{i+1:02d}"
        out_path = VIDEOS_DIR / f"{vid_id}.mp4"
        v_src = str(web_real if i == 0 and web_real.exists() else real_video_files[i % len(real_video_files)])
        a_src = str(bonafide_audios[i % len(bonafide_audios)])
        
        mux_video_audio(ffmpeg_bin, v_src, a_src, str(out_path), duration=3.5)
        manifest.append({
            "video_id": vid_id,
            "filename": f"{vid_id}.mp4",
            "path": str(out_path),
            "label": 0,
            "condition": "nominal",
            "description": f"Nominal authentic sample #{i+1} with genuine face and bonafide speech",
            "expected": {
                "video_classifier": 0,
                "rppg": 0,
                "syncnet": 0,
                "aasist": 0,
                "fusion": 0
            }
        })

    # 10 Nominal Synthetic (Deepfake visuals + Spoofed voice)
    for i in range(10):
        vid_id = f"nominal_synth_{i+1:02d}"
        out_path = VIDEOS_DIR / f"{vid_id}.mp4"
        if i == 0 and web_fake1.exists():
            v_src = str(web_fake1)
        elif i == 1 and web_fake2.exists():
            v_src = str(web_fake2)
        else:
            v_src = str(fake_video_files[i % len(fake_video_files)])
        a_src = str(spoof_audios[i % len(spoof_audios)])
        
        mux_video_audio(ffmpeg_bin, v_src, a_src, str(out_path), duration=3.5)
        manifest.append({
            "video_id": vid_id,
            "filename": f"{vid_id}.mp4",
            "path": str(out_path),
            "label": 1,
            "condition": "nominal",
            "description": f"Nominal synthetic sample #{i+1} with face-swap deepfake and cloned spoof speech",
            "expected": {
                "video_classifier": 1,
                "rppg": 1,
                "syncnet": 1,
                "aasist": 1,
                "fusion": 1
            }
        })

    # ------------------------------------------------------------------
    # 2. NO FACE CONDITION (10 videos: 5 Authentic, 5 Synthetic)
    # ------------------------------------------------------------------
    logger.info("Generating No Face condition videos (5 Authentic, 5 Synthetic)...")
    temp_noface_raw = tempfile.mktemp(suffix=".mp4")
    create_no_face_video(temp_noface_raw, duration_sec=3.5)
    
    # 5 No-Face Authentic (Scenery + Bonafide speech)
    for i in range(5):
        vid_id = f"noface_auth_{i+1:02d}"
        out_path = VIDEOS_DIR / f"{vid_id}.mp4"
        a_src = str(bonafide_audios[(10 + i) % len(bonafide_audios)])
        
        mux_video_audio(ffmpeg_bin, temp_noface_raw, a_src, str(out_path), duration=3.5)
        manifest.append({
            "video_id": vid_id,
            "filename": f"{vid_id}.mp4",
            "path": str(out_path),
            "label": 0,
            "condition": "no_face",
            "description": f"No-face authentic sample #{i+1} (room background with authentic voice)",
            "expected": {
                "video_classifier": None,  # Fatal / uninformative
                "rppg": None,              # Guardrail / uninformative
                "syncnet": None,           # Lip ROI missing / neutral
                "aasist": 0,               # Audio detects bonafide speech
                "fusion": 0
            }
        })

    # 5 No-Face Synthetic (Scenery + Spoofed voice)
    for i in range(5):
        vid_id = f"noface_synth_{i+1:02d}"
        out_path = VIDEOS_DIR / f"{vid_id}.mp4"
        a_src = str(spoof_audios[(10 + i) % len(spoof_audios)])
        
        mux_video_audio(ffmpeg_bin, temp_noface_raw, a_src, str(out_path), duration=3.5)
        manifest.append({
            "video_id": vid_id,
            "filename": f"{vid_id}.mp4",
            "path": str(out_path),
            "label": 1,
            "condition": "no_face",
            "description": f"No-face synthetic sample #{i+1} (camera covered/scenery with synthetic spoof speech)",
            "expected": {
                "video_classifier": None,  # Fatal / uninformative
                "rppg": None,              # Guardrail / uninformative
                "syncnet": None,           # Lip ROI missing / neutral
                "aasist": 1,               # Audio flags voice cloning
                "fusion": 1
            }
        })
        
    if os.path.exists(temp_noface_raw):
        os.remove(temp_noface_raw)

    # ------------------------------------------------------------------
    # 3. DUBBED AUDIO CONDITION (15 videos: 15 Manipulated / Attack)
    # ------------------------------------------------------------------
    logger.info("Generating Dubbed Audio attack videos (15 Manipulated)...")
    # Authentic face video paired with synthetic speech OR desynchronized track
    for i in range(15):
        vid_id = f"dubbed_synth_{i+1:02d}"
        out_path = VIDEOS_DIR / f"{vid_id}.mp4"
        v_src = str(real_video_files[(10 + i) % len(real_video_files)])
        
        # 10 samples with synthetic spoof speech (voice clone attack over real face)
        # 5 samples with genuine speech but heavy desync offset (1.5s delay)
        if i < 10:
            a_src = str(spoof_audios[(15 + i) % len(spoof_audios)])
            offset = 0.0
            desc = f"Dubbed audio attack #{i+1} (Authentic real face paired with synthetic voice clone)"
            exp_aasist = 1
            exp_syncnet = 1
        else:
            a_src = str(bonafide_audios[(15 + i) % len(bonafide_audios)])
            offset = 1.2  # 1.2s desynchronization offset
            desc = f"Dubbed audio attack #{i+1} (Authentic face paired with unsynchronized speech, offset=1.2s)"
            exp_aasist = 0
            exp_syncnet = 1
            
        mux_video_audio(ffmpeg_bin, v_src, a_src, str(out_path), duration=3.5, audio_delay_sec=offset)
        manifest.append({
            "video_id": vid_id,
            "filename": f"{vid_id}.mp4",
            "path": str(out_path),
            "label": 1,
            "condition": "dubbed_audio",
            "description": desc,
            "expected": {
                "video_classifier": 0,     # Visual is real face -> False Authentic!
                "rppg": 0,                 # Real pulse -> False Authentic!
                "syncnet": exp_syncnet,    # Lip-sync detects mismatch!
                "aasist": exp_aasist,      # Spoofed voice or neutral
                "fusion": 1
            }
        })

    # ------------------------------------------------------------------
    # 4. LOW LIGHT CONDITION (15 videos: 7 Authentic, 8 Synthetic)
    # ------------------------------------------------------------------
    logger.info("Generating Low Light condition videos (7 Authentic, 8 Synthetic)...")
    
    # 7 Low-Light Authentic
    for i in range(7):
        vid_id = f"lowlight_auth_{i+1:02d}"
        out_path = VIDEOS_DIR / f"{vid_id}.mp4"
        v_src = str(real_video_files[(25 + i) % len(real_video_files)])
        a_src = str(bonafide_audios[(i) % len(bonafide_audios)])
        
        # Create temporary dark video
        tmp_dark = tempfile.mktemp(suffix=".mp4")
        create_dark_video(v_src, tmp_dark, factor=0.10)
        mux_video_audio(ffmpeg_bin, tmp_dark, a_src, str(out_path), duration=3.5)
        if os.path.exists(tmp_dark):
            os.remove(tmp_dark)
            
        manifest.append({
            "video_id": vid_id,
            "filename": f"{vid_id}.mp4",
            "path": str(out_path),
            "label": 0,
            "condition": "low_light",
            "description": f"Low-light authentic sample #{i+1} (mean lum < 25, bonafide speech)",
            "expected": {
                "video_classifier": 0,
                "rppg": None,              # Severe sensor noise / guardrail
                "syncnet": None,
                "aasist": 0,               # Clean acoustic discrimination
                "fusion": 0
            }
        })

    # 8 Low-Light Synthetic
    for i in range(8):
        vid_id = f"lowlight_synth_{i+1:02d}"
        out_path = VIDEOS_DIR / f"{vid_id}.mp4"
        v_src = str(fake_video_files[(25 + i) % len(fake_video_files)])
        a_src = str(spoof_audios[(i) % len(spoof_audios)])
        
        tmp_dark = tempfile.mktemp(suffix=".mp4")
        create_dark_video(v_src, tmp_dark, factor=0.10)
        mux_video_audio(ffmpeg_bin, tmp_dark, a_src, str(out_path), duration=3.5)
        if os.path.exists(tmp_dark):
            os.remove(tmp_dark)
            
        manifest.append({
            "video_id": vid_id,
            "filename": f"{vid_id}.mp4",
            "path": str(out_path),
            "label": 1,
            "condition": "low_light",
            "description": f"Low-light synthetic sample #{i+1} (darkened deepfake, spoof voice)",
            "expected": {
                "video_classifier": 1,
                "rppg": None,
                "syncnet": None,
                "aasist": 1,
                "fusion": 1
            }
        })

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        
    logger.info(f"Multimodal evaluation dataset generation complete!")
    logger.info(f"Total samples: {len(manifest)} ({sum(1 for m in manifest if m['label']==0)} Real, {sum(1 for m in manifest if m['label']==1)} Fake)")
    logger.info(f"Manifest written to: {MANIFEST_PATH}")


if __name__ == "__main__":
    build_dataset()
