"""Timestamp and sequence-number validation for live camera feeds (SR-03).

Checks the sequence_number and timestamp_ms each frame carries, one frame at a
time as frames arrive, and reports anomalies that indicate dropped, injected,
replayed or reordered frames. Any anomaly means the feed's integrity cannot be
established; callers must never turn that into an "authentic" verdict.

This only inspects frame metadata. An attacker who rewrites sequence numbers
and timestamps to look continuous ("forged" streams in
eval/scripts/generate_attack_streams.py) passes these checks by design; content
checks such as frame hash-chaining are needed to catch that.

Usage:
    validator = StreamValidator(fps=30)
    for frame in feed:
        for anomaly in validator.check(frame.sequence_number, frame.timestamp_ms):
            raise_alert(anomaly)

    python stream_validator.py eval/fixtures/tampered_streams/replay_carried/manifest.csv --fps 30
"""
import argparse
import csv
import json
import sys
from collections import deque
from dataclasses import asdict, dataclass

GAP = "gap"
DUPLICATE = "duplicate"
OUT_OF_ORDER = "out_of_order"
TIMESTAMP_REGRESSION = "timestamp_regression"
TIMESTAMP_JUMP = "timestamp_jump"


@dataclass(frozen=True)
class Anomaly:
    position: int
    kind: str
    sequence_number: int
    timestamp_ms: int
    detail: str


class StreamValidator:
    """Stateful per-stream validator; create one per camera feed.

    fps: the camera's nominal frame rate, used for the expected frame interval.
    timestamp_tolerance: allowed deviation from the expected interval, as a
        fraction of it (0.5 = 50%), to absorb capture and network jitter.
    window: how many recent sequence numbers are remembered for duplicate
        detection. Bounds memory on long-running feeds; a replay of frames
        older than this is still flagged by the ordering and timestamp checks.
    """

    def __init__(self, fps, timestamp_tolerance=0.5, window=10_000):
        if fps <= 0:
            raise ValueError("fps must be positive")
        if not 0 < timestamp_tolerance < 1:
            raise ValueError("timestamp_tolerance must be between 0 and 1")
        if window < 1:
            raise ValueError("window must be at least 1")
        self.expected_interval_ms = 1000.0 / fps
        self.timestamp_tolerance = timestamp_tolerance
        self.window = window
        self._position = 0
        self._prev_seq = None
        self._prev_ts = None
        self._recent = deque()
        self._recent_set = set()

    def check(self, sequence_number, timestamp_ms):
        """Validates the next frame in arrival order; returns its anomalies."""
        seq, ts, pos = int(sequence_number), int(timestamp_ms), self._position
        anomalies = []

        def flag(kind, detail):
            anomalies.append(Anomaly(pos, kind, seq, ts, detail))

        if self._prev_seq is not None:
            if seq in self._recent_set:
                flag(DUPLICATE, f"sequence {seq} already received")
            elif seq < self._prev_seq + 1:
                flag(OUT_OF_ORDER, f"sequence {seq} arrived after {self._prev_seq}")
            elif seq > self._prev_seq + 1 and self._has_unseen_between(self._prev_seq, seq):
                flag(GAP, f"sequence jumped from {self._prev_seq} to {seq}")

            delta = ts - self._prev_ts
            low = self.expected_interval_ms * (1 - self.timestamp_tolerance)
            high = self.expected_interval_ms * (1 + self.timestamp_tolerance)
            if delta <= 0:
                flag(TIMESTAMP_REGRESSION, f"timestamp moved {delta} ms since previous frame")
            elif not low <= delta <= high:
                flag(TIMESTAMP_JUMP,
                     f"{delta} ms since previous frame, expected ~{self.expected_interval_ms:.1f} ms")

        self._remember(seq)
        self._prev_seq, self._prev_ts = seq, ts
        self._position += 1
        return anomalies

    def _has_unseen_between(self, low, high):
        # After a reordered block is delivered, the stream resumes past numbers
        # that already arrived; that is not a gap. Anything wider than the
        # window cannot have been fully seen, so the scan is bounded.
        if high - low - 1 > self.window:
            return True
        return any(s not in self._recent_set for s in range(low + 1, high))

    def _remember(self, seq):
        if seq in self._recent_set:
            return
        self._recent.append(seq)
        self._recent_set.add(seq)
        if len(self._recent) > self.window:
            self._recent_set.discard(self._recent.popleft())


def validate_manifest(path, fps, **validator_kwargs):
    """Runs a StreamValidator over a manifest.csv from generate_attack_streams.py,
    in row order (the order frames arrived)."""
    validator = StreamValidator(fps, **validator_kwargs)
    anomalies = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            anomalies.extend(validator.check(row["sequence_number"], row["timestamp_ms"]))
    return anomalies


def main():
    parser = argparse.ArgumentParser(description="Validate a stream manifest's sequence numbers and timestamps.")
    parser.add_argument("manifest", help="manifest.csv with sequence_number and timestamp_ms columns")
    parser.add_argument("--fps", type=float, required=True, help="Camera's nominal frame rate")
    parser.add_argument("--tolerance", type=float, default=0.5)
    parser.add_argument("--json", action="store_true", help="Print anomalies as JSON lines")
    args = parser.parse_args()

    anomalies = validate_manifest(args.manifest, args.fps, timestamp_tolerance=args.tolerance)
    for a in anomalies:
        print(json.dumps(asdict(a)) if args.json else f"frame {a.position:>5}  {a.kind:<21} {a.detail}")
    if not args.json:
        print("INTEGRITY OK" if not anomalies else f"INTEGRITY COMPROMISED: {len(anomalies)} anomalies")
    sys.exit(1 if anomalies else 0)


if __name__ == "__main__":
    main()
