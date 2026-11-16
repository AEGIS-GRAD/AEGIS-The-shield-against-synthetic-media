"""
Unit tests for the MCP capabilities() tool.
"""

from __future__ import annotations

import pytest
import server


def test_capabilities_status_ok():
    """Verify capabilities() returns status ok and a populated dictionary."""
    res = server.capabilities()
    assert res["status"] == "ok"
    assert "detectors" in res
    assert "default_weights" in res
    assert "authority_tiers" in res
    assert res["total_detectors"] >= 5


def test_capabilities_core_detectors_present():
    """Verify core detectors exist with required metadata fields."""
    res = server.capabilities()
    detectors = res["detectors"]

    expected_detectors = [
        "video-classifier",
        "rppg",
        "syncnet",
        "aasist",
        "detector_image",
        "detector_text",
    ]
    for det_id in expected_detectors:
        assert det_id in detectors, f"Expected detector '{det_id}' in capabilities"
        meta = detectors[det_id]
        assert "manifest" in meta
        assert "default_weight" in meta
        assert "authority_tier" in meta

        manifest = meta["manifest"]
        assert "detector_name" in manifest
        assert "modality" in manifest
        assert "version" in manifest


def test_capabilities_authority_tiers():
    """Verify primary detectors and secondary proxy classifications."""
    res = server.capabilities()
    detectors = res["detectors"]

    # video-classifier must be a primary detector
    assert detectors["video-classifier"]["authority_tier"] == "primary"
    assert detectors["video-classifier"]["default_weight"] >= 1.0

    # rppg must be classified as secondary_proxy
    assert detectors["rppg"]["authority_tier"] == "secondary_proxy"
    assert detectors["rppg"]["default_weight"] < 1.0
    assert detectors["rppg"]["manifest"].get("cannot_solely_certify_synthetic") is True


def test_capabilities_input_constraints():
    """Verify input constraints are present in manifests."""
    res = server.capabilities()
    detectors = res["detectors"]

    aasist_constraints = detectors["aasist"]["manifest"].get("input_constraints", {})
    assert aasist_constraints.get("requires_audio") is True
    assert aasist_constraints.get("min_duration_seconds") == 1.0

    rppg_constraints = detectors["rppg"]["manifest"].get("input_constraints", {})
    assert rppg_constraints.get("min_duration_seconds") == 2.0
