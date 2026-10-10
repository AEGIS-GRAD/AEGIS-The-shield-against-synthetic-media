"""Generates labeled tampered-stream fixtures for live-feed integrity evaluation.

Produces one clean reference stream plus tampered variants of it, covering the
SR-03 attack categories in shared/threat_model/THREAT_MODEL_full.md:

  splice   frames from a different source replace a segment (feed injection)
  replay   earlier footage from the same stream is resent in place of live frames
  reorder  two adjacent blocks of frames are delivered swapped

Each category has two metadata modes:

  carried  tampered frames keep the sequence_number/timestamp_ms they were
           captured with, so gaps, duplicates and out-of-order values appear
  forged   the attacker rewrites sequence_number/timestamp_ms to look continuous,
           so only content-level checks (e.g. hash chaining) can catch it

Output (under --output-dir, default eval/fixtures/tampered_streams/):

  index.csv               one row per scenario
  <scenario>/stream.mkv   FFV1 lossless video; decoded frames are byte-exact
  <scenario>/manifest.csv one row per frame, ground truth for that stream

Streams are lossless on purpose: hash-based checks compare decoded frame bytes,
and a lossy codec would make every frame of every stream differ from the
reference, not just the tampered ones. See eval/README.md for the schema.
"""
import argparse
import csv
import os
import shutil

import cv2
import numpy as np

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OUTPUT_DIR = os.path.join(REPO_ROOT, "eval", "fixtures", "tampered_streams")

FOURCC = cv2.VideoWriter_fourcc(*"FFV1")
WIDTH, HEIGHT = 320, 240

# Stream A is the "live" camera. Stream B is a different camera recorded a day
# earlier, with its own sequence counter.
A_SEQ_BASE, A_TS_BASE_MS = 0, 1_790_000_000_000
B_SEQ_BASE, B_TS_BASE_MS = 500_000, A_TS_BASE_MS - 86_400_000

MANIFEST_FIELDS = [
    "position", "sequence_number", "timestamp_ms",
    "is_tampered", "tamper_type", "source_ref",
]
INDEX_FIELDS = [
    "scenario", "tamper_type", "metadata_mode", "stream_path", "manifest_path",
    "reference_stream_path", "num_frames", "num_tampered",
    "first_tampered_position", "segment_start", "segment_length", "description",
]


