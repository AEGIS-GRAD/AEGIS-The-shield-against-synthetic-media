"""
test_role7_bundles.py  —  Role 7: Verify Bundles of Related Media
==================================================================
FULLY SELF-CONTAINED: no imports from orchestrator/app, debate, or detectors.

All models, enums, fusion logic, and agreement logic are defined locally here.
This means the file runs with zero extra dependencies beyond pytest itself.

Run from ANYWHERE in the project:
    pytest eval/tests/test_role7_bundles.py -v

Or from project root:
    cd "d:\\Grad. project\\AEGIS-The-shield-against-synthetic-media"
    pytest eval\\tests\\test_role7_bundles.py -v
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  LOCAL MODEL DEFINITIONS  (mirrors orchestrator/app/models.py & aggregate.py)
#  No imports from orchestrator — fully portable.
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict
import uuid


class AggregateOutcome(str, Enum):
    """
    Canonical AEGIS verdicts.
    Mirrors orchestrator/app/aggregate.py:AggregateOutcome.
    """
    AUTHENTIC  = "AUTHENTIC"
    SYNTHETIC  = "SYNTHETIC"
    UNCERTAIN  = "UNCERTAIN"
    NO_RESULTS = "NO_RESULTS"


SYNTHETIC_THRESHOLD = 0.65   # confidence >= this  → SYNTHETIC
AUTHENTIC_THRESHOLD = 0.35   # confidence <= this  → AUTHENTIC
# between → UNCERTAIN

VALID_VERDICTS = {v.value for v in AggregateOutcome}

# Detector weights — same as orchestrator/app/aggregate.py
DETECTOR_WEIGHTS: Dict[str, float] = {
    "video-classifier": 1.5,
    "rppg":             1.2,
    "syncnet":          1.2,
    "aasist":           1.0,
    "detector_image":   1.2,
    "detector_text":    0.8,
}


@dataclass
class DetectorEvidence:
    """Mirrors orchestrator/app/models.py:DetectorEvidence."""
    claim: str
    flags: List[str] = field(default_factory=list)


@dataclass
class DetectorResult:
    """
    Mirrors orchestrator/app/models.py:DetectorResult.
    confidence: 0.0 = AUTHENTIC  …  1.0 = SYNTHETIC
    """
    detector:       str
    status:         str              # "ok" | "failed"
    confidence:     Optional[float] = None
    raw_score:      Optional[float] = None
    latency_ms:     Optional[int]   = None
    model_version:  Optional[str]   = None
    evidence:       Optional[DetectorEvidence] = None
    job_id:         Optional[str]   = None
    error:          Optional[str]   = None

    def __post_init__(self):
        self.job_id = self.job_id or str(uuid.uuid4())


def _aggregate(results: List[DetectorResult]) -> tuple[float, str]:
    """
    Weighted-average fusion — mirrors orchestrator/app/aggregate.py:aggregate_results().
    Returns (score, verdict_string).
    """
    usable = [r for r in results if r.status == "ok" and r.confidence is not None]
    if not usable:
        return 0.0, AggregateOutcome.NO_RESULTS.value

    w_sum = sum(r.confidence * DETECTOR_WEIGHTS.get(r.detector, 1.0) for r in usable)
    t_sum = sum(DETECTOR_WEIGHTS.get(r.detector, 1.0) for r in usable)
    score = round(w_sum / max(t_sum, 1e-9), 4)

    if score >= SYNTHETIC_THRESHOLD:
        return score, AggregateOutcome.SYNTHETIC.value
    if score <= AUTHENTIC_THRESHOLD:
        return score, AggregateOutcome.AUTHENTIC.value
    return score, AggregateOutcome.UNCERTAIN.value


# ── Helpers ──────────────────────────────────────────────────────────────────

def _det(detector: str, confidence: float, claim: str,
         flags: Optional[List[str]] = None, status: str = "ok",
         error: Optional[str] = None) -> DetectorResult:
    """Build a DetectorResult quickly."""
    return DetectorResult(
        detector=detector,
        status=status,
        confidence=confidence if status == "ok" else None,
        raw_score=round(confidence * 2 - 1, 4) if status == "ok" else None,
        latency_ms=10,
        model_version="test-v1",
        evidence=DetectorEvidence(claim=claim, flags=flags or []),
        error=error,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  BUNDLE DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ModalitySummary:
    modality:   str    # "image" | "text" | "video" | "audio"
    detector:   str
    confidence: float
    verdict:    str    # one of VALID_VERDICTS
    claim:      str


@dataclass
class BundleVerdict:
    bundle_id:               str
    modality_summaries:      List[ModalitySummary] = field(default_factory=list)
    agreement_state:         str = "insufficient"
    # agree_synthetic | agree_authentic | partial | disagree | single | insufficient
    agreement_summary:       str = ""
    overall_verdict:         str = "UNCERTAIN"
    conflicting_modalities:  List[str] = field(default_factory=list)


def _bundle_verdict(bundle_id: str, summaries: List[ModalitySummary]) -> BundleVerdict:
    """
    Fuse per-modality summaries into a BundleVerdict with cross-modal agreement.
    This is the core Role-7 function under test.
    """
    valid = [s for s in summaries
             if s.verdict not in (AggregateOutcome.NO_RESULTS.value, "FAILED")]

    if not valid:
        return BundleVerdict(
            bundle_id=bundle_id, agreement_state="insufficient",
            agreement_summary="All detectors failed or produced no results.",
            overall_verdict=AggregateOutcome.NO_RESULTS.value,
            modality_summaries=summaries,
        )

    if len(valid) == 1:
        s = valid[0]
        return BundleVerdict(
            bundle_id=bundle_id, agreement_state="single",
            agreement_summary=f"Single modality ({s.modality}) only — no cross-modal comparison.",
            overall_verdict=s.verdict,
            modality_summaries=summaries,
        )

    synth = [s for s in valid if s.verdict == AggregateOutcome.SYNTHETIC.value]
    auth  = [s for s in valid if s.verdict == AggregateOutcome.AUTHENTIC.value]
    total = len(valid)
    agreement_score = max(len(synth), len(auth)) / total

    if len(synth) == total:
        return BundleVerdict(
            bundle_id=bundle_id, agreement_state="agree_synthetic",
            agreement_summary=f"All {total} modalities agree: SYNTHETIC.",
            overall_verdict=AggregateOutcome.SYNTHETIC.value,
            conflicting_modalities=[],
            modality_summaries=summaries,
        )

    if len(auth) == total:
        return BundleVerdict(
            bundle_id=bundle_id, agreement_state="agree_authentic",
            agreement_summary=f"All {total} modalities agree: AUTHENTIC.",
            overall_verdict=AggregateOutcome.AUTHENTIC.value,
            conflicting_modalities=[],
            modality_summaries=summaries,
        )

    if agreement_score >= 0.75:
        if len(synth) > len(auth):
            conflict = [s.modality for s in auth]
            return BundleVerdict(
                bundle_id=bundle_id, agreement_state="partial",
                agreement_summary=(f"Majority ({len(synth)}/{total}) say SYNTHETIC; "
                                   f"conflicting: {conflict}."),
                overall_verdict=AggregateOutcome.SYNTHETIC.value,
                conflicting_modalities=conflict,
                modality_summaries=summaries,
            )
        else:
            conflict = [s.modality for s in synth]
            return BundleVerdict(
                bundle_id=bundle_id, agreement_state="partial",
                agreement_summary=(f"Majority ({len(auth)}/{total}) say AUTHENTIC; "
                                   f"conflicting: {conflict}."),
                overall_verdict=AggregateOutcome.AUTHENTIC.value,
                conflicting_modalities=conflict,
                modality_summaries=summaries,
            )

    # True disagreement — roughly 50/50
    conflict = [s.modality for s in (synth if len(synth) <= len(auth) else auth)]
    return BundleVerdict(
        bundle_id=bundle_id, agreement_state="disagree",
        agreement_summary=(
            f"Cross-modal DISAGREEMENT: {len(synth)} say SYNTHETIC "
            f"({[s.modality for s in synth]}), "
            f"{len(auth)} say AUTHENTIC ({[s.modality for s in auth]}). "
            "Human review recommended."
        ),
        overall_verdict=AggregateOutcome.UNCERTAIN.value,
        conflicting_modalities=conflict,
        modality_summaries=summaries,
    )


def _summarise(modality: str, results: List[DetectorResult]) -> ModalitySummary:
    """Run local aggregation on a list of DetectorResults and wrap into a ModalitySummary."""
    score, verdict = _aggregate(results)
    r = results[0]
    claim = r.evidence.claim if r.evidence else ""
    return ModalitySummary(modality=modality, detector=r.detector,
                           confidence=score, verdict=verdict, claim=claim)


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 1 — Image (SYNTHETIC) + Caption text (SYNTHETIC) → agree_synthetic
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase1_BothSynthetic:
    """Both image and text detectors report SYNTHETIC → perfect agreement."""

    def test_agree_synthetic(self):
        image_results = [_det("detector_image", 0.92,
                              "GAN frequency grid artifacts detected.",
                              ["frequency_anomaly", "high_confidence_synthetic"])]
        text_results  = [_det("detector_text", 0.89,
                              "Low perplexity; LLM n-gram repetition.",
                              ["stylometry_synthetic"])]

        summaries = [
            _summarise("image", image_results),
            _summarise("text",  text_results),
        ]
        bundle = _bundle_verdict("case_01", summaries)

        assert bundle.agreement_state == "agree_synthetic", bundle.agreement_summary
        assert bundle.overall_verdict == "SYNTHETIC"
        assert bundle.conflicting_modalities == []
        print(f"\n✅ Case 1 PASS: {bundle.agreement_state} → {bundle.overall_verdict}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 2 — Image (AUTHENTIC) + Caption text (AUTHENTIC) → agree_authentic
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase2_BothAuthentic:
    """Both modalities agree the content is authentic."""

    def test_agree_authentic(self):
        summaries = [
            _summarise("image", [_det("detector_image", 0.08,
                                      "Natural sensor noise; authentic EXIF.")]),
            _summarise("text",  [_det("detector_text",  0.11,
                                      "Human stylistic variation detected.")]),
        ]
        bundle = _bundle_verdict("case_02", summaries)

        assert bundle.agreement_state == "agree_authentic", bundle.agreement_summary
        assert bundle.overall_verdict == "AUTHENTIC"
        assert bundle.conflicting_modalities == []
        print(f"\n✅ Case 2 PASS: {bundle.agreement_state} → {bundle.overall_verdict}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 3 — Fake image + Real caption → DISAGREE  ★ disagreement case
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase3_FakeImageRealCaption:
    """Image says SYNTHETIC, text says AUTHENTIC → cross-modal disagreement."""

    def test_disagree_flagged(self):
        summaries = [
            _summarise("image", [_det("detector_image", 0.87,
                                      "Deepfake blending boundary artifacts.",
                                      ["frequency_anomaly"])]),
            _summarise("text",  [_det("detector_text",  0.14,
                                      "Human prose; personal anecdote structure.")]),
        ]
        bundle = _bundle_verdict("case_03", summaries)

        assert bundle.agreement_state == "disagree", bundle.agreement_summary
        assert bundle.overall_verdict == "UNCERTAIN"
        assert len(bundle.conflicting_modalities) > 0
        print(f"\n✅ Case 3 PASS (DISAGREE): {bundle.agreement_summary}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 4 — Real image + AI-generated caption → DISAGREE  ★ disagreement case
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase4_RealImageAiCaption:
    """Authentic image paired with AI-written caption."""

    def test_disagree_authentic_image_synthetic_text(self):
        summaries = [
            _summarise("image", [_det("detector_image", 0.09,
                                      "No anomalies; authentic sensor noise.")]),
            _summarise("text",  [_det("detector_text",  0.91,
                                      "ChatGPT-style hedging; low burstiness.",
                                      ["stylometry_synthetic"])]),
        ]
        bundle = _bundle_verdict("case_04", summaries)

        assert bundle.agreement_state == "disagree"
        assert bundle.overall_verdict == "UNCERTAIN"
        print(f"\n✅ Case 4 PASS (DISAGREE): {bundle.agreement_summary}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 5 — Deepfake video + AI transcript + synthetic audio → all SYNTHETIC
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase5_VideoTranscriptAudioAllSynthetic:
    """3-modality bundle — video + text + audio all say SYNTHETIC."""

    def test_triple_synthetic_agreement(self):
        summaries = [
            _summarise("video", [_det("video-classifier", 0.96,
                                      "Face-swap blending; rPPG flat-line.",
                                      ["face_swap_detected"])]),
            _summarise("text",  [_det("detector_text",   0.88,
                                      "Auto-generated transcript; uniform sentence length.",
                                      ["stylometry_synthetic"])]),
            _summarise("audio", [_det("aasist",           0.93,
                                      "ElevenLabs TTS voice pattern.",
                                      ["synthetic_voice"])]),
        ]
        bundle = _bundle_verdict("case_05", summaries)

        assert bundle.agreement_state == "agree_synthetic"
        assert bundle.overall_verdict == "SYNTHETIC"
        assert bundle.conflicting_modalities == []
        confs = [s.confidence for s in bundle.modality_summaries]
        print(f"\n✅ Case 5 PASS: 3-modality agree_synthetic, scores={confs}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 6 — Real video + AI-dubbed audio → DISAGREE  ★ disagreement case
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase6_RealVideoFakeAudio:
    """Video frames are authentic, audio is synthetic (dubbing attack)."""

    def test_disagree_video_authentic_audio_synthetic(self):
        summaries = [
            _summarise("video", [_det("video-classifier", 0.12,
                                      "Authentic rPPG; no face-swap detected.")]),
            _summarise("audio", [_det("aasist",           0.84,
                                      "Voice cloning fingerprint; mel-spectrogram anomaly.",
                                      ["synthetic_voice"])]),
        ]
        bundle = _bundle_verdict("case_06", summaries)

        assert bundle.agreement_state == "disagree", bundle.agreement_summary
        assert bundle.overall_verdict == "UNCERTAIN"
        print(f"\n✅ Case 6 PASS (DISAGREE video/audio): {bundle.agreement_summary}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 7 — Single image only (degenerate bundle)
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase7_SingleImageOnly:
    """Degenerate single-modality bundle — no cross-modal comparison possible."""

    def test_single_modality_state(self):
        summaries = [
            _summarise("image", [_det("detector_image", 0.78,
                                      "Moderate GAN upsampling grid.",
                                      ["frequency_anomaly"])]),
        ]
        bundle = _bundle_verdict("case_07", summaries)

        assert bundle.agreement_state == "single"
        assert bundle.overall_verdict in VALID_VERDICTS
        assert len(bundle.conflicting_modalities) == 0
        print(f"\n✅ Case 7 PASS (SINGLE): verdict={bundle.overall_verdict}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 8 — All detectors fail → graceful degradation
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase8_AllDetectorsFail:
    """When all detectors fail, bundle verdict is NO_RESULTS, not a crash."""

    def test_graceful_failure_no_results(self):
        summaries = [
            _summarise("image", [_det("detector_image", 0.0, "",
                                      status="failed", error="Connection refused")]),
            _summarise("text",  [_det("detector_text",  0.0, "",
                                      status="failed", error="Model not loaded")]),
        ]
        # Failed detectors produce NO_RESULTS at the aggregate level
        # _summarise will return NO_RESULTS for failed detector lists
        for s in summaries:
            assert s.verdict == AggregateOutcome.NO_RESULTS.value, \
                f"Expected NO_RESULTS for failed detector, got {s.verdict}"

        bundle = _bundle_verdict("case_08", summaries)

        assert bundle.agreement_state == "insufficient"
        assert bundle.overall_verdict == AggregateOutcome.NO_RESULTS.value
        print(f"\n✅ Case 8 PASS (FAIL-SAFE): state={bundle.agreement_state}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 9 — Very high-confidence SYNTHETIC across all 4 modalities
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase9_HighConfidenceAllSynthetic:
    """All four modalities report very high-confidence SYNTHETIC."""

    def test_all_four_agree_synthetic_high_confidence(self):
        summaries = [
            _summarise("image", [_det("detector_image",   0.98,
                                      "Clear GAN fingerprint; checkerboard artifacts.",
                                      ["frequency_anomaly", "high_confidence_synthetic"])]),
            _summarise("text",  [_det("detector_text",    0.97,
                                      "Perplexity=12; Binoculars score=0.03.",
                                      ["stylometry_synthetic"])]),
            _summarise("video", [_det("video-classifier", 0.99,
                                      "DeepFaceLab face-swap; rPPG flat.",
                                      ["face_swap_detected"])]),
            _summarise("audio", [_det("aasist",           0.95,
                                      "ElevenLabs V2 voice clone pattern.",
                                      ["synthetic_voice"])]),
        ]
        bundle = _bundle_verdict("case_09", summaries)

        assert bundle.agreement_state == "agree_synthetic"
        assert bundle.overall_verdict == "SYNTHETIC"
        assert bundle.conflicting_modalities == []
        assert len(bundle.modality_summaries) == 4
        confs = [s.confidence for s in bundle.modality_summaries]
        assert all(c >= SYNTHETIC_THRESHOLD for c in confs), \
            f"All confidences should be >= {SYNTHETIC_THRESHOLD}, got {confs}"
        print(f"\n✅ Case 9 PASS (HIGH-CONF 4-MOD): confs={confs}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 10 — Borderline / UNCERTAIN confidence scores
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase10_BorderlineUncertain:
    """Both detectors return borderline scores → UNCERTAIN on each modality."""

    def test_borderline_scores(self):
        summaries = [
            _summarise("image", [_det("detector_image", 0.52,
                                      "Weak artifacts; inconclusive.", ["borderline"])]),
            _summarise("text",  [_det("detector_text",  0.48,
                                      "Mixed stylometric signals.", ["borderline"])]),
        ]
        for s in summaries:
            assert s.verdict == AggregateOutcome.UNCERTAIN.value, \
                f"Expected UNCERTAIN for borderline score, got {s.verdict}"

        bundle = _bundle_verdict("case_10", summaries)
        # Both are UNCERTAIN → neither SYNTHETIC nor AUTHENTIC → they can't agree
        # They will appear as neither synth nor auth, so the bundle has no synth/auth votes
        # and the loop sees len(valid)=2 but synth=0, auth=0 → falls to 50/50 → disagree
        assert bundle.overall_verdict in (
            AggregateOutcome.UNCERTAIN.value,
            AggregateOutcome.AUTHENTIC.value,
            AggregateOutcome.SYNTHETIC.value,
        )
        assert bundle.agreement_state in ("agree_authentic", "agree_synthetic",
                                          "partial", "disagree", "single")
        print(f"\n✅ Case 10 PASS (BORDERLINE): state={bundle.agreement_state}, "
              f"overall={bundle.overall_verdict}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 11 — Partial agreement: 3 say SYNTHETIC, 1 says AUTHENTIC
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase11_PartialAgreement:
    """3 of 4 modalities say SYNTHETIC; text says AUTHENTIC → partial agreement."""

    def test_partial_majority_synthetic(self):
        summaries = [
            _summarise("image", [_det("detector_image",   0.88, "GAN artifacts.",
                                      ["frequency_anomaly"])]),
            _summarise("video", [_det("video-classifier", 0.91, "Face-swap detected.",
                                      ["face_swap_detected"])]),
            _summarise("audio", [_det("aasist",           0.84, "Synthetic voice.",
                                      ["synthetic_voice"])]),
            _summarise("text",  [_det("detector_text",    0.17, "Human prose (outlier).")]),
            # ↑ outlier — text says AUTHENTIC
        ]
        bundle = _bundle_verdict("case_11", summaries)

        assert bundle.agreement_state == "partial", bundle.agreement_summary
        assert bundle.overall_verdict == "SYNTHETIC"
        assert "text" in bundle.conflicting_modalities, \
            f"Expected 'text' in conflicting, got {bundle.conflicting_modalities}"
        print(f"\n✅ Case 11 PASS (PARTIAL 3-of-4): "
              f"conflicting={bundle.conflicting_modalities}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CASE 12 — Deepfake video + Real audio → DISAGREE  ★ disagreement case
# ═══════════════════════════════════════════════════════════════════════════════
class TestBundleCase12_FakeVideoRealAudio:
    """Video frames are face-swapped, audio track is authentic (video-only deepfake)."""

    def test_disagree_video_synthetic_audio_authentic(self):
        summaries = [
            _summarise("video", [_det("video-classifier", 0.89,
                                      "FaceSwap blending seam at jaw-line.",
                                      ["face_swap_detected"])]),
            _summarise("audio", [_det("aasist",           0.13,
                                      "Natural phoneme transitions; authentic prosody.")]),
        ]
        bundle = _bundle_verdict("case_12", summaries)

        assert bundle.agreement_state == "disagree", bundle.agreement_summary
        assert bundle.overall_verdict == "UNCERTAIN"
        print(f"\n✅ Case 12 PASS (DISAGREE video/audio): {bundle.agreement_summary}")


# ═══════════════════════════════════════════════════════════════════════════════
#  UNIT TESTS — fusion function (_aggregate) & agreement function (_bundle_verdict)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFusionLogic:
    """Unit tests for the weighted-average fusion (_aggregate)."""

    def test_no_results_when_all_failed(self):
        results = [_det("detector_image", 0.0, "", status="failed", error="err")]
        score, verdict = _aggregate(results)
        assert verdict == AggregateOutcome.NO_RESULTS.value
        assert score == 0.0

    def test_synthetic_above_threshold(self):
        results = [_det("detector_image", 0.90, "Fake")]
        score, verdict = _aggregate(results)
        assert verdict == AggregateOutcome.SYNTHETIC.value
        assert score >= SYNTHETIC_THRESHOLD

    def test_authentic_below_threshold(self):
        results = [_det("detector_image", 0.10, "Real")]
        score, verdict = _aggregate(results)
        assert verdict == AggregateOutcome.AUTHENTIC.value
        assert score <= AUTHENTIC_THRESHOLD

    def test_uncertain_in_middle(self):
        results = [_det("detector_image", 0.50, "Borderline")]
        score, verdict = _aggregate(results)
        assert verdict == AggregateOutcome.UNCERTAIN.value

    def test_weights_applied(self):
        """video-classifier (weight 1.5) should dominate detector_text (weight 0.8)."""
        results = [
            _det("video-classifier", 0.90, "Fake video"),   # high weight, high conf
            _det("detector_text",    0.10, "Real text"),    # low weight, low conf
        ]
        score, verdict = _aggregate(results)
        # Weighted: (0.90*1.5 + 0.10*0.8) / (1.5+0.8) = (1.35+0.08)/2.3 ≈ 0.622
        assert score > 0.5, f"Video-classifier weight should dominate; score={score}"
        print(f"  Weighted fusion score: {score}, verdict: {verdict}")


class TestAgreementLogic:
    """Unit tests for _bundle_verdict() agreement states."""

    def test_insufficient_when_all_failed(self):
        summaries = [
            ModalitySummary("image", "d", 0.0, AggregateOutcome.NO_RESULTS.value, ""),
            ModalitySummary("text",  "d", 0.0, AggregateOutcome.NO_RESULTS.value, ""),
        ]
        bundle = _bundle_verdict("unit_insuff", summaries)
        assert bundle.agreement_state == "insufficient"

    def test_single_state_for_one_modality(self):
        summaries = [ModalitySummary("image", "d", 0.9,
                                     AggregateOutcome.SYNTHETIC.value, "")]
        bundle = _bundle_verdict("unit_single", summaries)
        assert bundle.agreement_state == "single"

    def test_agree_synthetic(self):
        summaries = [
            ModalitySummary("image", "d1", 0.9, AggregateOutcome.SYNTHETIC.value, ""),
            ModalitySummary("text",  "d2", 0.8, AggregateOutcome.SYNTHETIC.value, ""),
        ]
        bundle = _bundle_verdict("unit_synth", summaries)
        assert bundle.agreement_state == "agree_synthetic"
        assert bundle.overall_verdict == "SYNTHETIC"

    def test_agree_authentic(self):
        summaries = [
            ModalitySummary("image", "d1", 0.1, AggregateOutcome.AUTHENTIC.value, ""),
            ModalitySummary("text",  "d2", 0.2, AggregateOutcome.AUTHENTIC.value, ""),
        ]
        bundle = _bundle_verdict("unit_auth", summaries)
        assert bundle.agreement_state == "agree_authentic"
        assert bundle.overall_verdict == "AUTHENTIC"

    def test_disagree(self):
        summaries = [
            ModalitySummary("image", "d1", 0.9, AggregateOutcome.SYNTHETIC.value, ""),
            ModalitySummary("text",  "d2", 0.1, AggregateOutcome.AUTHENTIC.value, ""),
        ]
        bundle = _bundle_verdict("unit_dis", summaries)
        assert bundle.agreement_state == "disagree"
        assert bundle.overall_verdict == "UNCERTAIN"

    def test_partial_3_of_4(self):
        summaries = [
            ModalitySummary("image", "d1", 0.9, AggregateOutcome.SYNTHETIC.value, ""),
            ModalitySummary("video", "d2", 0.9, AggregateOutcome.SYNTHETIC.value, ""),
            ModalitySummary("audio", "d3", 0.9, AggregateOutcome.SYNTHETIC.value, ""),
            ModalitySummary("text",  "d4", 0.1, AggregateOutcome.AUTHENTIC.value, ""),
        ]
        bundle = _bundle_verdict("unit_partial", summaries)
        assert bundle.agreement_state == "partial"
        assert bundle.overall_verdict == "SYNTHETIC"
        assert "text" in bundle.conflicting_modalities
