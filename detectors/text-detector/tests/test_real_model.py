"""Real-weight end-to-end verification test for Desklib fp16 + GPT-2 perplexity on local hardware."""
from __future__ import annotations

import json

import jsonschema
import pytest
import torch
from fastapi.testclient import TestClient

from app import create_app, create_default_runtime
from config import TextDetectorConfig
from conftest import REPO_ROOT, b64, make_words

RESP_SCHEMA = json.loads(
    (REPO_ROOT / "shared" / "json-api-contracts-schema" / "detector_response.schema.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.gpu
def test_real_desklib_and_gpt2_end_to_end():
    cfg = TextDetectorConfig(preload_models=False)
    if not (cfg.model_dir / "config.json").exists():
        pytest.skip(f"Local Desklib weights not downloaded yet at {cfg.model_dir}")

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    runtime = create_default_runtime(cfg)
    runtime.desklib.load()
    if runtime.perplexity is not None:
        runtime.perplexity.load()

    long_prose = make_words(
        700,
        seed_phrase=(
            "Modern distributed verification systems coordinate multimodal forensic detectors "
            "across audio video and textual channels under strict memory envelopes."
        ),
    )
    short_prose = "Too short to analyze."

    with TestClient(create_app(runtime=runtime)) as client:
        resp_long = client.post(
            "/detect",
            json={"job_id": "real-long-1", "modality": "text", "payload": b64(long_prose)},
        )
        assert resp_long.status_code == 200
        long_data = resp_long.json()
        jsonschema.validate(instance=long_data, schema=RESP_SCHEMA)
        assert long_data["status"] == "ok"
        assert long_data["signals"]["chunk_aggregation"]["chunk_count"] >= 2
        assert 0.0 <= long_data["confidence"] <= 1.0

        resp_short = client.post(
            "/detect",
            json={"job_id": "real-short-1", "modality": "text", "payload": b64(short_prose)},
        )
        assert resp_short.status_code == 200
        assert resp_short.json()["status"] == "not_applicable"

    if torch.cuda.is_available():
        peak_mb = torch.cuda.max_memory_allocated() / (1024.0 * 1024.0)
        assert peak_mb < 3500.0, f"Peak VRAM {peak_mb:.1f} MB exceeded 4 GB RTX 3050 envelope"

