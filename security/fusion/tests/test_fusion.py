"""
Unit tests for FeedFusionEngine using standard library unittest (works with or without pytest).
"""

import unittest
from security.fusion.feed_fusion import FeedFusionEngine


class TestFeedFusionEngine(unittest.TestCase):
    def setUp(self):
        self.engine = FeedFusionEngine(w_integrity=0.5, w_ai=0.5)

    def test_clean_authentic_feed(self):
        """Clean stream + low AI anomaly score -> AUTHENTIC in Tier 2."""
        res = self.engine.fuse(
            hash_chain_ok=True,
            integrity_anomalies=[],
            prnu_ok=True,
            prnu_pce=120.0,
            ai_score=0.15,
        )
        self.assertEqual(res.verdict, "AUTHENTIC")
        self.assertTrue(res.integrity_ok)
        self.assertEqual(res.integrity_score, 0.0)
        self.assertEqual(res.tier, 2)
        # Tiered fusion: clean integrity does not dilute AI score by 50%
        self.assertEqual(res.combined_score, 0.15)

    def test_clean_feed_synthetic_content(self):
        """
        Stream metadata and hash chain intact (e.g. forged metadata or pre-encoded deepfake),
        but AI content score is high -> SYNTHETIC.
        """
        res = self.engine.fuse(
            hash_chain_ok=True,
            integrity_anomalies=[],
            prnu_ok=True,
            prnu_pce=110.0,
            ai_score=0.88,
        )
        self.assertEqual(res.verdict, "SYNTHETIC")
        self.assertTrue(res.integrity_ok)
        self.assertEqual(res.ai_score, 0.88)

    def test_hash_break_yields_integrity_unknown(self):
        """
        Broken hash chain must NEVER be authentic, even if AI score is 0.0.
        """
        res = self.engine.fuse(
            hash_chain_ok=False,
            integrity_anomalies=[],
            prnu_ok=True,
            prnu_pce=95.0,
            ai_score=0.10,
        )
        self.assertEqual(res.verdict, "INTEGRITY_UNKNOWN")
        self.assertFalse(res.integrity_ok)
        self.assertGreaterEqual(res.integrity_score, 1.0)

    def test_timestamp_anomalies_yield_integrity_unknown(self):
        """
        Stream with timestamp gaps/jumps/regressions -> INTEGRITY_UNKNOWN.
        """
        anomalies = ["gap: seq jump from 12 to 18", "timestamp_jump: 200ms delta"]
        res = self.engine.fuse(
            hash_chain_ok=True,
            integrity_anomalies=anomalies,
            prnu_ok=True,
            prnu_pce=80.0,
            ai_score=0.20,
        )
        self.assertEqual(res.verdict, "INTEGRITY_UNKNOWN")
        self.assertFalse(res.integrity_ok)
        self.assertEqual(res.evidence["anomaly_count"], 2)

    def test_prnu_sensor_failure_yields_integrity_unknown(self):
        """
        Foreign camera sensor detected via PRNU PCE drop -> INTEGRITY_UNKNOWN.
        """
        res = self.engine.fuse(
            hash_chain_ok=True,
            integrity_anomalies=[],
            prnu_ok=False,
            prnu_pce=14.2,
            ai_score=0.15,
        )
        self.assertEqual(res.verdict, "INTEGRITY_UNKNOWN")
        self.assertFalse(res.integrity_ok)

    def test_uncertain_range(self):
        """
        Clean integrity but intermediate AI score (between authentic and synthetic) -> UNCERTAIN.
        """
        res = self.engine.fuse(
            hash_chain_ok=True,
            integrity_anomalies=[],
            prnu_ok=True,
            prnu_pce=90.0,
            ai_score=0.50,
        )
        self.assertEqual(res.verdict, "UNCERTAIN")
        self.assertTrue(res.integrity_ok)
        self.assertEqual(res.combined_score, 0.50)
        self.assertEqual(res.ai_score, 0.50)

    def test_tier1_prnu_pce_threshold_enforced(self):
        """PCE below threshold triggers Tier 1 hard alert even if prnu_ok boolean is True."""
        res = self.engine.fuse(
            hash_chain_ok=True,
            integrity_anomalies=[],
            prnu_ok=True,
            prnu_pce=35.0,  # below default 50.0 threshold
            ai_score=0.10,
        )
        self.assertEqual(res.verdict, "INTEGRITY_UNKNOWN")
        self.assertFalse(res.integrity_ok)
        self.assertEqual(res.tier, 1)

    def test_hysteresis_suppresses_borderline_flapping(self):
        """
        Consecutive scores drifting around 0.39-0.42 remain in AUTHENTIC
        state without flapping to UNCERTAIN.
        """
        engine = FeedFusionEngine(authentic_threshold=0.40, hysteresis_margin=0.05)

        # Window 0: initial authentic observation establishes AUTHENTIC state
        res0 = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.33)
        self.assertEqual(res0.verdict, "AUTHENTIC")

        # Window 1: score rises to 0.42 (above 0.40 threshold, but within 0.40 + 0.05 margin)
        res1 = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.42)
        self.assertEqual(res1.verdict, "AUTHENTIC")
        self.assertTrue(res1.hysteresis_applied)

        # Window 2: score dips slightly to 0.39
        res2 = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.39)
        self.assertEqual(res2.verdict, "AUTHENTIC")

        # Window 3: score spikes past upper threshold + margin (0.65 + 0.05 = 0.70)
        res3 = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.75)
        self.assertEqual(res3.verdict, "SYNTHETIC")

        # Window 4: score dips to 0.62 (below synthetic_threshold 0.65, but within 0.65 - 0.05 margin)
        res4 = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.62)
        self.assertEqual(res4.verdict, "SYNTHETIC")
        self.assertTrue(res4.hysteresis_applied)

    def test_calibrator_integration(self):
        """Verifies that a custom calibrator function scales raw scores in Tier 2."""
        # Simple calibrator that scales raw edge scores by 0.5
        calibrator = lambda raw: raw * 0.5
        engine = FeedFusionEngine(calibrator=calibrator)

        # Raw score 0.40 calibrated to 0.20 -> clearly AUTHENTIC
        res = engine.fuse(hash_chain_ok=True, integrity_anomalies=[], prnu_ok=True, ai_score=0.40)
        self.assertEqual(res.verdict, "AUTHENTIC")
        self.assertEqual(res.calibrated_score, 0.20)
        self.assertEqual(res.combined_score, 0.20)


if __name__ == "__main__":
    unittest.main()
