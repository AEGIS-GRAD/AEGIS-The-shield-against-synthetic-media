"""
Tests for debate/claim_wrapper.py.

Run from the repository root:
    python -m pytest debate/tests/test_claim_wrapper.py -v

Where the 20 sample outputs come from
-------------------------------------
* video-classifier (6): 4 use REAL `det_video_classifier_confidence` values from
  eval/reports/week_benchmark_raw.csv (sample file named in each case id);
  2 are constructed because the benchmark never produced a value >= 0.65 (its
  maximum was 0.6111), so a real SYNTHETIC-polarity sample does not exist yet.
* rPPG (7): constructed. The CSV only recorded rPPG's `confidence`, whose meaning
  differs from `score` (see claim_wrapper.py, contract note 2), so it cannot be
  turned back into a full response. These replicate the CURRENT contract of
  detectors/rppg/main.py exactly (confidence = |score-0.5|*2*input_quality).
* SyncNet (7): constructed by following detectors/syncnet/infer.py's mapping
  (p_synthetic in {0.12, 0.28, 0.65, 0.92}, 0.5 + `not_applicable` when it
  cannot run). The benchmark CSV has no usable SyncNet values (all exactly 0.5).
"""

import logging

import pytest

from debate.arbitrator import JudgeArbitrator
from debate.claim_wrapper import (
    wrap_detector_response,
    wrap_video_detector_outputs,
)
from debate.disagreement import evaluate_disagreement
from debate.schemas import ClaimPolarity as P
from debate.schemas import DisagreementType, EvidenceDomain, JudgeVerdictClass

JOB = "job-test-001"


# ── Builders that mirror each detector's real response shape ─────────────────
def vc(conf):
    """video-classifier response, flags chosen exactly as detectors/video_classifier/main.py does."""
    flags = ["high_fake_probability"] if conf > 0.65 else (["authentic_frames"] if conf < 0.35 else ["borderline_frames"])
    return {
        "job_id": JOB, "confidence": conf, "raw_score": conf, "latency_ms": 5000,
        "model_version": "efficientnet-b0-v1.0",
        "evidence": {"claim": f"Frame-level EfficientNet-B0 analysis computed fake probability of {conf:.2f} across sampled frames.",
                     "flags": flags},
    }


def rppg(score, bpm=72.0, iq=1.0, flags=None, verdict=None, claim=None):
    """rPPG response, mirroring detectors/rppg/main.py."""
    flags = flags or []
    if verdict is None:
        verdict = "inconclusive" if iq < 0.5 else ("synthetic" if score > 0.5 else "authentic")
    return {
        "job_id": JOB, "modality": "video",
        "confidence": round(abs(score - 0.5) * 2.0 * iq, 4),  # NOT P(synthetic)
        "raw_score": score, "score": score, "verdict": verdict,
        "model": "rppg-chrom", "model_version": "rppg-chrom-v1.0",
        "estimated_bpm": bpm, "latency_ms": 4000,
        "evidence": {"claim": claim or f"BVP pulse signal extracted via CHROM with estimated heart rate of {bpm:.1f} BPM.",
                     "flags": flags},
        "input_quality": iq,
    }


def sync(p, offset, flags, claim="(detector claim)"):
    """SyncNet response, mirroring detectors/syncnet/infer.py."""
    return {
        "job_id": JOB, "confidence": p, "raw_score": float(offset), "latency_ms": 6000,
        "model_version": "syncnet-v1.3",
        "evidence": {"claim": claim, "flags": flags},
    }


