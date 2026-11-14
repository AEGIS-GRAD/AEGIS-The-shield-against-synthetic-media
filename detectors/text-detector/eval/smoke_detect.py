"""Live HTTP smoke script for a running `detector_text` container or local uvicorn server."""
from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.request

HUMAN_SAMPLE = (
    "When our university lab rebuilt the cooling loop on the third floor, nobody remembered "
    "to label the bypass valve behind the server rack. Two weeks later, an undergraduate opened "
    "it while hunting for a dropped multimeter screw, and the telemetry alerts woke everyone up "
    "around two in the morning. We spent Saturday tracing every copper pipe by hand with masking "
    "tape and a Sharpie, laughing mostly so nobody would cry about the missed sleep. Looking back, "
    "that chaotic weekend taught our whole cohort more about real hardware troubleshooting than any "
    "textbook lecture we ever attended during senior year."
)

SHORT_SAMPLE = "Only nine short words here, far below threshold."


def _request(url: str, method: str = "GET", body: dict | None = None, token: str = "") -> dict:
    headers = {}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["X-Internal-Token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8005")
    parser.add_argument("--token", default=os.getenv("INTERNAL_API_KEY", ""))
    args = parser.parse_args()

    health = _request(f"{args.url}/health")
    print("HEALTH:", json.dumps(health, indent=2))

    ok_resp = _request(
        f"{args.url}/detect",
        method="POST",
        token=args.token,
        body={
            "job_id": "smoke-ok",
            "modality": "text",
            "payload": base64.b64encode(HUMAN_SAMPLE.encode("utf-8")).decode("ascii"),
        },
    )
    print("DETECT_OK:", json.dumps(ok_resp, indent=2))

    short_resp = _request(
        f"{args.url}/detect",
        method="POST",
        token=args.token,
        body={
            "job_id": "smoke-short",
            "modality": "text",
            "payload": base64.b64encode(SHORT_SAMPLE.encode("utf-8")).decode("ascii"),
        },
    )
    print("DETECT_SHORT:", json.dumps(short_resp, indent=2))


if __name__ == "__main__":
    main()

