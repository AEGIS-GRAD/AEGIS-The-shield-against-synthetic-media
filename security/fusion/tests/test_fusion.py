"""
Unit tests for FeedFusionEngine using standard library unittest (works with or without pytest).
"""

import unittest
from security.fusion.feed_fusion import FeedFusionEngine


class TestFeedFusionEngine(unittest.TestCase):
    def setUp(self):
        self.engine = FeedFusionEngine(w_integrity=0.5, w_ai=0.5)

    def test_clean_authentic_feed(self):
        """Clean stream + low AI anomaly score -> AUTHENTIC."""
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
        self.assertAlmostEqual(res.combined_score, 0.075)

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
        Clean integrity but intermediate AI score (between 0.35 and 0.65) -> UNCERTAIN.
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
        self.assertAlmostEqual(res.combined_score, 0.25)
        self.assertEqual(res.ai_score, 0.50)


if __name__ == "__main__":
    unittest.main()