def synthesize_frames(n, fps, background, seed, prnu_seed=None):
    """Camera-like scene with a moving subject, burned-in counter, and persistent
    PRNU sensor pattern + temporal sensor noise.
    
    If prnu_seed is specified, a persistent PRNU noise matrix unique to this physical sensor
    is generated and blended into every frame."""
    rng = np.random.default_rng(seed)
    
    # Generate persistent hardware PRNU sensor fingerprint
    effective_prnu_seed = prnu_seed if prnu_seed is not None else seed
    prnu_rng = np.random.default_rng(effective_prnu_seed)
    persistent_prnu = prnu_rng.normal(0, 3.5, (HEIGHT, WIDTH, 3)).astype(np.float32)

    frames = []
    for i in range(n):
        frame = np.full((HEIGHT, WIDTH, 3), background, dtype=np.uint8)
        cv2.rectangle(frame, (0, HEIGHT - 60), (WIDTH, HEIGHT), (60, 60, 60), -1)
        x = int(40 + (WIDTH - 80) * (0.5 + 0.5 * np.sin(2 * np.pi * i / (fps * 4))))
        cv2.circle(frame, (x, HEIGHT // 2), 28, (110, 145, 190), -1)
        cv2.putText(frame, f"{i:05d}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 1, cv2.LINE_AA)
        
        # Temporal thermal noise per frame
        thermal_noise = rng.integers(-2, 3, frame.shape, dtype=np.int16)
        
        # Superimpose physical sensor PRNU fingerprint and thermal noise
        noisy_frame = frame.astype(np.float32) + persistent_prnu + thermal_noise
        frames.append(np.clip(noisy_frame, 0, 255).astype(np.uint8))
    return frames


def read_frames(path, max_frames):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = []
    while len(frames) < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(cv2.resize(frame, (WIDTH, HEIGHT)))
    cap.release()
    return frames, fps


def capture_meta(source, index, fps):
    """The sequence_number/timestamp_ms a frame carried when it was captured."""
    seq_base, ts_base = (A_SEQ_BASE, A_TS_BASE_MS) if source in ("A", "C") else (B_SEQ_BASE, B_TS_BASE_MS)
    return seq_base + index, ts_base + round(index * 1000 / fps)


def build_scenario(tamper_type, mode, n, start, length, fps):
    """Returns the per-position (source, source_index) list and the metadata
    each position carries."""
    refs = [("A", i) for i in range(n)]
    seg = range(start, start + length)

    if tamper_type == "splice":
        for j, pos in enumerate(seg):
            refs[pos] = ("B", j)
    elif tamper_type == "prnu_splice":
        # Spliced segment from Camera C: visually identical scene, but physically different sensor
        for pos in seg:
            refs[pos] = ("C", pos)
    elif tamper_type == "replay":
        replay_from = start - length
        for j, pos in enumerate(seg):
            refs[pos] = ("A", replay_from + j)
    elif tamper_type == "reorder":
        half = length // 2
        swapped = list(range(start + half, start + length)) + list(range(start, start + half))
        for pos, src in zip(seg, swapped):
            refs[pos] = ("A", src)
    elif tamper_type == "auth_bypass":
        # Device credentials attack: stream frames remain unmanipulated visually,
        # but connection attempts use invalid, expired, or forged client credentials
        refs = [("A", i) for i in range(n)]

    meta = []
    for pos, (src, idx) in enumerate(refs):
        if mode == "forged" or mode == "invalid_credentials":
            meta.append(capture_meta("A", pos, fps))
        else:
            meta.append(capture_meta(src, idx, fps))
    return refs, meta


def write_stream(path, frames, fps):
    writer = cv2.VideoWriter(path, FOURCC, fps, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV cannot write FFV1 video to {path}")
    for frame in frames:
        writer.write(frame)
    writer.release()


DESCRIPTIONS = {
    ("none", "none"): "Untampered reference stream.",
    ("splice", "carried"): "Segment replaced by another camera's footage; injected frames keep that camera's sequence numbers and day-old timestamps.",
    ("splice", "forged"): "Segment replaced by another camera's footage; sequence numbers and timestamps rewritten to look continuous.",
    ("replay", "carried"): "Segment replaced by earlier footage from the same stream; replayed frames keep their original (duplicate, backwards) metadata.",
    ("replay", "forged"): "Segment replaced by earlier footage from the same stream; metadata rewritten to look continuous.",
    ("reorder", "carried"): "Two adjacent blocks delivered swapped; frames keep original metadata, so values arrive out of order.",
    ("reorder", "forged"): "Two adjacent blocks delivered swapped; metadata rewritten to look in-order.",
    ("prnu_splice", "forged"): "Spliced segment from visually identical scene captured on a physically different camera sensor (tests PRNU hardware fingerprint detection).",
    ("auth_bypass", "invalid_credentials"): "Connection attempt using invalid, untrusted, or forged device credentials to test mTLS authentication layer.",
}


def generate(output_dir, source, splice_source, num_frames, fps, seed):
    if source:
        frames_a, fps = read_frames(source, num_frames)
    else:
        # Camera A: Primary camera with enrolled PRNU sensor seed 1001
        frames_a = synthesize_frames(num_frames, fps, (170, 185, 175), seed=seed, prnu_seed=1001)
    n = len(frames_a)

    # Segment sits in the middle third; replay needs `length` frames before it.
    length = max(2, (n // 6) // 2 * 2)
    start = n // 3
    if start < length or start + length > n:
        raise ValueError(f"Source too short for tampering segments: {n} frames")

    if splice_source:
        frames_b, _ = read_frames(splice_source, length)
        if len(frames_b) < length:
            raise ValueError(f"Splice source needs >= {length} frames, got {len(frames_b)}")
    else:
        # Camera B: Dissimilar camera source with distinct background and sensor
        frames_b = synthesize_frames(length, fps, (95, 110, 140), seed=seed + 1, prnu_seed=2002)

    # Camera C: Visually similar / identical scene to Camera A, but captured by a physically different sensor
    # (used for testing PRNU hardware fingerprint extraction)
    frames_c = synthesize_frames(num_frames, fps, (170, 185, 175), seed=seed, prnu_seed=9999)

    pools = {"A": frames_a, "B": frames_b, "C": frames_c}
    os.makedirs(output_dir, exist_ok=True)
    reference_path = os.path.join(output_dir, "clean", "stream.mkv")

    scenarios = [("clean", "none", "none")] + [
        (f"{t}_{m}", t, m)
        for t in ("splice", "replay", "reorder")
        for m in ("carried", "forged")
    ] + [
        ("prnu_splice", "prnu_splice", "forged"),
        ("auth_bypass", "auth_bypass", "invalid_credentials"),
    ]

    index_rows = []
    for name, tamper_type, mode in scenarios:
        scenario_dir = os.path.join(output_dir, name)
        os.makedirs(scenario_dir, exist_ok=True)

        if tamper_type == "none":
            refs = [("A", i) for i in range(n)]
            meta = [capture_meta("A", i, fps) for i in range(n)]
        else:
            refs, meta = build_scenario(tamper_type, mode, n, start, length, fps)

        stream_path = os.path.join(scenario_dir, "stream.mkv")
        write_stream(stream_path, [pools[src][idx] for src, idx in refs], fps)

        rows = []
        for pos, ((src, idx), (seq, ts)) in enumerate(zip(refs, meta)):
            if tamper_type == "auth_bypass":
                tampered = True
            else:
                tampered = (src, idx) != ("A", pos)
            rows.append({
                "position": pos,
                "sequence_number": seq,
                "timestamp_ms": ts,
                "is_tampered": tampered,
                "tamper_type": tamper_type if tampered else "none",
                "source_ref": f"{src}:{idx}",
            })

        manifest_path = os.path.join(scenario_dir, "manifest.csv")
        with open(manifest_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        tampered_positions = [r["position"] for r in rows if r["is_tampered"]]
        index_rows.append({
            "scenario": name,
            "tamper_type": tamper_type,
            "metadata_mode": mode,
            "stream_path": os.path.relpath(stream_path, output_dir),
            "manifest_path": os.path.relpath(manifest_path, output_dir),
            "reference_stream_path": os.path.relpath(reference_path, output_dir),
            "num_frames": n,
            "num_tampered": len(tampered_positions),
            "first_tampered_position": tampered_positions[0] if tampered_positions else -1,
            "segment_start": start if (tampered_positions and tamper_type != "auth_bypass") else (0 if tamper_type == "auth_bypass" else -1),
            "segment_length": length if (tampered_positions and tamper_type != "auth_bypass") else (n if tamper_type == "auth_bypass" else 0),
            "description": DESCRIPTIONS[(tamper_type, mode)],
        })
        print(f"Generated {name}: {len(tampered_positions)}/{n} tampered frames -> {stream_path}")

    index_path = os.path.join(output_dir, "index.csv")
    with open(index_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(index_rows)
    print(f"Wrote {len(index_rows)} scenarios to {index_path}")
    return index_path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--source", help="Real video to use as the live stream (default: synthetic)")
    parser.add_argument("--splice-source", help="Real video to splice in (default: synthetic)")
    parser.add_argument("--num-frames", type=int, default=150,
                        help="Frames to synthesize, or max frames read from --source")
    parser.add_argument("--fps", type=float, default=30.0, help="FPS for synthetic streams")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--clean", action="store_true", help="Remove --output-dir before generating")
    args = parser.parse_args()

    if args.clean and os.path.isdir(args.output_dir):
        shutil.rmtree(args.output_dir)
    generate(args.output_dir, args.source, args.splice_source, args.num_frames, args.fps, args.seed)


if __name__ == "__main__":
    main()
