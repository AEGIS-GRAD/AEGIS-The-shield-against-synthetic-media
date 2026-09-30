This folder is dedicated to the evaluation and benchmarking of the AEGIS system. It contains scripts for running automated benchmarks and Jupyter notebooks for detailed evaluation analysis. Additionally, it holds documentation related to the datasets used for testing and training. It also serves as the centralized location for tracking results and performance metrics over time.

## Tampered-stream fixtures (live-feed integrity)

`scripts/generate_attack_streams.py` produces labeled tampered streams for evaluating feed-integrity checks (frame hash-chaining, timestamp/sequence validation) against the SR-03 attack categories in `shared/threat_model/THREAT_MODEL_full.md`.

```bash
pip install opencv-python-headless numpy
python eval/scripts/generate_attack_streams.py            # synthetic source, 150 frames @ 30fps
python eval/scripts/generate_attack_streams.py --source real.mp4 --splice-source other.mp4 --clean
```

Output goes to `eval/fixtures/tampered_streams/` (gitignored — regenerate, don't commit):

| Scenario | What the attacker did | Metadata |
| :--- | :--- | :--- |
| `clean` | Nothing — reference stream | continuous |
| `splice_carried` / `splice_forged` | Replaced a segment with another camera's footage | kept / rewritten |
| `replay_carried` / `replay_forged` | Replaced a segment with earlier footage from the same stream | kept / rewritten |
| `reorder_carried` / `reorder_forged` | Swapped two adjacent blocks of frames | kept / rewritten |

In `carried` mode, tampered frames keep the `sequence_number`/`timestamp_ms` they were captured with, so gaps, duplicates and out-of-order values appear. In `forged` mode the attacker rewrites them to look continuous, and only content-level checks (hash chaining) can detect the attack.

Each `<scenario>/` holds `stream.mkv` (FFV1, lossless) and `manifest.csv`, one row per frame:

| Column | Meaning |
| :--- | :--- |
| `position` | Frame index in decode order |
| `sequence_number` | Sequence number the frame carries (as a stream header would) |
| `timestamp_ms` | Capture timestamp the frame carries, epoch milliseconds |
| `is_tampered` | Ground truth: frame content differs from `clean` at this position |
| `tamper_type` | `none`, `splice`, `replay` or `reorder` |
| `source_ref` | Where the frame came from: `A:<index>` (this camera) or `B:<index>` (spliced camera) |

`index.csv` has one row per scenario with its paths, `reference_stream_path` (the clean stream to build a reference hash chain from), `num_tampered` and `first_tampered_position`.

Hash **decoded frames**, not the `.mkv` file: decoded frames are byte-identical across runs, but the container embeds a random segment ID, so file hashes change on every run.
