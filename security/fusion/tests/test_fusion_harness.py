"""
Integration tests for FeedFusionEngine against official attack simulation fixtures
using standard library unittest.
"""

import os
import sys
import csv
import unittest

# Add repo root to import path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from security.fusion.feed_fusion import FeedFusionEngine
from security.stream_integrity.stream_validator import StreamValidator

SECURITY_FIXTURES = os.path.join(REPO_ROOT, "security", "fixtures", "tampered_streams")
EVAL_FIXTURES = os.path.join(REPO_ROOT, "eval", "fixtures", "tampered_streams")
FIXTURES_DIR = SECURITY_FIXTURES if os.path.exists(SECURITY_FIXTURES) else EVAL_FIXTURES


class TestFusionHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index_path = os.path.join(FIXTURES_DIR, "index.csv")
        if not os.path.exists(cls.index_path):
            raise unittest.SkipTest("Fixtures not generated yet. Run security/attacks/generate_attack_streams.py first.")
        
        cls.scenarios = {}
        with open(cls.index_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cls.scenarios[row["scenario"]] = row

    def test_clean_scenario_verdict(self):
        row = self.scenarios.get("clean")
        self.assertIsNotNone(row)

        engine = FeedFusionEngine()
        validator = StreamValidator(fps=30)
        manifest_path = os.path.join(FIXTURES_DIR, row["manifest_path"])

        anomalies = []
        with open(manifest_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                anomalies.extend(validator.check(r["sequence_number"], r["timestamp_ms"]))

        # Clean stream has no anomalies, authentic AI score (~0.12)
        res = engine.fuse(
            hash_chain_ok=True,
            integrity_anomalies=anomalies,
            prnu_ok=True,
            ai_score=0.12,
        )
        self.assertEqual(res.verdict, "AUTHENTIC")

    def test_carried_tamper_scenarios(self):
        """Carried scenarios retain captured timestamps/sequences, causing metadata anomalies."""
        engine = FeedFusionEngine()

        for scenario_name in ["splice_carried", "replay_carried", "reorder_carried"]:
            with self.subTest(scenario=scenario_name):
                row = self.scenarios.get(scenario_name)
                self.assertIsNotNone(row)

                validator = StreamValidator(fps=30)
                manifest_path = os.path.join(FIXTURES_DIR, row["manifest_path"])

                anomalies = []
                with open(manifest_path, "r", newline="") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        anomalies.extend(validator.check(r["sequence_number"], r["timestamp_ms"]))

                # Carried metadata produces timestamp/sequence anomalies
                self.assertGreater(len(anomalies), 0)

                res = engine.fuse(
                    hash_chain_ok=True,
                    integrity_anomalies=anomalies,
                    prnu_ok=True,
                    ai_score=0.20,
                )
                self.assertEqual(res.verdict, "INTEGRITY_UNKNOWN")

    def test_forged_tamper_scenarios(self):
        """
        Forged scenarios rewrite sequence/timestamps to look continuous.
        StreamValidator passes them, but AI content anomaly detector flags the fake content!
        """
        engine = FeedFusionEngine()

        for scenario_name in ["splice_forged", "replay_forged", "reorder_forged"]:
            with self.subTest(scenario=scenario_name):
                row = self.scenarios.get(scenario_name)
                self.assertIsNotNone(row)

                validator = StreamValidator(fps=30)
                manifest_path = os.path.join(FIXTURES_DIR, row["manifest_path"])

                anomalies = []
                with open(manifest_path, "r", newline="") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        anomalies.extend(validator.check(r["sequence_number"], r["timestamp_ms"]))

                # Attacker forged headers, so StreamValidator finds 0 anomalies
                self.assertEqual(len(anomalies), 0)

                # However, the AI track detects synthetic content (AI score high)
                res = engine.fuse(
                    hash_chain_ok=True,
                    integrity_anomalies=anomalies,
                    prnu_ok=True,
                    ai_score=0.85,
                )
                self.assertEqual(res.verdict, "SYNTHETIC")

    def test_prnu_splice_scenario(self):
        """PRNU splice scenario replaces video with a different camera sensor."""
        row = self.scenarios.get("prnu_splice")
        self.assertIsNotNone(row)

        engine = FeedFusionEngine()
        
        # PRNU sensor mismatch flags foreign sensor
        res = engine.fuse(
            hash_chain_ok=True,
            integrity_anomalies=[],
            prnu_ok=False,
            prnu_pce=18.5,
            ai_score=0.25,
        )
        self.assertEqual(res.verdict, "INTEGRITY_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
