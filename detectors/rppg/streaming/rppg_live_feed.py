"""
Task 5 driver: run the streaming rPPG detector on the same simulated live feed
as Task 3 (video file looped, or webcam index).  Same CLI style / CSV log.

  python rppg_live_feed.py --video sample.mp4 --loop
  python rppg_live_feed.py --video 0
  python rppg_live_feed.py --video sample.mp4 --no-display --max-seconds 30
"""
import argparse, csv, os, sys, time
from datetime import datetime, timezone
import cv2
try:
    from .streaming import StreamingRPPG, roi_mean_rgb
except ImportError:
    try:
        from streaming import StreamingRPPG, roi_mean_rgb
    except ImportError:
        from detectors.rppg.streaming.streaming import StreamingRPPG, roi_mean_rgb

try:
    from facenet_pytorch import MTCNN
    _mtcnn = MTCNN(keep_all=True, device="cpu"); HAS_MTCNN = True
except ImportError:
    HAS_MTCNN = False
    print("[WARN] facenet-pytorch missing: whole frame used as ROI (weak pulse signal)")

now_iso = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")

def largest_face(frame):
    if not HAS_MTCNN: return None
    boxes, _ = _mtcnn.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    if boxes is None: return None
    h, w = frame.shape[:2]
    best = max(boxes, key=lambda b: (b[2]-b[0])*(b[3]-b[1]))
    x1, y1, x2, y2 = max(0,int(best[0])), max(0,int(best[1])), min(w,int(best[2])), min(h,int(best[3]))
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None

def run(a):
    src = int(a.video) if a.video.isdigit() else a.video
    cap = cv2.VideoCapture(src)
    if not cap.isOpened(): print(f"[ERROR] cannot open {a.video}"); return
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, round(src_fps / a.fps))
    det = StreamingRPPG(fps=a.fps, window_sec=a.window_sec, min_sec=a.min_sec, hop_sec=a.hop_sec)
    fh = open(a.log, "w", newline=""); w = csv.writer(fh)
    w.writerow(["timestamp","stream_t","ready","rppg_score","hr_bpm","snr_db","buffer_sec","face"])
    read_idx = 0; t_stream = 0.0; start = time.time(); next_tick = start; last_print = -1
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                if a.loop: cap.set(cv2.CAP_PROP_POS_FRAMES, 0); continue
                break
            read_idx += 1
            if read_idx % step: continue
            if a.realtime:
                next_tick += 1.0 / a.fps; d = next_tick - time.time()
                if d > 0: time.sleep(d)
            t_stream += 1.0 / a.fps          # stream clock (use wall clock for webcam)
            if isinstance(src, int): t_stream = time.time() - start
            box = largest_face(frame)
            if HAS_MTCNN and box is None:
                det.notify_no_face(t_stream); r = det.last; face = 0
            else:
                rgb = roi_mean_rgb(frame, box); face = int(box is not None)
                r = det.push(t_stream, rgb) if rgb is not None else det.last
            if int(t_stream) != last_print:   # log once per stream second
                last_print = int(t_stream)
                f = lambda v, p=3: "" if v is None else f"{v:.{p}f}"
                w.writerow([now_iso(), f"{t_stream:.1f}", int(r.ready), f(r.score,4), f(r.hr_bpm,1), f(r.snr_db,2), f"{r.window_sec:.1f}", face]); fh.flush()
                print(f"[{now_iso()}] t={t_stream:5.1f}s ready={r.ready} score={f(r.score)} hr={f(r.hr_bpm,1)} snr={f(r.snr_db,1)} ({r.reason})")
            if not a.no_display:
                v = frame.copy()
                if box: cv2.rectangle(v, box[:2], box[2:], (0,220,0), 2)
                txt = "rPPG: warming up" if not r.ready else f"rPPG {r.score:.2f}  HR {r.hr_bpm:.0f} bpm"
                cv2.putText(v, txt, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
                cv2.imshow("AEGIS rPPG Live", v)
                if cv2.waitKey(1) & 0xFF == ord("q"): break
            if a.max_seconds and t_stream >= a.max_seconds: break
    except KeyboardInterrupt:
        pass
    finally:
        cap.release(); cv2.destroyAllWindows(); fh.close(); print(f"log saved -> {a.log}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--fps", type=float, default=10.0)
    p.add_argument("--window-sec", type=float, default=10.0)
    p.add_argument("--min-sec", type=float, default=6.0)
    p.add_argument("--hop-sec", type=float, default=1.0)
    p.add_argument("--loop", action="store_true")
    p.add_argument("--no-display", action="store_true")
    p.add_argument("--realtime", action="store_true", help="pace to wall clock (default: as fast as possible for files)")
    p.add_argument("--max-seconds", type=float, default=0)
    p.add_argument("--log", default="live_rppg_scores.csv")
    run(p.parse_args())
