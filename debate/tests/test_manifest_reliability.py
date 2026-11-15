"""
Unit tests for manifest per-condition reliability engine (`debate/manifest_reliability.py`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from capability_manifests.Schema import DETECTOR_MANIFEST_SCHEMA
from debate.claim_wrapper import wrap_detector_response
from debate.manifest_reliability import ManifestReliabilityEngine
from debate.schemas import OperatingConditions


def test_all_edited_manifests_pass_json_schema_validation():
    manifests_dir = Path(__file__).resolve().parent.parent.parent / "capability_manifests"
    checked = 0
    for name in [
        "video-classifier.json",
        "rppg.json",
        "streaming-rppg.json",
        "syncnet.json",
        "aasist.json",
        "image.json",
        "detector_image.json",
        "detector_text.json",
    ]:
        data = json.loads((manifests_dir / name).read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=DETECTOR_MANIFEST_SCHEMA)
        checked += 1
    assert checked == 8


def test_rppg_zero_bpm_triggers_critical_discount_and_secondary_authority():
    engine = ManifestReliabilityEngine()
    claim = wrap_detector_response(
        "rppg",
        {
            "job_id": "bpm0",
            "score": 0.78,
            "confidence": 0.56,
            "verdict": "synthetic",
            "estimated_bpm": 0.0,
            "input_quality": 1.0,
            "evidence": {"claim": "BVP pulse signal extracted via CHROM with 0.0 BPM.", "flags": []},
        },
        conditions=OperatingConditions(duration_seconds=5.0, mean_luminance=80.0, audio_present=False),
    )
    assert claim.observational_metrics is not None
    assert claim.observational_metrics.physiological is not None
    assert claim.observational_metrics.physiological.estimated_bpm == 0.0

    assess = engine.evaluate_claim(claim, conditions=claim.operating_conditions)
    assert assess.authority_tier == "secondary_proxy"
    assert assess.cannot_solely_certify_synthetic is True
    assert "rppg_invalid_bpm_synthetic_discount" in assess.applied_conditions
    assert assess.adjusted_confidence < 0.65
    assert assess.effective_weight < assess.base_weight


def test_advisory_gap_for_silent_video_vs_fatal_gap_for_missing_face():
    engine = ManifestReliabilityEngine()
    vc = wrap_detector_response(
        "video-classifier",
        {"job_id": "g", "confidence": 0.20, "evidence": {"claim": "ok", "flags": ["authentic_frames"]}},
    )
    sync_silent = wrap_detector_response(
        "syncnet",
        {"job_id": "g", "confidence": 0.50, "evidence": {"claim": "no audio", "flags": ["not_applicable"]}},
    )
    silent_cond = OperatingConditions(duration_seconds=6.0, mean_luminance=80.0, audio_present=False, face_detected=True)
    assess_adv = engine.evaluate_claim(sync_silent, conditions=silent_cond, is_coverage_gap=True, all_claims=[vc, sync_silent])
    assert assess_adv.is_advisory_gap is True
    assert assess_adv.is_fatal_gap is False

    # Same gap when audio WAS present and only visual detector is weak/absent -> fatal coverage gap
    audio_cond = OperatingConditions(duration_seconds=6.0, mean_luminance=80.0, audio_present=True, face_detected=True)
    assess_fatal = engine.evaluate_claim(sync_silent, conditions=audio_cond, is_coverage_gap=True, all_claims=[sync_silent])
    assert assess_fatal.is_advisory_gap is False
    assert assess_fatal.is_fatal_gap is True


def test_image_fft_corroboration_and_exif_missing_non_dispositive():
    engine = ManifestReliabilityEngine()
    borderline_fft = wrap_detector_response(
        "detector_image",
        {"job_id": "i1", "confidence": 0.59, "evidence": {"claim": "borderline", "flags": ["frequency_anomaly", "borderline"]}},
    )
    a_fft = engine.evaluate_claim(borderline_fft)
    assert "image_forensic_signal_corroboration" in a_fft.applied_conditions
    assert a_fft.adjusted_confidence >= 0.65

    social_exif = wrap_detector_response(
        "detector_image",
        {"job_id": "i2", "confidence": 0.43, "evidence": {"claim": "borderline", "flags": ["exif_missing"]}},
    )
    a_exif = engine.evaluate_claim(social_exif)
    assert "image_exif_missing_non_dispositive" in a_exif.applied_conditions
    assert 0.35 < a_exif.adjusted_confidence < 0.65


def test_text_short_attenuation_and_chunk_disagreement_damping():
    engine = ManifestReliabilityEngine()
    short_att = wrap_detector_response(
        "detector_text",
        {"job_id": "t1", "status": "ok", "confidence": 0.72, "evidence": {"claim": "short text", "flags": ["short_text_attenuated"]}},
    )
    a_short = engine.evaluate_claim(short_att)
    assert "text_marginal_length_40_to_149w" in a_short.applied_conditions
    assert a_short.effective_weight < a_short.base_weight

    divergent = wrap_detector_response(
        "detector_text",
        {
            "job_id": "t2",
            "status": "ok",
            "confidence": 0.75,
            "evidence": {"claim": "divergent", "flags": ["high_ai_probability", "chunk_disagreement", "natural_burstiness"]},
        },
    )
    a_div = engine.evaluate_claim(divergent)
    assert "text_chunk_disagreement_damping" in a_div.applied_conditions
    assert a_div.adjusted_confidence < 0.65
