import csv
import os
import subprocess
import sys

import pytest

from stream_validator import (
    DUPLICATE, GAP, OUT_OF_ORDER, TIMESTAMP_JUMP, TIMESTAMP_REGRESSION,
    StreamValidator, validate_manifest,
)

FPS = 30
INTERVAL = 1000 / FPS
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GENERATOR = os.path.join(REPO_ROOT, "eval", "scripts", "generate_attack_streams.py")


def run(frames, **kwargs):
    """frames: list of (sequence_number, timestamp_ms) in arrival order."""
    validator = StreamValidator(FPS, **kwargs)
    return [a for seq, ts in frames for a in validator.check(seq, ts)]


def steady(seqs):
    """Frames whose timestamps match their sequence numbers exactly."""
    return [(s, round(s * INTERVAL)) for s in seqs]


def kinds_at(anomalies, position):
    return {a.kind for a in anomalies if a.position == position}


def test_clean_stream_has_no_anomalies():
    assert run(steady(range(300))) == []


def test_jitter_within_tolerance_is_accepted():
    frames = [(0, 0), (1, 40), (2, 62), (3, 100), (4, 130)]
    assert run(frames) == []


def test_gap_is_flagged():
    anomalies = run(steady([0, 1, 2, 7, 8]))
    assert GAP in kinds_at(anomalies, 3)
    assert {a.position for a in anomalies} == {3}


def test_duplicate_is_flagged():
    anomalies = run(steady([0, 1, 2, 3]) + [(1, 133)])
    assert kinds_at(anomalies, 4) == {DUPLICATE}


def test_duplicate_with_replayed_timestamp_also_flags_regression():
    anomalies = run(steady([0, 1, 2, 3, 1]))
    assert kinds_at(anomalies, 4) == {DUPLICATE, TIMESTAMP_REGRESSION}


def test_out_of_order_is_flagged():
    anomalies = run([(0, 0), (1, 33), (3, 67), (2, 100), (4, 133)])
    assert kinds_at(anomalies, 2) == {GAP}
    assert kinds_at(anomalies, 3) == {OUT_OF_ORDER}


def test_resuming_after_reordered_block_is_not_a_gap():
    # 2 and 3 arrive swapped; when 4 arrives every number before it has been seen.
    anomalies = run([(0, 0), (1, 33), (3, 67), (2, 100), (4, 133)])
    assert kinds_at(anomalies, 4) == set()


def test_timestamp_regression_with_continuous_sequence():
    anomalies = run([(0, 0), (1, 33), (2, 20), (3, 53)])
    assert kinds_at(anomalies, 2) == {TIMESTAMP_REGRESSION}


def test_frozen_timestamp_is_a_regression():
    anomalies = run([(0, 0), (1, 33), (2, 33)])
    assert kinds_at(anomalies, 2) == {TIMESTAMP_REGRESSION}


def test_timestamp_jump_with_continuous_sequence():
    anomalies = run([(0, 0), (1, 33), (2, 500), (3, 533)])
    assert kinds_at(anomalies, 2) == {TIMESTAMP_JUMP}


def test_replay_older_than_window_is_still_flagged():
    anomalies = run(steady(range(10)) + steady([2]), window=3)
    assert kinds_at(anomalies, 10) == {OUT_OF_ORDER, TIMESTAMP_REGRESSION}


def test_memory_is_bounded_by_window():
    validator = StreamValidator(FPS, window=50)
    for seq, ts in steady(range(1000)):
        validator.check(seq, ts)
    assert len(validator._recent_set) == 50


@pytest.mark.parametrize("kwargs", [
    {"fps": 0}, {"fps": 30, "timestamp_tolerance": 0}, {"fps": 30, "timestamp_tolerance": 1},
    {"fps": 30, "window": 0},
])
def test_invalid_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        StreamValidator(**kwargs)


# Integration: the tampered streams from eval/scripts/generate_attack_streams.py.

@pytest.fixture(scope="module")
def attack_streams(tmp_path_factory):
    pytest.importorskip("cv2", reason="generating tampered streams requires opencv")
    out = tmp_path_factory.mktemp("tampered_streams")
    subprocess.run([sys.executable, GENERATOR, "--output-dir", str(out), "--fps", str(FPS)],
                   check=True, stdout=subprocess.DEVNULL)
    with open(out / "index.csv", newline="") as f:
        return out, {row["scenario"]: row for row in csv.DictReader(f)}


def validate_scenario(attack_streams, name):
    out, index = attack_streams
    return validate_manifest(out / index[name]["manifest_path"], FPS), index[name]


def test_clean_stream_passes(attack_streams):
    anomalies, _ = validate_scenario(attack_streams, "clean")
    assert anomalies == []


@pytest.mark.parametrize("name", ["splice_carried", "replay_carried", "reorder_carried"])
def test_carried_attacks_are_detected_at_the_tampered_segment(attack_streams, name):
    anomalies, row = validate_scenario(attack_streams, name)
    start, length = int(row["segment_start"]), int(row["segment_length"])

    assert anomalies, f"{name} was not detected"
    assert anomalies[0].position == int(row["first_tampered_position"])
    # Alerts stay on the tampered segment, plus the first frame after it,
    # where the stream visibly resumes from a different point.
    assert all(start <= a.position <= start + length for a in anomalies)


@pytest.mark.parametrize("name", ["splice_forged", "replay_forged", "reorder_forged"])
def test_forged_metadata_is_not_detectable_from_metadata_alone(attack_streams, name):
    """Known limitation, not a bug: these need content checks (hash chaining)."""
    anomalies, _ = validate_scenario(attack_streams, name)
    assert anomalies == []
