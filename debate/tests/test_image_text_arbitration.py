"""
AEGIS Debate Layer — Image & Text Intra-Modality Arbitration Test Suite.
========================================================================
Covers 44 test cases (22 image, 22 text) testing:
- Image: MIRROR vs. Frequency vs. EXIF arbitration (Rules 7A, 7B, 7C, 7D).
- Text: Fine-tuned Desklib vs. Stylometric vs. Perplexity arbitration (Rules 8A, 8B, 8C, 8D).
- Deliberate intra-modality disagreements and edge-case handling.
"""

import sys
import unittest
from pathlib import Path

# Ensure repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from debate.arbitrator import JudgeArbitrator
from debate.claim_wrapper import wrap_detector_response
from debate.schemas import (
    ClaimPolarity,
    EvidenceDomain,
    ForensicClaim,
    JudgeVerdictClass,
    ObservationalMetrics,
    ImageForensicMetrics,
    TextForensicMetrics,
)


def _make_claim(
    detector_id: str,
    domain: EvidenceDomain,
    polarity: ClaimPolarity,
    confidence: float,
    claim_text: str,
    flags=None,
    metrics=None,
) -> ForensicClaim:
    return ForensicClaim(
        claim_id=f"clm-{detector_id}-test",
        job_id="test-job-42",
        detector_id=detector_id,
        model_version="v1.0",
        domain=domain,
        polarity=polarity,
        confidence=confidence,
        raw_score=confidence,
        claim=claim_text,
        flags=flags or [],
        observational_metrics=metrics,
    )


# ============================================================================
# IMAGE INTRA-MODALITY ARBITRATION TESTS (22 CASES)
# ============================================================================

