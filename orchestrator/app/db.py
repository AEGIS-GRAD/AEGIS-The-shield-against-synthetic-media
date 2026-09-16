import sqlite3
import json
import os
from datetime import datetime, timezone

# Pin to the directory this file lives in so the DB is always found at the
# same absolute path regardless of where uvicorn is launched from.
_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "orchestrator_log.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            input_file TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            detectors_called_json TEXT NOT NULL,
            raw_results_json TEXT NOT NULL,
            aggregated_score REAL,
            aggregated_verdict TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_decision(input_file, metadata, detectors_called, raw_results, aggregated_score, aggregated_verdict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO decisions
           (timestamp, input_file, metadata_json, detectors_called_json, raw_results_json, aggregated_score, aggregated_verdict)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            input_file,
            json.dumps(metadata),
            json.dumps(detectors_called),
            json.dumps(raw_results),
            aggregated_score,
            aggregated_verdict,
        ),
    )
    conn.commit()
    conn.close()