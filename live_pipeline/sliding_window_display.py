"""
Task 3 — Live-Feed Pipeline with Face Detection + Real-Time Overlay
Reads a video (or webcam index), detects faces per frame with MTCNN,
feeds the largest face into the Week 1 sliding-window MobileNetV3 detector,
and overlays bounding boxes + rolling anomaly score on the displayed video.

Usage examples:
  python sliding_window_display.py --video sample.mp4 --loop
  python sliding_window_display.py --video 0              # live webcam
"""
import argparse
import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import cv2
import numpy as np

# ── Make the repo importable ─────────────────────────────────────────────────
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..",
                 "AEGIS-The-shield-against-synthetic-media"))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from engine.edge_model.sliding_window import SlidingWindowDetector

# ── MTCNN face detector ───────────────────────────────────────────────────────
try:
    from facenet_pytorch import MTCNN
    _mtcnn = MTCNN(keep_all=True, select_largest=False, device="cpu")
    HAS_MTCNN = True
except ImportError:
    HAS_MTCNN = False
    print("[WARN] facenet-pytorch not installed — no face boxes, full frame used")

# ── ImageNet normalisation constants ─────────────────────────────────────────
MEAN       = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD        = np.array([0.229, 0.224, 0.225], dtype=np.float32)
INPUT_SIZE = 224


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─────────────────────────────────────────────────────────────────────────────
# Face detection helpers
# ─────────────────────────────────────────────────────────────────────────────

def detect_faces(frame_bgr):
    """
    Detect faces in a BGR frame using MTCNN.

    Returns:
        boxes  : list of (x1, y1, x2, y2) ints, clipped to frame
        fprobs : list of float detection confidences (0..1)
    """
    if not HAS_MTCNN:
        return [], []

    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    try:
        raw_boxes, raw_probs = _mtcnn.detect(rgb)
    except Exception as e:
        print(f"[WARN] MTCNN error: {e}")
        return [], []

    if raw_boxes is None:
        return [], []

    h, w = frame_bgr.shape[:2]
    boxes, fprobs = [], []
    for b, p in zip(raw_boxes, raw_probs):
        x1 = max(0, int(b[0]))
        y1 = max(0, int(b[1]))
        x2 = min(w, int(b[2]))
        y2 = min(h, int(b[3]))
        if x2 > x1 and y2 > y1:
            boxes.append((x1, y1, x2, y2))
            fprobs.append(float(p))

    return boxes, fprobs


def preprocess_region(frame_bgr, box=None):
    """
    Crop the face region (or whole frame if no box), then resize to
    224×224 and apply ImageNet normalisation.

    Returns: float32 numpy array of shape (3, 224, 224)
    """
    if box is not None:
        x1, y1, x2, y2 = box
        crop = frame_bgr[y1:y2, x1:x2]
    else:
        crop = frame_bgr

    rgb     = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    rgb     = cv2.resize(rgb, (INPUT_SIZE, INPUT_SIZE),
                         interpolation=cv2.INTER_AREA)
    normed  = (rgb.astype(np.float32) / 255.0 - MEAN) / STD
    return np.transpose(normed, (2, 0, 1)).astype(np.float32)  # (3,H,W)


# ─────────────────────────────────────────────────────────────────────────────
# Overlay drawing
# ─────────────────────────────────────────────────────────────────────────────