# ── The 20 sample outputs ────────────────────────────────────────────────────
# (case id, detector, response, expected polarity, expected coverage_gap, substrings the claim must contain)
SAMPLES = [
    # --- video-classifier: 4 real benchmark values + 2 constructed ---
    ("vc_csv_296_real__0.00", "video-classifier", vc(0.0), P.AUTHENTIC, False,
     ["no significant manipulation", "0%"]),
    ("vc_csv_FaceShifter_761_766_fake__0.2634", "video-classifier", vc(0.2634), P.AUTHENTIC, False,
     ["no significant manipulation", "26%"]),  # a missed fake: the wrapper reports faithfully
    ("vc_csv_FaceShifter_705_707_fake__0.5407", "video-classifier", vc(0.5407), P.INCONCLUSIVE, False,
     ["borderline", "54%"]),
    ("vc_csv_067_real__0.6111", "video-classifier", vc(0.6111), P.INCONCLUSIVE, False,
     ["borderline", "61%"]),
    ("vc_constructed_strong_synthetic__0.91", "video-classifier", vc(0.91), P.SYNTHETIC, False,
     ["strong spatial evidence of face manipulation", "91%"]),
    ("vc_constructed_boundary__0.65", "video-classifier", vc(0.65), P.SYNTHETIC, False,
     ["weak spatial evidence of face manipulation", "65%"]),

    # --- rPPG (7 constructed) ---
    ("rppg_strong_pulse_authentic", "rppg", rppg(0.10, bpm=72), P.AUTHENTIC, False,
     ["stable, periodic pulse", "90%", "72 BPM"]),
    ("rppg_no_pulse_synthetic", "rppg", rppg(0.90, bpm=51), P.SYNTHETIC, False,
     ["No stable heartbeat signal", "strongly suggesting synthetic generation", "10%"]),
    ("rppg_low_light_synthetic", "rppg",
     rppg(0.80, iq=0.6, flags=["low_light_attenuation"]), P.SYNTHETIC, False,
     ["poorly lit"]),
    ("rppg_short_clip_authentic", "rppg",
     rppg(0.20, iq=0.7, flags=["short_clip_attenuation"]), P.AUTHENTIC, False,
     ["clip is short"]),
    ("rppg_atypical_heart_rate", "rppg",
     rppg(0.85, bpm=200, flags=["atypical_heart_rate"]), P.SYNTHETIC, False,
     ["outside the typical human range", "200 BPM"]),
    ("rppg_guardrail_short_clip", "rppg",
     rppg(0.5, bpm=0.0, iq=0.0, verdict="inconclusive", flags=["insufficient_duration"],
          claim="Clip is 1.2 s long; rPPG needs at least 2.0 s for a stable pulse estimate."),
     P.INCONCLUSIVE, True,
     ["Clip is 1.2 s long; rPPG needs at least 2.0 s for a stable pulse estimate."]),  # detector's own sentence kept
    ("rppg_degraded_input_inconclusive", "rppg",
     rppg(0.75, iq=0.4, flags=["low_light_attenuation", "short_clip_attenuation"]), P.INCONCLUSIVE, True,
     ["unreliable", "40%", "poor lighting and a short clip"]),

    # --- SyncNet (7 constructed from infer.py's mapping) ---
    ("sync_verified", "syncnet", sync(0.12, 0, ["lip_sync_verified"]), P.AUTHENTIC, False,
     ["tightly synchronized", "offset 0 frames"]),
    ("sync_in_sync", "syncnet", sync(0.28, -1, ["in_sync"]), P.AUTHENTIC, False,
     ["natural range", "40 ms"]),
    ("sync_mild_offset", "syncnet", sync(0.65, 2, ["sync_offset_detected"]), P.SYNTHETIC, False,
     ["mild lip-audio offset of 2 frames", "80 ms"]),
    ("sync_severe_audio_lags", "syncnet", sync(0.92, -5, ["sync_offset_detected", "audio_visual_mismatch"]),
     P.SYNTHETIC, False, ["audio lags the video by 5 frames", "200 ms"]),
    ("sync_severe_audio_leads", "syncnet", sync(0.92, 6, ["sync_offset_detected", "audio_visual_mismatch"]),
     P.SYNTHETIC, False, ["audio leads the video by 6 frames", "240 ms"]),
    ("sync_not_applicable_no_audio", "syncnet",
     sync(0.5, 0, ["not_applicable"], claim="No audio track detected in submitted file — lip-sync analysis skipped."),
     P.NOT_APPLICABLE, True,
     ["No audio track detected in submitted file — lip-sync analysis skipped."]),
    ("sync_not_applicable_no_face", "syncnet",
     sync(0.5, 0, ["not_applicable", "insufficient_signal"],
          claim="No valid face or mouth region detected in video — lip-sync analysis skipped."),
     P.NOT_APPLICABLE, True,
     ["No valid face or mouth region detected in video — lip-sync analysis skipped."]),
]


def test_there_are_exactly_20_samples():
    assert len(SAMPLES) == 20


