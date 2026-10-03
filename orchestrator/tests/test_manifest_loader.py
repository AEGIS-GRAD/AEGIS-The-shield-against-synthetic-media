"""
tests/test_manifest_loader.py -- Unit tests for orchestrator/app/manifest_loader.py
=====================================================================================
Tests are grouped into four suites:

1. TestLoadAllManifests   -- loading the real manifests from the repo
2. TestLoadManifest       -- single-manifest loading, error paths
3. TestValidateManifest   -- schema validation, good and bad inputs
4. TestRenderManifestText -- text rendering (manifest + registry)

Run from the repo root:
    pip install jsonschema pytest
    pytest orchestrator/tests/test_manifest_loader.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup: make orchestrator/app/ and capability_manifests/ importable
# regardless of where pytest is invoked from.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_APP_DIR = _REPO_ROOT / "orchestrator" / "app"
_MANIFESTS_DIR = _REPO_ROOT / "capability_manifests"

for _p in [str(_APP_DIR), str(_MANIFESTS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from manifest_loader import (  # noqa: E402
    ManifestError,
    ManifestNotFoundError,
    ManifestValidationError,
    load_all_manifests,
    load_manifest,
    render_manifest_text,
    render_registry_text,
    validate_manifest,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

KNOWN_DETECTORS = {"aasist", "rppg", "syncnet", "video-classifier"}


@pytest.fixture()
def minimal_valid_manifest() -> dict:
    return {
        "detector_name": "test-detector",
        "modality": ["video"],
        "version": "test-v1",
        "description": "A test detector.",
        "input_constraints": {
            "requires_audio": False,
            "min_duration_seconds": 1.0,
            "max_duration_seconds": None,
            "supported_formats": [".mp4"],
        },
        "performance": {
            "avg_latency_ms": None,
            "p95_latency_ms": None,
            "avg_ram_usage_mb": None,
            "avg_vram_usage_mb": None,
            "measured_on": "PENDING",
        },
        "known_failure_modes": [
            {
                "condition": "very dark footage",
                "effect": "high false-negative rate",
                "source": "test/notes.md",
            }
        ],
        "reliability_notes": "Works well in normal lighting.",
    }


@pytest.fixture()
def real_manifests() -> list[dict]:
    return load_all_manifests(_MANIFESTS_DIR)


# ===========================================================================
# 1. load_all_manifests
# ===========================================================================

class TestLoadAllManifests:
    def test_returns_all_four_detectors(self, real_manifests):
        names = {m["detector_name"] for m in real_manifests}
        assert names == KNOWN_DETECTORS

    def test_result_is_sorted_by_name(self, real_manifests):
        names = [m["detector_name"] for m in real_manifests]
        assert names == sorted(names)

    def test_each_manifest_has_required_keys(self, real_manifests):
        required = {
            "detector_name", "modality", "version", "description",
            "input_constraints", "performance", "known_failure_modes",
            "reliability_notes",
        }
        for m in real_manifests:
            assert required.issubset(m.keys()), f"{m['detector_name']} is missing keys"

    def test_raises_on_empty_directory(self, tmp_path):
        with pytest.raises(ManifestError, match="No manifest JSON files found"):
            load_all_manifests(tmp_path)

    def test_raises_on_invalid_manifest_in_directory(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(
            json.dumps({"detector_name": "bad", "modality": ["video"]}),
            encoding="utf-8",
        )
        with pytest.raises(ManifestValidationError):
            load_all_manifests(tmp_path)

    def test_raises_on_malformed_json(self, tmp_path):
        bad = tmp_path / "broken.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ManifestError, match="Malformed JSON"):
            load_all_manifests(tmp_path)


# ===========================================================================
# 2. load_manifest (single detector)
# ===========================================================================

class TestLoadManifest:
    @pytest.mark.parametrize("name", sorted(KNOWN_DETECTORS))
    def test_loads_each_real_detector(self, name):
        m = load_manifest(name, _MANIFESTS_DIR)
        assert m["detector_name"] == name

    def test_raises_not_found_for_unknown_detector(self):
        with pytest.raises(ManifestNotFoundError, match="no-such-detector"):
            load_manifest("no-such-detector", _MANIFESTS_DIR)

    def test_raises_validation_error_for_invalid_file(self, tmp_path):
        bad = tmp_path / "mydet.json"
        bad.write_text(
            json.dumps({"detector_name": "mydet"}),
            encoding="utf-8",
        )
        with pytest.raises(ManifestValidationError) as exc_info:
            load_manifest("mydet", tmp_path)
        assert exc_info.value.detector_name == "mydet"

    def test_returned_dict_matches_file_content(self):
        m = load_manifest("aasist", _MANIFESTS_DIR)
        raw_path = _MANIFESTS_DIR / "aasist.json"
        with open(raw_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        assert m == raw


# ===========================================================================
# 3. validate_manifest
# ===========================================================================

class TestValidateManifest:
    def test_valid_minimal_manifest_does_not_raise(self, minimal_valid_manifest):
        validate_manifest(minimal_valid_manifest)

    def test_valid_real_manifests_pass(self, real_manifests):
        for m in real_manifests:
            validate_manifest(m)

    def test_missing_required_field_raises(self):
        bad = {"detector_name": "x", "modality": ["video"]}
        with pytest.raises(ManifestValidationError):
            validate_manifest(bad)

    def test_wrong_modality_enum_raises(self, minimal_valid_manifest):
        minimal_valid_manifest["modality"] = ["hologram"]
        with pytest.raises(ManifestValidationError):
            validate_manifest(minimal_valid_manifest)

    def test_error_carries_detector_name(self, minimal_valid_manifest):
        del minimal_valid_manifest["reliability_notes"]
        with pytest.raises(ManifestValidationError) as exc_info:
            validate_manifest(minimal_valid_manifest)
        assert exc_info.value.detector_name == "test-detector"

    def test_free_detector_name_is_valid(self):
        m = {
            "detector_name": "brand-new-detector",
            "modality": ["audio"],
            "version": "v0.1",
            "description": "desc",
            "input_constraints": {
                "requires_audio": True,
                "min_duration_seconds": 0.5,
                "supported_formats": [".wav"],
            },
            "performance": {"avg_latency_ms": 100, "measured_on": "test"},
            "known_failure_modes": [],
            "reliability_notes": "ok",
        }
        validate_manifest(m)


# ===========================================================================
# 4. render_manifest_text / render_registry_text
# ===========================================================================

class TestRenderManifestText:
    def test_contains_detector_name(self, minimal_valid_manifest):
        assert "test-detector" in render_manifest_text(minimal_valid_manifest)

    def test_contains_version(self, minimal_valid_manifest):
        assert "test-v1" in render_manifest_text(minimal_valid_manifest)

    def test_contains_modality(self, minimal_valid_manifest):
        assert "video" in render_manifest_text(minimal_valid_manifest)

    def test_contains_requires_audio_flag(self, minimal_valid_manifest):
        text = render_manifest_text(minimal_valid_manifest)
        assert "requires_audio" in text
        assert "False" in text

    def test_contains_min_duration(self, minimal_valid_manifest):
        assert "1.0" in render_manifest_text(minimal_valid_manifest)

    def test_contains_failure_mode_condition(self, minimal_valid_manifest):
        assert "very dark footage" in render_manifest_text(minimal_valid_manifest)

    def test_contains_failure_mode_effect(self, minimal_valid_manifest):
        assert "high false-negative rate" in render_manifest_text(minimal_valid_manifest)

    def test_contains_reliability_notes(self, minimal_valid_manifest):
        assert "Works well in normal lighting." in render_manifest_text(minimal_valid_manifest)

    def test_pending_performance_shows_pending(self, minimal_valid_manifest):
        assert "pending" in render_manifest_text(minimal_valid_manifest)

    def test_real_latency_shows_seconds(self, minimal_valid_manifest):
        minimal_valid_manifest["performance"]["avg_latency_ms"] = 7000
        minimal_valid_manifest["performance"]["p95_latency_ms"] = 15000
        text = render_manifest_text(minimal_valid_manifest)
        assert "7.0s" in text
        assert "15.0s" in text

    def test_no_failure_modes_shows_none_documented(self, minimal_valid_manifest):
        minimal_valid_manifest["known_failure_modes"] = []
        assert "none documented" in render_manifest_text(minimal_valid_manifest)

    def test_max_duration_included_when_present(self, minimal_valid_manifest):
        minimal_valid_manifest["input_constraints"]["max_duration_seconds"] = 60.0
        assert "60.0" in render_manifest_text(minimal_valid_manifest)

    def test_renders_all_real_manifests_without_error(self, real_manifests):
        for m in real_manifests:
            text = render_manifest_text(m)
            assert m["detector_name"] in text


class TestRenderRegistryText:
    def test_empty_list_returns_placeholder(self):
        assert "No capability manifests loaded" in render_registry_text([])

    def test_header_shows_count(self, real_manifests):
        text = render_registry_text(real_manifests)
        assert f"{len(real_manifests)} detector(s)" in text

    def test_all_detector_names_present(self, real_manifests):
        text = render_registry_text(real_manifests)
        for m in real_manifests:
            assert m["detector_name"] in text

    def test_single_manifest_renders(self, minimal_valid_manifest):
        text = render_registry_text([minimal_valid_manifest])
        assert "1 detector(s)" in text
        assert "test-detector" in text

    def test_registry_text_is_string(self, real_manifests):
        assert isinstance(render_registry_text(real_manifests), str)