def draw_overlay(frame, boxes, fprobs, rolling, win_score, latency_ms):
    """
    Draw face bounding boxes and HUD panel onto 'frame' (in-place copy).

    Colour scheme:
        rolling > 0.65  →  RED   (likely SYNTHETIC)
        rolling < 0.35  →  GREEN (likely AUTHENTIC)
        else            →  YELLOW (UNCERTAIN)
    """
    if rolling is not None and rolling > 0.65:
        box_color = (0, 0, 220)          # BGR red
        verdict   = "SYNTHETIC"
    elif rolling is not None and rolling < 0.35:
        box_color = (0, 220, 0)          # BGR green
        verdict   = "AUTHENTIC"
    else:
        box_color = (0, 200, 220)        # BGR yellow
        verdict   = "UNCERTAIN"

    # ── Bounding boxes ────────────────────────────────────────────────────────
    for i, (box, fp) in enumerate(zip(boxes, fprobs)):
        x1, y1, x2, y2 = box
        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
        label = f"Face {i+1}  {fp:.2f}"
        cv2.putText(frame, label, (x1, max(y1 - 6, 14)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)

    # ── HUD panel (top-left) ──────────────────────────────────────────────────
    lines = [
        f"Rolling : {rolling:.3f}" if rolling is not None else "Rolling : --",
        f"Window  : {win_score:.3f}" if win_score is not None else "Window  : --",
        f"Latency : {latency_ms:.0f} ms" if latency_ms is not None else "Latency : --",
        f"Verdict : {verdict}",
    ]
    for i, line in enumerate(lines):
        y_pos = 22 + i * 22
        cv2.rectangle(frame, (0, y_pos - 16), (260, y_pos + 6), (0, 0, 0), -1)
        cv2.putText(frame, line, (5, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    return frame


# ─────────────────────────────────────────────────────────────────────────────
# Scorer (runs in background thread)
# ─────────────────────────────────────────────────────────────────────────────

def score_window(detector, frames):
    """Score a list of preprocessed frames. Returns (score, latency_ms)."""
    t0    = time.time()
    score = detector.predict_window(frames)
    return score, (time.time() - t0) * 1000.0


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

def run(args):
    # ── Open video source ─────────────────────────────────────────────────────
    src = int(args.video) if args.video.isdigit() else args.video
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open source: {args.video}")
        return

    # ── Build detector ────────────────────────────────────────────────────────
    detector = SlidingWindowDetector(
        backend=args.backend,
        window_size=args.window_size,
        stride=args.stride,
        device=args.device,
    )

    src_fps          = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step             = max(1, round(src_fps / args.fps))   # keep 1-in-N frames
    window_budget_ms = (1000.0 / args.fps) * args.stride   # ms per window slot

    # ── State ─────────────────────────────────────────────────────────────────
    buffer      = []          # raw preprocessed frames accumulating
    executor    = ThreadPoolExecutor(max_workers=1)
    pending     = None        # Future from the background scorer
    rolling     = None        # EMA score
    last_win    = None        # last window score (for display while waiting)
    last_lat    = None        # last latency (ms)
    last_boxes  = []          # carry forward boxes between frames
    last_fprobs = []
    read_idx    = 0           # every frame read
    kept_idx    = 0           # frames kept after decimation
    next_tick   = time.time()

    # ── CSV log ───────────────────────────────────────────────────────────────
    log_fh  = open(args.log, "w", newline="")
    log_csv = csv.writer(log_fh)
    log_csv.writerow(["timestamp", "window_score", "rolling_score",
                      "latency_ms", "faces_detected"])

    print(f"[{now_iso()}] Pipeline started | "
          f"backend={args.backend} window={args.window_size} "
          f"stride={args.stride} fps={args.fps}")

    # ── Callback: collect scoring result from background thread ───────────────
    def collect(future):
        nonlocal rolling, last_win, last_lat
        try:
            score, ms = future.result()
        except Exception as e:
            print(f"[{now_iso()}] WARN scorer: {e}")
            return
        last_win = score
        last_lat = ms
        rolling  = score if rolling is None else (
            args.alpha * score + (1.0 - args.alpha) * rolling)
        n = len(last_boxes)
        print(f"[{now_iso()}] window={score:.3f}  rolling={rolling:.3f}  "
              f"({ms:.0f} ms)  faces={n}")
        log_csv.writerow([now_iso(), f"{score:.4f}", f"{rolling:.4f}",
                          f"{ms:.0f}", n])
        log_fh.flush()
        if ms > window_budget_ms:
            print(f"[{now_iso()}] WARN latency {ms:.0f} ms > "
                  f"budget {window_budget_ms:.0f} ms")

    # ── Main read loop ────────────────────────────────────────────────────────
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                if args.loop:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                print(f"[{now_iso()}] Stream ended.")
                break

            read_idx += 1
            if read_idx % step:         # skip frames to hit target fps
                continue
            kept_idx += 1

            # pace to real-time
            next_tick += 1.0 / args.fps
            delay = next_tick - time.time()
            if delay > 0:
                time.sleep(delay)

            # ── Detect faces this frame ───────────────────────────────────────
            boxes, fprobs = detect_faces(frame)
            if boxes:                   # carry forward if faces found
                last_boxes  = boxes
                last_fprobs = fprobs

            # ── Preprocess: face crop or whole frame ──────────────────────────
            primary_box   = boxes[0] if boxes else None
            preprocessed  = preprocess_region(frame, box=primary_box)

            # ── Collect completed future ──────────────────────────────────────
            if pending is not None and pending.done():
                collect(pending)
                pending = None

            # ── Push to buffer (Week 1 sliding window) ────────────────────────
            buffer.append(preprocessed)
            if len(buffer) >= args.window_size:
                window_frames = buffer[: args.window_size]
                buffer        = buffer[args.stride :]
                if pending is None:
                    pending = executor.submit(score_window, detector,
                                              window_frames)
                else:
                    print(f"[{now_iso()}] Scorer busy — window skipped")
            else:
                # still filling — print progress every second
                if kept_idx % args.fps == 0:
                    print(f"[{now_iso()}] Filling buffer: "
                          f"{len(buffer)}/{args.window_size}")

            # ── Draw overlay & display ────────────────────────────────────────
            display_frame = draw_overlay(
                frame.copy(),
                last_boxes, last_fprobs,
                rolling, last_win, last_lat)

            cv2.imshow("AEGIS Live Feed", display_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                print(f"[{now_iso()}] Quit by user.")
                break

        # flush last pending result
        if pending is not None:
            collect(pending)

    except KeyboardInterrupt:
        print(f"\n[{now_iso()}] Stopped by Ctrl+C.")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        executor.shutdown(wait=False)
        log_fh.close()
        print(f"[{now_iso()}] Log saved → {args.log}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="AEGIS Task 3 — Live deepfake detection with face overlay")
    p.add_argument("--video",       required=True,
                   help="Path to .mp4/.avi  OR  webcam index (e.g. 0)")
    p.add_argument("--backend",     default="onnx_int8",
                   choices=["pytorch", "onnx_fp32", "onnx_int8"])
    p.add_argument("--device",      default="cpu", choices=["cpu", "cuda"])
    p.add_argument("--fps",         type=int,   default=10,
                   help="Target processing fps (default 10)")
    p.add_argument("--window-size", type=int,   default=16,
                   help="Sliding window length in frames (Week 1 default 16)")
    p.add_argument("--stride",      type=int,   default=8,
                   help="Stride between windows (Week 1 default 8)")
    p.add_argument("--alpha",       type=float, default=0.6,
                   help="EMA smoothing factor (0=frozen, 1=no smoothing)")
    p.add_argument("--loop",        action="store_true",
                   help="Loop video file to simulate infinite stream")
    p.add_argument("--log",         default="live_scores_display.csv")
    run(p.parse_args())