@pytest.mark.parametrize("case_id, detector, response, polarity, gap, must_contain", SAMPLES,
                         ids=[s[0] for s in SAMPLES])
def test_sample_output_becomes_a_readable_claim(case_id, detector, response, polarity, gap, must_contain):
    claim = wrap_detector_response(detector, response)

    assert claim.polarity == polarity
    assert claim.coverage_gap is gap
    assert claim.detector_id == detector
    assert claim.job_id == JOB
    assert 0.0 <= claim.confidence <= 1.0

    # The point of the task: a sentence, not a bare number.
    assert len(claim.claim.split()) >= 8, f"claim too terse: {claim.claim!r}"
    assert claim.claim.rstrip().endswith("."), f"claim should be a full sentence: {claim.claim!r}"
    for fragment in must_contain:
        assert fragment in claim.claim, f"{fragment!r} missing from {claim.claim!r}"

    # Flags are passed through untouched (downstream matches on exact names).
    assert claim.flags == response["evidence"]["flags"]
    # Every claim is traceable to the raw output that produced it.
    assert claim.evidence_hash and len(claim.evidence_hash) == 64


# ── Domains ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("detector, expected", [
    ("video-classifier", EvidenceDomain.SPATIAL_PIXEL),
    ("rppg", EvidenceDomain.PHYSIOLOGICAL_BVP),
    ("syncnet", EvidenceDomain.AUDIOVISUAL_SYNC),
])
def test_domain_mapping(detector, expected):
    resp = {"video-classifier": vc(0.9), "rppg": rppg(0.9), "syncnet": sync(0.92, 5, ["audio_visual_mismatch"])}[detector]
    assert wrap_detector_response(detector, resp).domain == expected


# ── rPPG: the confidence-semantics trap ──────────────────────────────────────
def test_rppg_uses_score_not_confidence():
    """Authentic video, strong pulse: rPPG reports score=0.05 but confidence=0.90.
    Passing `confidence` through would make this a 0.90 SYNTHETIC claim."""
    resp = rppg(0.05, bpm=70)
    assert resp["confidence"] == 0.9  # the trap value
    claim = wrap_detector_response("rppg", resp)
    assert claim.confidence == 0.05
    assert claim.polarity == P.AUTHENTIC


def test_rppg_attenuation_is_applied_exactly_once():
    claim = wrap_detector_response("rppg", rppg(0.80, iq=0.6, flags=["low_light_attenuation"]))
    assert claim.attenuation_factors.luminance_factor == 0.6
    assert claim.attenuation_factors.duration_factor == 1.0
    # 0.5 + (0.80 - 0.5) * 0.6 = 0.68  (not 0.5 + 0.3*0.6*0.6)
    assert claim.effective_confidence == pytest.approx(0.68)


def test_rppg_both_attenuation_flags_keep_the_composite():
    claim = wrap_detector_response(
        "rppg", rppg(0.80, iq=0.6, flags=["low_light_attenuation", "short_clip_attenuation"]))
    assert claim.attenuation_factors.composite_attenuation == pytest.approx(0.6)


def test_rppg_without_score_falls_back_to_confidence_with_a_warning(caplog):
    legacy = rppg(0.8)
    del legacy["score"]
    legacy["confidence"] = 0.8  # legacy contract: confidence == P(synthetic)
    with caplog.at_level(logging.WARNING):
        claim = wrap_detector_response("rppg", legacy)
    assert claim.confidence == 0.8
    assert "no `score`" in caplog.text


# ── Polarity thresholds (inclusive, same as disagreement.py) ─────────────────
@pytest.mark.parametrize("conf, expected", [
    (0.0, P.AUTHENTIC), (0.35, P.AUTHENTIC), (0.3501, P.INCONCLUSIVE),
    (0.6499, P.INCONCLUSIVE), (0.65, P.SYNTHETIC), (1.0, P.SYNTHETIC),
])
def test_polarity_boundaries(conf, expected):
    assert wrap_detector_response("video-classifier", vc(conf)).polarity == expected


