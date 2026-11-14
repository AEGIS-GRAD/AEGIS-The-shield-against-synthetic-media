"""Tests validating capability_manifests/detector_text.json against AEGIS schema and orchestrator loader."""
from __future__ import annotations

import json
import sys

import jsonschema

from conftest import REPO_ROOT

MANIFEST_DIR = REPO_ROOT / "capability_manifests"
if str(MANIFEST_DIR) not in sys.path:
    sys.path.insert(0, str(MANIFEST_DIR))

from Schema import DETECTOR_MANIFEST_SCHEMA  # noqa: E402


def test_text_manifest_conforms_to_schema_and_documents_limitations():
    path = MANIFEST_DIR / "detector_text.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=DETECTOR_MANIFEST_SCHEMA)

    assert data["detector_name"] == "detector_text"
    assert data["modality"] == ["text"]
    assert data["model_metadata"]["license"] == "MIT"
    assert data["model_metadata"]["backbone"] == "microsoft/deberta-v3-large"
    assert len(data["known_failure_modes"]) >= 3