class TestImageArbitration(unittest.TestCase):
    def setUp(self):
        self.arbitrator = JudgeArbitrator()

    # 1. Consensus Authentic: clean model, clean frequency, valid EXIF
    def test_image_01_consensus_authentic(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.AUTHENTIC, 0.10, "Natural photo structure"),
            _make_claim("image-frequency", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.AUTHENTIC, 0.12, "Clean power spectrum"),
            _make_claim("image-exif", EvidenceDomain.METADATA_INTEGRITY, ClaimPolarity.AUTHENTIC, 0.05, "Camera EXIF valid"),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)
        self.assertLessEqual(verdict.calibrated_score, 0.35)

    # 2. Consensus Synthetic: synthetic model, frequency anomaly, missing EXIF
    def test_image_02_consensus_synthetic(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.92, "Synthetic artifacts"),
            _make_claim("image-frequency", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.88, "Grid artifacts", ["frequency_anomaly"]),
            _make_claim("image-exif", EvidenceDomain.METADATA_INTEGRITY, ClaimPolarity.INCONCLUSIVE, 0.55, "No camera metadata", ["exif_missing"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)
        self.assertGreaterEqual(verdict.calibrated_score, 0.85)

    # 3. Social media stripped real photo: clean model, clean frequency, missing EXIF -> AUTHENTIC (Rule 7A)
    def test_image_03_social_media_stripped_exif_authentic(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.AUTHENTIC, 0.12, "Natural visual structure"),
            _make_claim("image-frequency", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.AUTHENTIC, 0.15, "Clean spectrum"),
            _make_claim("image-exif", EvidenceDomain.METADATA_INTEGRITY, ClaimPolarity.SYNTHETIC, 0.70, "Suspicious missing metadata", ["exif_missing"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)
        self.assertTrue(any("Rule 7A" in (adj.discount_reason or "") for adj in verdict.adjudications if adj.detector_id == "image-exif"))

    # 4. Spoofed EXIF on deepfake: synthetic model, clean EXIF -> SYNTHETIC (Rule 7B)
    def test_image_04_spoofed_exif_deepfake(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.88, "Deepfake manipulation"),
            _make_claim("image-frequency", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.75, "Spectral irregularity"),
            _make_claim("image-exif", EvidenceDomain.METADATA_INTEGRITY, ClaimPolarity.AUTHENTIC, 0.10, "Pasted Canon EOS metadata"),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)
        self.assertTrue(any("Rule 7B" in (adj.discount_reason or "") for adj in verdict.adjudications if adj.detector_id == "image-exif"))

    # 5. Corroborated frequency upsampling grid artifact -> high certainty SYNTHETIC (Rule 7C)
    def test_image_05_corroborated_frequency_grid(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.82, "Diffusion artifacts"),
            _make_claim("image-frequency", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.89, "Upsampling grid", ["frequency_anomaly"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)
        self.assertGreaterEqual(verdict.calibrated_score, 0.90)

    # 6. Isolated JPEG recompression grid: authentic visual + frequency anomaly -> Rule 7D attenuates
    def test_image_06_isolated_jpeg_frequency_anomaly(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.AUTHENTIC, 0.18, "Clean photo structure"),
            _make_claim("image-frequency", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.75, "JPEG 8x8 block artifacts", ["frequency_anomaly"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)
        self.assertTrue(any("Rule 7D" in (adj.discount_reason or "") for adj in verdict.adjudications if adj.detector_id == "image-frequency"))

    # 7. Pure GAN generator: strong frequency grid + missing EXIF
    def test_image_07_gan_generator_artifacts(self):
        resp = {"confidence": 0.91, "flags": ["frequency_anomaly", "exif_missing"], "raw_score": 0.91}
        claim = wrap_detector_response("detector_image", resp)
        verdict = self.arbitrator.arbitrate([claim])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)
        self.assertIn("frequency-domain grid artifacts present, no camera metadata", claim.claim)

    # 8. Diffusion generator with latent decode artifacts
    def test_image_08_diffusion_latent_artifacts(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.87, "Diffusion latent artifacts"),
            _make_claim("image-frequency", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.82, "High-frequency ringing", ["frequency_anomaly"]),
            _make_claim("image-exif", EvidenceDomain.METADATA_INTEGRITY, ClaimPolarity.INCONCLUSIVE, 0.55, "Missing EXIF", ["exif_missing"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)
        self.assertGreaterEqual(verdict.calibrated_score, 0.85)

    # 9. Authentic DSLR photo with intact metadata
    def test_image_09_dslr_photo(self):
        resp = {"confidence": 0.08, "flags": [], "raw_score": 0.08}
        claim = wrap_detector_response("detector_image", resp)
        verdict = self.arbitrator.arbitrate([claim])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)
        self.assertIn("clean frequency spectrum and intact camera metadata", claim.claim)

    # 10. Authentic smartphone photo with computational HDR
    def test_image_10_smartphone_hdr_photo(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.AUTHENTIC, 0.14, "Natural portrait"),
            _make_claim("image-frequency", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.AUTHENTIC, 0.20, "Mild sharpening"),
            _make_claim("image-exif", EvidenceDomain.METADATA_INTEGRITY, ClaimPolarity.AUTHENTIC, 0.05, "Apple iPhone 15 Pro EXIF"),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)

    # 11. Heavily compressed social media real photo
    def test_image_11_compressed_social_real(self):
        resp = {"confidence": 0.25, "flags": ["exif_missing"], "raw_score": 0.25}
        claim = wrap_detector_response("detector_image", resp)
        verdict = self.arbitrator.arbitrate([claim])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)

    # 12. Deliberate disagreement: Model synthetic (0.88) vs clean frequency (0.15) vs EXIF valid (0.10)
    def test_image_12_disagreement_model_overrides_metadata(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.88, "Deepfake faceswap"),
            _make_claim("image-frequency", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.AUTHENTIC, 0.15, "Clean frequency"),
            _make_claim("image-exif", EvidenceDomain.METADATA_INTEGRITY, ClaimPolarity.AUTHENTIC, 0.10, "Valid EXIF"),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)

    # 13. Deliberate disagreement: Model authentic (0.12) vs frequency anomaly (0.85) vs EXIF missing (0.55)
    def test_image_13_disagreement_model_overrides_frequency_noise(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.AUTHENTIC, 0.12, "Authentic face"),
            _make_claim("image-frequency", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.85, "Grid anomaly", ["frequency_anomaly"]),
            _make_claim("image-exif", EvidenceDomain.METADATA_INTEGRITY, ClaimPolarity.INCONCLUSIVE, 0.55, "No EXIF", ["exif_missing"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)

    # 14. Deliberate disagreement: Borderline model (0.50) + frequency anomaly (0.80)
    def test_image_14_borderline_model_with_frequency_anomaly(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.INCONCLUSIVE, 0.50, "Borderline spatial"),
            _make_claim("image-frequency", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.SYNTHETIC, 0.80, "Grid artifact", ["frequency_anomaly"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertGreaterEqual(verdict.calibrated_score, 0.50)

    # 15. Borderline model (0.50) + EXIF missing (0.55)
    def test_image_15_borderline_with_missing_exif(self):
        claims = [
            _make_claim("image-mirror", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.INCONCLUSIVE, 0.50, "Borderline"),
            _make_claim("image-exif", EvidenceDomain.METADATA_INTEGRITY, ClaimPolarity.INCONCLUSIVE, 0.55, "No EXIF", ["exif_missing"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertIn(verdict.final_verdict, (JudgeVerdictClass.INTEGRITY_UNKNOWN, JudgeVerdictClass.UNCERTAIN))

    # 16. Inconclusive image input (coverage gap)
    def test_image_16_coverage_gap(self):
        claim = _make_claim("detector_image", EvidenceDomain.IMAGE_FORENSIC, ClaimPolarity.NOT_APPLICABLE, 0.50, "Corrupt JPEG", ["not_applicable"])
        verdict = self.arbitrator.arbitrate([claim])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.INTEGRITY_UNKNOWN)

    # 17. Single composite detector_image authentic with exif_missing
    def test_image_17_single_detector_authentic_exif_missing(self):
        resp = {"confidence": 0.20, "flags": ["exif_missing"], "raw_score": 0.20}
        claim = wrap_detector_response("detector_image", resp)
        verdict = self.arbitrator.arbitrate([claim])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)

    # 18. Single composite detector_image synthetic with frequency_anomaly & exif_missing
    def test_image_18_single_detector_synthetic_both_flags(self):
        resp = {"confidence": 0.88, "flags": ["frequency_anomaly", "exif_missing"], "raw_score": 0.88}
        claim = wrap_detector_response("detector_image", resp)
        verdict = self.arbitrator.arbitrate([claim])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)

    # 19. Claim template verification: grid artifacts + no metadata
    def test_image_19_template_grid_and_no_metadata(self):
        resp = {"confidence": 0.85, "flags": ["frequency_anomaly", "exif_missing"]}
        claim = wrap_detector_response("detector_image", resp)
        self.assertIn("frequency-domain grid artifacts present, no camera metadata", claim.claim)

    # 20. Claim template verification: grid artifacts + camera metadata intact
    def test_image_20_template_grid_and_metadata_intact(self):
        resp = {"confidence": 0.78, "flags": ["frequency_anomaly"]}
        claim = wrap_detector_response("detector_image", resp)
        self.assertIn("frequency-domain grid artifacts present, camera metadata intact", claim.claim)

    # 21. Subclaims ensemble synthetic test
    def test_image_21_subclaims_ensemble_synthetic(self):
        c1 = wrap_detector_response("image-mirror", {"confidence": 0.90})
        c2 = wrap_detector_response("image-frequency", {"confidence": 0.85, "flags": ["frequency_anomaly"]})
        c3 = wrap_detector_response("image-exif", {"confidence": 0.55, "flags": ["exif_missing"]})
        verdict = self.arbitrator.arbitrate([c1, c2, c3])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)

    # 22. Subclaims ensemble authentic test
    def test_image_22_subclaims_ensemble_authentic(self):
        c1 = wrap_detector_response("image-mirror", {"confidence": 0.10})
        c2 = wrap_detector_response("image-frequency", {"confidence": 0.15})
        c3 = wrap_detector_response("image-exif", {"confidence": 0.08})
        verdict = self.arbitrator.arbitrate([c1, c2, c3])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)


# ============================================================================
# TEXT INTRA-MODALITY ARBITRATION TESTS (22 CASES)
# ============================================================================

class TestTextArbitration(unittest.TestCase):
    def setUp(self):
        self.arbitrator = JudgeArbitrator()

    # 1. Consensus Authentic: human semantic score (0.10), high vocabulary diversity, variable sentence length
    def test_text_01_consensus_authentic(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.AUTHENTIC, 0.08, "Human prose semantics"),
            _make_claim("text-stylometry", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.AUTHENTIC, 0.12, "Natural sentence burstiness"),
            _make_claim("text-perplexity", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.AUTHENTIC, 0.15, "Diverse perplexity distribution"),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)
        self.assertLessEqual(verdict.calibrated_score, 0.35)

    # 2. Consensus Synthetic: Desklib (0.95), uniform low perplexity, low sentence length variation
    def test_text_02_consensus_synthetic(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.95, "LLM generated text"),
            _make_claim("text-stylometry", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.88, "Low sentence variance", ["stylometry_synthetic"]),
            _make_claim("text-perplexity", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.92, "Uniform low perplexity", ["uniform_low_perplexity"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)
        self.assertGreaterEqual(verdict.calibrated_score, 0.92)

    # 3. Technical / Academic Paper (Jargon Exception): Desklib authentic (0.15), low vocabulary diversity flag -> AUTHENTIC (Rule 8B)
    def test_text_03_technical_academic_jargon_authentic(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.AUTHENTIC, 0.14, "Human academic prose"),
            _make_claim("text-stylometry", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.75, "Low lexical diversity from technical jargon", ["low_vocabulary_diversity"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)
        self.assertTrue(any("Rule 8B" in (adj.discount_reason or "") for adj in verdict.adjudications if adj.detector_id == "text-stylometry"))

    # 4. Legal Contract / Statute: Repetitive phrasing -> AUTHENTIC (Rule 8B)
    def test_text_04_legal_contract_repetition(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.AUTHENTIC, 0.18, "Human statutory drafting"),
            _make_claim("text-stylometry", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.80, "Boilerplate repetition", ["high_ngram_repetition"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)

    # 5. Paraphrased AI text: Desklib synthetic (0.85), high sentence length variation -> SYNTHETIC (Rule 8C)
    def test_text_05_paraphrased_ai_text(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.85, "Deep semantic neural synthetic markers"),
            _make_claim("text-stylometry", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.AUTHENTIC, 0.25, "Humanized burstiness"),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)
        self.assertTrue(any("Rule 8C" in (adj.discount_reason or "") for adj in verdict.adjudications if adj.detector_id == "text-stylometry"))

    # 6. Polished Claude/GPT essay: Desklib synthetic (0.92), low perplexity, low sentence variation
    def test_text_06_polished_gpt_essay(self):
        resp = {
            "confidence": 0.92,
            "flags": ["uniform_low_perplexity", "low_sentence_length_variation"],
            "perplexity_variance": 0.10,
            "sentence_length_cov": 0.20,
        }
        claim = wrap_detector_response("detector_text", resp)
        verdict = self.arbitrator.arbitrate([claim])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)
        self.assertIn("uniformly low perplexity, low sentence-length variation", claim.claim)

    # 7. Direct LLM output: Desklib (0.96) + uniform low perplexity -> score >= 0.92
    def test_text_07_direct_llm_output(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.96, "Direct LLM synthesis"),
            _make_claim("text-perplexity", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.94, "Flat perplexity", ["uniform_low_perplexity"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)
        self.assertGreaterEqual(verdict.calibrated_score, 0.92)

    # 8. Human Reddit casual comment
    def test_text_08_human_reddit_comment(self):
        resp = {"confidence": 0.05, "flags": [], "raw_score": 0.05}
        claim = wrap_detector_response("detector_text", resp)
        verdict = self.arbitrator.arbitrate([claim])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)
        self.assertIn("natural syntactic burstiness and lexical diversity", claim.claim)

    # 9. Human Wikipedia article
    def test_text_09_human_wikipedia_article(self):
        resp = {"confidence": 0.15, "flags": [], "raw_score": 0.15}
        claim = wrap_detector_response("detector_text", resp)
        verdict = self.arbitrator.arbitrate([claim])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)

    # 10. Short query / snippet coverage gap
    def test_text_10_short_query_gap(self):
        claim = _make_claim("detector_text", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.NOT_APPLICABLE, 0.50, "Insufficient token count", ["not_applicable"])
        verdict = self.arbitrator.arbitrate([claim])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.INTEGRITY_UNKNOWN)

    # 11. Deliberate disagreement: Desklib authentic (0.10) vs stylometry synthetic (0.80) -> Rule 8B
    def test_text_11_disagreement_desklib_authentic_overrides_repetitive_style(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.AUTHENTIC, 0.10, "Human semantics"),
            _make_claim("text-stylometry", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.80, "Repetitive style", ["low_vocabulary_diversity"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)

    # 12. Deliberate disagreement: Desklib synthetic (0.90) vs stylometry authentic (0.20) -> Rule 8C
    def test_text_12_disagreement_desklib_synthetic_overrides_diverse_style(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.90, "Deep synthetic embeddings"),
            _make_claim("text-stylometry", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.AUTHENTIC, 0.20, "Burstiness engineered"),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)

    # 13. Deliberate disagreement: Desklib borderline (0.50) + stylometry synthetic (0.85)
    def test_text_13_borderline_desklib_stylometry_synthetic_tiebreaker(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.INCONCLUSIVE, 0.50, "Borderline classifier"),
            _make_claim("text-stylometry", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.85, "Repetitive phrasing", ["stylometry_synthetic"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertGreaterEqual(verdict.calibrated_score, 0.50)

    # 14. Deliberate disagreement: Desklib borderline (0.50) + stylometry authentic (0.15)
    def test_text_14_borderline_desklib_stylometry_authentic_tiebreaker(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.INCONCLUSIVE, 0.50, "Borderline classifier"),
            _make_claim("text-stylometry", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.AUTHENTIC, 0.15, "Human burstiness"),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertLessEqual(verdict.calibrated_score, 0.50)

    # 15. Desklib synthetic (0.75) vs perplexity authentic (0.25)
    def test_text_15_desklib_vs_perplexity_disagreement(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.75, "Synthetic neural features"),
            _make_claim("text-perplexity", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.AUTHENTIC, 0.25, "Variable perplexity"),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)

    # 16. Desklib authentic (0.25) vs perplexity synthetic (0.75)
    def test_text_16_desklib_authentic_vs_perplexity_synthetic(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.AUTHENTIC, 0.25, "Authentic human prose"),
            _make_claim("text-perplexity", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.75, "Low perplexity"),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertLessEqual(verdict.calibrated_score, 0.50)

    # 17. Tri-signal synthetic alignment -> high certainty
    def test_text_17_tri_signal_synthetic_alignment(self):
        claims = [
            _make_claim("text-desklib", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.88, "Synthetic"),
            _make_claim("text-stylometry", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.82, "Repetitive", ["stylometry_synthetic"]),
            _make_claim("text-perplexity", EvidenceDomain.TEXT_FORENSIC, ClaimPolarity.SYNTHETIC, 0.90, "Flat", ["uniform_low_perplexity"]),
        ]
        verdict = self.arbitrator.arbitrate(claims)
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)
        self.assertGreaterEqual(verdict.calibrated_score, 0.92)

    # 18. Claim template verification: uniform perplexity + low sentence variance
    def test_text_18_template_perplexity_and_sentence_cov(self):
        resp = {"confidence": 0.88, "flags": ["uniform_low_perplexity", "low_sentence_length_variation"]}
        claim = wrap_detector_response("detector_text", resp)
        self.assertIn("uniformly low perplexity, low sentence-length variation", claim.claim)

    # 19. Claim template verification: low vocab diversity
    def test_text_19_template_vocab_diversity(self):
        resp = {"confidence": 0.75, "flags": ["low_vocabulary_diversity"]}
        claim = wrap_detector_response("detector_text", resp)
        self.assertIn("low vocabulary diversity and repetitive stylometric pacing", claim.claim)

    # 20. Claim template verification: n-gram repetition
    def test_text_20_template_ngram_repetition(self):
        resp = {"confidence": 0.79, "flags": ["high_ngram_repetition"]}
        claim = wrap_detector_response("detector_text", resp)
        self.assertIn("high n-gram repetition across discourse segments", claim.claim)

    # 21. Subclaims ensemble synthetic
    def test_text_21_subclaims_ensemble_synthetic(self):
        c1 = wrap_detector_response("text-desklib", {"confidence": 0.92})
        c2 = wrap_detector_response("text-stylometry", {"confidence": 0.80, "flags": ["stylometry_synthetic"]})
        c3 = wrap_detector_response("text-perplexity", {"confidence": 0.85, "flags": ["uniform_low_perplexity"]})
        verdict = self.arbitrator.arbitrate([c1, c2, c3])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.SYNTHETIC)

    # 22. Subclaims ensemble authentic
    def test_text_22_subclaims_ensemble_authentic(self):
        c1 = wrap_detector_response("text-desklib", {"confidence": 0.08})
        c2 = wrap_detector_response("text-stylometry", {"confidence": 0.15})
        c3 = wrap_detector_response("text-perplexity", {"confidence": 0.10})
        verdict = self.arbitrator.arbitrate([c1, c2, c3])
        self.assertEqual(verdict.final_verdict, JudgeVerdictClass.AUTHENTIC)


if __name__ == "__main__":
    unittest.main()
