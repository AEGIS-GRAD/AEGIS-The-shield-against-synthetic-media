"""
Tests for AEGIS Claim and Evidence Schema validation.
Verifies Pydantic v2 schemas and JSON Schema Draft-07 compliance.
"""

import json
from pathlib import Path
import pytest
import jsonschema

from debate.schemas import (
    ClaimPolarity,
    CourtAdmissibleVerdict,
    EvidenceDomain,
    ForensicClaim,
    JudgeVerdictClass,
    OperatingConditions,
    SpatialMetrics,
    PhysiologicalMetrics,
    AudioVisualMetrics,
    ObservationalMetrics,
    AttenuationFactors,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "shared" / "json-api-contracts-schema" / "claim_evidence_schema.json"


@pytest.fixture
def json_schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_claim_pydantic_validation():
    claim = ForensicClaim(
        job_id="test-job-001",
        detector_id="video-classifier",
        model_version="efficientnet-b0-v1.0",
        domain=EvidenceDomain.SPATIAL_PIXEL,
        polarity=ClaimPolarity.SYNTHETIC,
        confidence=0.88,
        raw_score=2.45,
        claim="Spatial face-warping detected on 8/10 sampled frames.",
        flags=["high_fake_probability"],
        observational_metrics=ObservationalMetrics(
            spatial=SpatialMetrics(
                sampled_frames=10,
                max_frame_anomaly=0.94,
                frame_variance=0.012,
                suspicious_frame_ratio=0.80,
            )
        ),
        attenuation_factors=AttenuationFactors(luminance_factor=1.0),
    )

    dumped = claim.model_dump()
    assert dumped["detector_id"] == "video-classifier"
    assert dumped["confidence"] == 0.88
    assert claim.effective_confidence == 0.88


def test_effective_confidence_attenuation():
    # If luminance is severely degraded, deviation from 0.5 is attenuated
    claim = ForensicClaim(
        job_id="test-job-002",
        detector_id="rppg",
        model_version="rppg-chrom-v1.0",
        domain=EvidenceDomain.PHYSIOLOGICAL_BVP,
        polarity=ClaimPolarity.SYNTHETIC,
        confidence=0.90,  # deviation = +0.40
        claim="Pulse absent.",
        flags=["low_light_attenuation"],
        attenuation_factors=AttenuationFactors(luminance_factor=0.25),
    )
    # Attenuated deviation = 0.40 * 0.25 = 0.10 -> effective = 0.60
    assert claim.effective_confidence == 0.60


def test_json_schema_validation(json_schema):
    sample_payload = {
        "job_id": "test-job-003",
        "detector_id": "syncnet",
        "model_version": "syncnet-v1.3",
        "domain": "audiovisual_sync",
        "polarity": "SYNTHETIC",
        "confidence": 0.92,
        "raw_score": 5.0,
        "claim": "Severe desync detected: audio leads video by 5 frames.",
        "flags": ["sync_offset_detected", "audio_visual_mismatch"],
        "observational_metrics": {
            "audiovisual": {
                "optimal_offset_frames": 5,
                "offset_ms": 200.0,
                "min_distance": 0.85,
                "sync_confidence": 0.42,
            }
        },
        "coverage_gap": False,
        "evidence_hash": "a" * 64,
        "timestamp": "2026-10-14T23:00:00Z",
    }

    # Should validate without raising jsonschema.ValidationError
    jsonschema.validate(instance=sample_payload, schema=json_schema)


def test_verdict_pydantic_validation():
    verdict = CourtAdmissibleVerdict(
        verdict_id="vrd-123456",
        job_id="test-job-004",
        final_verdict=JudgeVerdictClass.SYNTHETIC,
        calibrated_score=0.87,
        confidence_interval=[0.82, 0.92],
        arbitration_mode="expert_deterministic_judge",
        adjudications=[],
        forensic_justification="Conclusive boundary manipulation identified.",
        coverage_warnings=[],
        siem_alert_tier="P1_CRITICAL",
        evidence_manifest_hash="b" * 64,
    )
    dumped = verdict.model_dump()
    assert dumped["final_verdict"] == "SYNTHETIC"
    assert dumped["siem_alert_tier"] == "P1_CRITICAL"
