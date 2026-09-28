# Stream integrity: timestamp and sequence validation

Implements SR-03 (`shared/threat_model/THREAT_MODEL_full.md`): checks the sequence number and timestamp every live frame carries, and flags dropped, injected, replayed or reordered frames.

It checks one frame at a time as frames arrive, so it works on a live feed, not just on finished files. Create one `StreamValidator` per camera:

```python
from stream_validator import StreamValidator

validator = StreamValidator(fps=30)
for frame in feed:
    for anomaly in validator.check(frame.sequence_number, frame.timestamp_ms):
        ...  # raise an alert; the feed's integrity can no longer be established
```

**Any anomaly means integrity is unknown.** Per the project's verdict rules, a feed with anomalies must never be reported as authentic.

## Anomalies

| Kind | Meaning | Typical attack |
| :--- | :--- | :--- |
| `gap` | Sequence skipped forward past numbers never received | Injected frames, or dropped frames |
| `duplicate` | Sequence number already received | Replay |
| `out_of_order` | Sequence went backwards to a number not yet received | Reordering; the end of a spliced segment |
| `timestamp_regression` | Timestamp went backwards or stood still | Replay, reordering, splice from an older recording |
| `timestamp_jump` | Time since the previous frame is far from 1/fps | Splice from another clock, dropped frames |

Each `Anomaly` has `position` (frame index in arrival order), `kind`, `sequence_number`, `timestamp_ms` and a readable `detail`. Use `dataclasses.asdict()` to get JSON for alerting.

## Settings

| Setting | Default | Effect |
| :--- | :--- | :--- |
| `fps` | required | The camera's nominal frame rate. Sets the expected gap between timestamps. |
| `timestamp_tolerance` | `0.5` | Allowed deviation from that gap, as a fraction (0.5 = ±50%). Too tight flags normal network jitter; too loose misses small timestamp tampering. |
| `window` | `10000` | How many recent sequence numbers are remembered to detect duplicates (~5.5 min at 30 fps). Keeps memory bounded on feeds that run for days. A replay older than the window is still caught, as `out_of_order` plus `timestamp_regression`. |

## Command line

Validate a manifest from `eval/scripts/generate_attack_streams.py`:

```bash
python security/stream_integrity/stream_validator.py eval/fixtures/tampered_streams/replay_carried/manifest.csv --fps 30
python security/stream_integrity/stream_validator.py <manifest.csv> --fps 30 --json   # one JSON object per anomaly
```

Exits `0` if the stream is intact, `1` if any anomaly was found.

## Known limitations

- **Forged metadata passes.** An attacker who rewrites sequence numbers and timestamps to look continuous (the `*_forged` streams) is invisible to this check. The frame content changed but the headers look normal, so content checks such as frame hash-chaining are needed alongside this. The tests assert this on purpose.
- **Replaying a whole old recording passes.** If an attacker replays an old recording from the start of a session with its original, internally consistent metadata, nothing within the stream looks wrong. Catching this needs a freshness check that compares frame timestamps to the receiver's clock, which requires trusted time sync with the camera (transport-security work).
- **No counter wraparound.** Real RTP sequence numbers are 16-bit and wrap from 65535 to 0; that would currently be reported as `out_of_order`.
- **Alerts are not yet sent to Wazuh.** That's the SIEM alerting task.

## Tests

```bash
cd security/stream_integrity && pip install -r requirements.txt && pytest tests/ -v
```

Unit tests cover each anomaly type with hand-made sequences. Integration tests generate the tampered streams from `eval/scripts/generate_attack_streams.py`, and check that the clean stream passes, every `carried` attack is flagged starting at its first tampered frame, and every `forged` attack passes. These are skipped if OpenCV isn't installed.
