"""Generates deliberately tricky edge-case media fixtures for AEGIS detector validation:
1. silent_video.mp4: Valid face video with no audio track.
2. short_clip.mp4: Video under 2 seconds (0.8s, 24 frames at 30fps).
3. occluded_face.mp4: Video where the face/mouth region is heavily blocked by an occluding box.
4. poorly_lit.mp4: Video with severe underexposure/dark lighting (mean pixel value < 10).
5. clean_baseline.mp4: Clean 3-second video with sinusoidal skin oscillation for baseline comparison.
"""
import os
import cv2
import numpy as np

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "edge_cases")


def create_fixtures():
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    width, height = 320, 240
    fps = 30.0
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    # 1. Clean Baseline (3 seconds, 90 frames, face with slight pulse oscillation)
    clean_path = os.path.join(FIXTURES_DIR, "clean_baseline.mp4")
    out = cv2.VideoWriter(clean_path, fourcc, fps, (width, height))
    for i in range(90):
        frame = np.full((height, width, 3), 200, dtype=np.uint8)
        osc = int(5 * np.sin(2 * np.pi * 1.2 * i / fps))
        # Draw face circle (skin tone)
        cv2.circle(frame, (width // 2, height // 2), 60, (110 + osc, 145 + osc, 190 + osc), -1)
        # Draw eyes and mouth
        cv2.circle(frame, (width // 2 - 20, height // 2 - 15), 6, (40, 40, 40), -1)
        cv2.circle(frame, (width // 2 + 20, height // 2 - 15), 6, (40, 40, 40), -1)
        cv2.ellipse(frame, (width // 2, height // 2 + 25), (18, 8), 0, 0, 180, (50, 50, 150), -1)
        out.write(frame)
    out.release()
    print(f"Generated clean baseline: {clean_path}")

    # 2. Silent Video (3 seconds, exactly same visual as clean, no audio)
    silent_path = os.path.join(FIXTURES_DIR, "silent_video.mp4")
    out = cv2.VideoWriter(silent_path, fourcc, fps, (width, height))
    for i in range(90):
        frame = np.full((height, width, 3), 200, dtype=np.uint8)
        osc = int(5 * np.sin(2 * np.pi * 1.2 * i / fps))
        cv2.circle(frame, (width // 2, height // 2), 60, (110 + osc, 145 + osc, 190 + osc), -1)
        cv2.circle(frame, (width // 2 - 20, height // 2 - 15), 6, (40, 40, 40), -1)
        cv2.circle(frame, (width // 2 + 20, height // 2 - 15), 6, (40, 40, 40), -1)
        cv2.ellipse(frame, (width // 2, height // 2 + 25), (18, 8), 0, 0, 180, (50, 50, 150), -1)
        out.write(frame)
    out.release()
    print(f"Generated silent video: {silent_path}")

    # 3. Short Clip (< 2 seconds, 24 frames = 0.8s)
    short_path = os.path.join(FIXTURES_DIR, "short_clip.mp4")
    out = cv2.VideoWriter(short_path, fourcc, fps, (width, height))
    for i in range(24):
        frame = np.full((height, width, 3), 200, dtype=np.uint8)
        cv2.circle(frame, (width // 2, height // 2), 60, (110, 145, 190), -1)
        out.write(frame)
    out.release()
    print(f"Generated short clip (<2s): {short_path}")

    # 4. Occluded Face (face circle with a large black mask covering the lower 70% of the face)
    occluded_path = os.path.join(FIXTURES_DIR, "occluded_face.mp4")
    out = cv2.VideoWriter(occluded_path, fourcc, fps, (width, height))
    for i in range(90):
        frame = np.full((height, width, 3), 200, dtype=np.uint8)
        # Face circle
        cv2.circle(frame, (width // 2, height // 2), 60, (110, 145, 190), -1)
        # Heavy black mask/occlusion over the mouth & lower face
        cv2.rectangle(
            frame,
            (width // 2 - 50, height // 2 - 5),
            (width // 2 + 50, height // 2 + 60),
            (10, 10, 10),
            -1,
        )
        out.write(frame)
    out.release()
    print(f"Generated occluded face clip: {occluded_path}")

    # 5. Poorly Lit Video (severely dark / underexposed, pixel intensity < 8)
    dark_path = os.path.join(FIXTURES_DIR, "poorly_lit.mp4")
    out = cv2.VideoWriter(dark_path, fourcc, fps, (width, height))
    for i in range(90):
        frame = np.full((height, width, 3), 5, dtype=np.uint8)
        # Barely visible dark circle
        cv2.circle(frame, (width // 2, height // 2), 60, (8, 9, 10), -1)
        out.write(frame)
    out.release()
    print(f"Generated poorly lit clip: {dark_path}")

    return {
        "clean": clean_path,
        "silent": silent_path,
        "short": short_path,
        "occluded": occluded_path,
        "poorly_lit": dark_path,
    }


if __name__ == "__main__":
    create_fixtures()
