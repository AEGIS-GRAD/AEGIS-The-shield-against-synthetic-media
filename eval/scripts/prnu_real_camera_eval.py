"""
AEGIS PRNU real-camera validation — Week 11 Task 6
==================================================

Earlier PRNU results (``security/tests/test_prnu.py``, the surveillance pen-test)
used *simulated* splices: synthetic noise patterns injected into generated
frames. This script measures whether the gateway's PRNU check actually separates
**physical cameras** on real footage.

Protocol (two phones are enough)
--------------------------------
For each camera, record with fixed settings (no digital zoom, stabilisation off,
same resolution, e.g. 1280x720 or the phones' common size):

1. ``flat``    30 s of a flat, bright, out-of-focus scene (white wall / sky) — enrolment
2. ``sceneA``  30 s of a shared scene, *both cameras filming the same thing*
3. ``sceneB``  30 s of a scene only this camera films

Then::

    python eval/scripts/prnu_real_camera_eval.py \
        --camera phoneA=footage/phoneA --camera phoneB=footage/phoneB --out eval/reports

where each folder holds ``flat.mp4``, ``sceneA.mp4``, ``sceneB.mp4`` (any of them
may be missing; a single video file per camera also works, then the first
``--enroll`` frames are used for enrolment).

The shared ``sceneA`` is the decisive test: if PCE between *different* cameras
filming the *same* scene is high, the detector is matching scene content, not
sensor noise, and its splice verdicts are not evidence of a foreign sensor.

Metrics: same-camera vs cross-camera PCE distributions, accept/reject rates at the
gateway threshold (PCE 50), ROC AUC and EER, for both the gateway's PCE (peak at
any shift, as in ``security/forensics/prnu.py``) and classic zero-shift PCE.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from security.forensics.prnu import PRNUExtractor  # noqa: E402

GATEWAY_THRESHOLD = 50.0


def read_frames(path: Path, step: int, limit: int) -> List[np.ndarray]:
    frames: List[np.ndarray] = []
    if path.is_dir():
        for p in sorted(path.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}:
                img = cv2.imread(str(p))
                if img is not None:
                    frames.append(img)
            if len(frames) >= limit:
                break
        return frames
    cap = cv2.VideoCapture(str(path))
    i = 0
    while len(frames) < limit:
        ok, f = cap.read()
        if not ok:
            break
        if i % step == 0:
            frames.append(f)
        i += 1
    cap.release()
    return frames


def center_crop(img: np.ndarray, h: int, w: int) -> np.ndarray:
    H, W = img.shape[:2]
    y, x = (H - h) // 2, (W - w) // 2
    return img[y:y + h, x:x + w]


def zero_shift_pce(residual: np.ndarray, baseline: np.ndarray, r: int = 5) -> float:
    """Classic PCE: normalised cross-correlation at zero shift vs. energy elsewhere."""
    a = residual - residual.mean()
    b = baseline - baseline.mean()
    cc = np.fft.ifft2(np.fft.fft2(a) * np.conj(np.fft.fft2(b))).real
    cc /= (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12)
    peak = cc[0, 0]
    mask = np.ones_like(cc, dtype=bool)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            mask[dy % cc.shape[0], dx % cc.shape[1]] = False
    energy = np.mean(cc[mask] ** 2)
    return float(np.sign(peak) * peak ** 2 / (energy + 1e-18))


def auc_eer(pos: List[float], neg: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if not pos or not neg:
        return None, None, None
    p, n = np.asarray(pos), np.asarray(neg)
    auc = float((p[:, None] > n[None, :]).mean() + 0.5 * (p[:, None] == n[None, :]).mean())
    thr = np.unique(np.concatenate([p, n]))
    best = (1.0, None)
    for t in thr:
        frr, far = float((p < t).mean()), float((n >= t).mean())
        if abs(frr - far) < best[0]:
            best = (abs(frr - far), ((frr + far) / 2, float(t)))
    return auc, best[1][0] if best[1] else None, best[1][1] if best[1] else None


def collect_sources(spec: str, args) -> Tuple[str, Dict[str, List[np.ndarray]]]:
    name, _, raw = spec.partition("=")
    p = Path(raw)
    clips: Dict[str, List[np.ndarray]] = {}
    if p.is_dir() and any((p / f"{c}.mp4").exists() for c in ("flat", "sceneA", "sceneB")):
        for c in ("flat", "sceneA", "sceneB"):
            if (p / f"{c}.mp4").exists():
                clips[c] = read_frames(p / f"{c}.mp4", args.step, args.max_frames)
    else:
        frames = read_frames(p, args.step, args.max_frames)
        clips["flat"], clips["test"] = frames[: args.enroll], frames[args.enroll:]
    return name, clips


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", action="append", required=True, help="NAME=PATH (video, image folder, or protocol folder)")
    ap.add_argument("--enroll", type=int, default=40)
    ap.add_argument("--step", type=int, default=3, help="use every Nth video frame")
    ap.add_argument("--max-frames", type=int, default=200)
    ap.add_argument("--size", type=int, nargs=2, default=None, metavar=("H", "W"), help="common centre crop (no resizing)")
    ap.add_argument("--level", type=int, default=2, help="DWT level (gateway uses 2)")
    ap.add_argument("--label", default="real-camera", help="short description of the footage for the report")
    ap.add_argument("--out", default=str(REPO / "eval" / "reports"))
    args = ap.parse_args()

    sources = dict(collect_sources(s, args) for s in args.camera)
    if len(sources) < 2:
        sys.exit("need at least two cameras")
    all_frames = [f for clips in sources.values() for frames in clips.values() for f in frames]
    h, w = args.size or (min(f.shape[0] for f in all_frames), min(f.shape[1] for f in all_frames))
    h, w = h - h % 8, w - w % 8
    ex = PRNUExtractor(level=args.level, wavelet="db4")

    baselines = {}
    tests: Dict[str, List[Tuple[str, np.ndarray]]] = {}
    for cam, clips in sources.items():
        enroll = clips.get("flat") or []
        baselines[cam] = ex.generate_baseline([center_crop(f, h, w) for f in enroll[: args.enroll]])
        tests[cam] = [(clip, ex.extract_noise_residual(center_crop(f, h, w)))
                      for clip, frames in clips.items() if clip != "flat" for f in frames]

    rows = []
    for probe_cam, residuals in tests.items():
        for clip, res in residuals:
            for ref_cam, base in baselines.items():
                rows.append({"probe": probe_cam, "clip": clip, "reference": ref_cam, "same": probe_cam == ref_cam,
                             "pce_gateway": ex.compute_pce(res, base), "pce_zero_shift": zero_shift_pce(res, base)})

    def summarise(key: str) -> Dict[str, object]:
        pos = [r[key] for r in rows if r["same"]]
        neg = [r[key] for r in rows if not r["same"]]
        auc, eer, eer_t = auc_eer(pos, neg)
        return {
            "same_camera_median": float(np.median(pos)) if pos else None,
            "cross_camera_median": float(np.median(neg)) if neg else None,
            "same_accept_rate_at_50": float(np.mean(np.asarray(pos) >= GATEWAY_THRESHOLD)) if pos else None,
            "foreign_accept_rate_at_50": float(np.mean(np.asarray(neg) >= GATEWAY_THRESHOLD)) if neg else None,
            "auc": auc, "eer": eer, "eer_threshold": eer_t,
        }

    summary = {"gateway_pce": summarise("pce_gateway"), "zero_shift_pce": summarise("pce_zero_shift")}
    pair = {}
    for r in rows:
        pair.setdefault((r["probe"], r["reference"]), []).append(r["pce_gateway"])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "prnu_real_camera_eval.json").write_text(json.dumps(
        {"label": args.label, "crop": [h, w], "cameras": list(sources), "summary": summary,
         "pairs": {f"{a}->{b}": float(np.median(v)) for (a, b), v in pair.items()},
         "n_rows": len(rows)}, indent=2), encoding="utf-8")

    cams = list(sources)
    matrix = "| probe \\ enrolled | " + " | ".join(cams) + " |\n|---|" + "---|" * len(cams) + "\n"
    for a in cams:
        matrix += f"| **{a}** | " + " | ".join(f"{np.median(pair[(a, b)]):.1f}" for b in cams) + " |\n"

    def fmt(v):
        return "n/a" if v is None else (f"{v:.1%}" if isinstance(v, float) and v <= 1.0 else f"{v:.1f}")

    lines = []
    for k, label in (("gateway_pce", "Gateway PCE (peak at any shift)"), ("zero_shift_pce", "Classic zero-shift PCE")):
        s = summary[k]
        lines.append(f"| {label} | {s['same_camera_median']:.1f} | {s['cross_camera_median']:.1f} | "
                     f"{fmt(s['same_accept_rate_at_50'])} | {fmt(s['foreign_accept_rate_at_50'])} | "
                     f"{s['auc']:.3f} | {fmt(s['eer'])} |")
    md = f"""# PRNU Source-Separation Evaluation — {args.label}

**Date:** {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · **Script:** `eval/scripts/prnu_real_camera_eval.py`
**Sources:** {', '.join(cams)} · **Common centre crop:** {h}x{w} (no resampling) · **Enrolment frames / source:** {args.enroll}
**Probe frames:** {len(rows) // len(cams)} · **DWT level:** {args.level} · **Gateway threshold:** PCE {GATEWAY_THRESHOLD:.0f}

| Statistic | Same-source median | Cross-source median | Same-source accepted @50 | Foreign accepted @50 | ROC AUC | EER |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
{chr(10).join(lines)}

Median gateway PCE, probe source (row) against enrolled baseline (column):

{matrix}
"""
    (out / "prnu_real_camera_eval.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