# ── Metrics ──────────────────────────────────────────────────────────────────
def test_metrics_are_filled_where_the_detector_provides_them():
    r = wrap_detector_response("rppg", rppg(0.10, bpm=72))
    assert r.observational_metrics.physiological.estimated_bpm == 72
    assert r.observational_metrics.physiological.spectral_purity == pytest.approx(0.9)

    s = wrap_detector_response("syncnet", sync(0.92, -5, ["audio_visual_mismatch"]))
    assert s.observational_metrics.audiovisual.optimal_offset_frames == -5
    assert s.observational_metrics.audiovisual.offset_ms == -200.0

    v = wrap_detector_response("video-classifier", vc(0.9))
    assert v.observational_metrics.spatial.sampled_frames == 10
    assert v.observational_metrics.spatial.max_frame_anomaly is None  # the detector does not expose it

    na = wrap_detector_response("syncnet", sync(0.5, 0, ["not_applicable"]))
    assert na.observational_metrics is None


# ── Evidence hash, errors, batch helper ──────────────────────────────────────
def test_evidence_hash_is_deterministic_and_input_sensitive():
    a1 = wrap_detector_response("video-classifier", vc(0.9))
    a2 = wrap_detector_response("video-classifier", vc(0.9))
    b = wrap_detector_response("video-classifier", vc(0.91))
    assert a1.evidence_hash == a2.evidence_hash
    assert a1.evidence_hash != b.evidence_hash


def test_unknown_detector_raises():
    with pytest.raises(ValueError, match="Unknown video detector"):
        wrap_detector_response("aasist", vc(0.5))  # audio detector is out of scope for this module


def test_batch_skips_missing_detectors_and_keeps_a_stable_order():
    claims = wrap_video_detector_outputs({
        "syncnet": sync(0.5, 0, ["not_applicable"]),
        "video-classifier": vc(0.9),
        "rppg": None,  # timed out / not called: no claim is invented
    })
    assert [c.detector_id for c in claims] == ["video-classifier", "syncnet"]


def test_batch_rejects_unknown_detector_ids():
    with pytest.raises(ValueError):
        wrap_video_detector_outputs({"aasist": vc(0.5)})


# ── Integration with the real debate engine ──────────────────────────────────
def test_not_applicable_syncnet_is_a_gap_not_a_conflict():
    claims = wrap_video_detector_outputs({
        "video-classifier": vc(0.10),
        "rppg": rppg(0.10),
        "syncnet": sync(0.5, 0, ["not_applicable"]),
    })
    analysis = evaluate_disagreement(claims)
    assert analysis.coverage_gaps == ["syncnet"]
    assert analysis.requires_arbitration is False
    assert analysis.primary_disagreement_type == DisagreementType.CONSENSUS


def test_spatial_vs_physiological_conflict_triggers_arbitration():
    claims = wrap_video_detector_outputs({"video-classifier": vc(0.91), "rppg": rppg(0.10)})
    analysis = evaluate_disagreement(claims)
    assert analysis.requires_arbitration is True
    assert analysis.primary_disagreement_type == DisagreementType.POLARITY_INVERSION
    assert set(analysis.conflicting_detectors) == {"video-classifier", "rppg"}


def test_face_swap_rule_fires_on_wrapped_claims():
    """Rule 3 (face-swap pulse preservation) needs rPPG's P(synthetic) to be LOW.
    With rPPG's raw `confidence` (0.80) it would never fire; with `score` (0.10) it does."""
    claims = wrap_video_detector_outputs({
        "video-classifier": vc(0.91),
        "rppg": rppg(0.10),
        "syncnet": sync(0.5, 0, ["not_applicable"]),
    })
    verdict = JudgeArbitrator().arbitrate(claims)
    assert verdict.final_verdict == JudgeVerdictClass.SYNTHETIC
    assert verdict.calibrated_score >= 0.85
    assert "Rule 3" in verdict.forensic_justification


def test_low_light_rule_fires_on_wrapped_claims():
    """Rule 1 needs the `low_light_attenuation` flag and P(synthetic) > 0.60 on the rPPG claim."""
    claims = wrap_video_detector_outputs({
        "video-classifier": vc(0.10),
        "rppg": rppg(0.85, iq=0.6, flags=["low_light_attenuation"]),
    })
    verdict = JudgeArbitrator().arbitrate(claims)
    assert "Rule 1" in verdict.forensic_justification
    assert verdict.final_verdict == JudgeVerdictClass.AUTHENTIC
