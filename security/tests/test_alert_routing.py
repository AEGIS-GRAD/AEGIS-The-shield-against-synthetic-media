"""
End-to-End Verification Test Suite: Incident-Response & SIEM Alert Routing
==========================================================================
Demonstrates end-to-end integration connecting triggered anomalies from the
AI track's FeedFusionEngine to SIEM/SOC-style destinations (Wazuh, Webhook,
Evidence Vault, File Logs) compliant with Week 2's incident response workflow.
"""

import hmac
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from security.fusion.feed_fusion import FeedFusionEngine
from security.stream_integrity.stream_validator import StreamValidator, Anomaly
from security.forensics.evidence_vault import SurveillanceEvidenceVault
from security.incident_response.alert_router import (
    AEGISAlert,
    CameraMetadata,
    EvidenceBundle,
    AlertRouter,
    MemoryAlertDestination,
    FileAlertDestination,
    WebhookAlertDestination,
    EvidenceVaultDestination,
    WAZUH_RULE_MAP,
)


class TestIncidentResponseAlertRouting(unittest.TestCase):
    """
    Test suite validating the complete incident response alert workflow
    from detection/fusion to SIEM/SOC destination receipt.
    """

    def setUp(self):
        self.mem_dest = MemoryAlertDestination()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "wazuh_alerts.jsonl"
        self.file_dest = FileAlertDestination(self.log_file)
        self.vault = SurveillanceEvidenceVault(vault_dir=Path(self.temp_dir.name) / "vault")
        self.vault_dest = EvidenceVaultDestination(vault_instance=self.vault)

        self.router = AlertRouter(
            destinations=[self.mem_dest, self.file_dest, self.vault_dest],
            min_severity="P4_INFO",
            dedup_window_seconds=1.0,
        )

        self.engine = FeedFusionEngine(
            w_integrity=0.5,
            w_ai=0.5,
            synthetic_threshold=0.65,
            authentic_threshold=0.35,
            alert_router=self.router,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Actionable Alert Schema Contract Verification
    # ─────────────────────────────────────────────────────────────────────────

    def test_alert_schema_contract_compliance(self):
        """
        Validates that AEGISAlert strictly satisfies all required fields
        and constraints defined in AEGIS-SOP-IR-001 Section 5.1 JSON Schema.
        """
        cam = CameraMetadata(
            camera_id="cam-north-gate-02",
            ip_address="10.20.1.42",
            location="Perimeter North Gate",
            certificate_fingerprint="SHA256:7e8b91a24d55c911832b49",
        )
        bundle = EvidenceBundle(
            forensic_hash="8f835b7194f4c281729b827e8bcda1a3e895471c26b7139177bc",
            frame_sequence_range=[100, 130],
            pce_score=14.5,
            pce_threshold=50.0,
            broken_at_sequence=112,
            model_contributions={"video-classifier": 0.94, "rppg": 0.81},
            technical_detail="Hardware sensor mismatch and facial boundary anomalies detected.",
        )
        alert = AEGISAlert(
            severity="P1_CRITICAL",
            camera_metadata=cam,
            threat_classification="PRNU_SENSOR_MISMATCH",
            anomaly_score=0.92,
            evidence_bundle=bundle,
            recommended_actions=["Sever live ingestion TCP socket immediately"],
            wazuh_rule_id=100201,
            containment_action="SOCKET_SEVERED",
        )

        # Validate required field presences
        d = alert.model_dump()
        self.assertIn("alert_id", d)
        self.assertIn("timestamp_iso", d)
        self.assertEqual(d["severity"], "P1_CRITICAL")
        self.assertEqual(d["camera_metadata"]["camera_id"], "cam-north-gate-02")
        self.assertEqual(d["threat_classification"], "PRNU_SENSOR_MISMATCH")
        self.assertAlmostEqual(d["anomaly_score"], 0.92)
        self.assertEqual(d["evidence_bundle"]["pce_score"], 14.5)
        self.assertEqual(d["evidence_bundle"]["broken_at_sequence"], 112)
        self.assertEqual(d["evidence_bundle"]["frame_sequence_range"], [100, 130])
        self.assertEqual(len(d["recommended_actions"]), 1)
        self.assertEqual(d["wazuh_rule_id"], 100201)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Wazuh SIEM NDJSON Formatting & Injection Hardening (CVE-2026-56699)
    # ─────────────────────────────────────────────────────────────────────────

    def test_wazuh_ndjson_formatting_and_sanitization(self):
        """
        Validates Wazuh NDJSON serialization format and sanitization of newline
        injection characters (SR-14, NIST SP 800-61).
        """
        cam = CameraMetadata(camera_id="cam-01")
        bundle = EvidenceBundle(
            forensic_hash="abcd1234abcd1234abcd1234abcd1234abcd1234",
            frame_sequence_range=[1, 10],
            technical_detail="Injection attempt:\n--MALICIOUS-NDJSON-INJECTION--\r\nfake_log: true",
        )
        alert = AEGISAlert(
            severity="P1_CRITICAL",
            camera_metadata=cam,
            threat_classification="CRYPTOGRAPHIC_HASH_MISMATCH",
            anomaly_score=0.99,
            evidence_bundle=bundle,
        )

        ndjson = alert.to_wazuh_ndjson()
        # Must be exactly one trailing newline and no interior newlines
        lines = ndjson.splitlines()
        self.assertEqual(len(lines), 1, "Interior newlines must be sanitized to defeat NDJSON injection!")

        # Must parse as clean JSON
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["integration"], "AEGIS-Wazuh-SIEM")
        self.assertEqual(parsed["wazuh_rule"]["id"], 100201)
        self.assertEqual(parsed["wazuh_rule"]["level"], 12)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Webhook Destination with HMAC-SHA256 Cryptographic Signature
    # ─────────────────────────────────────────────────────────────────────────

    def test_webhook_destination_hmac_signature(self):
        """
        Validates external webhook dispatch with HMAC-SHA256 signed headers.
        """
        captured_headers = {}
        captured_payload = None

        def mock_poster(url, headers, payload):
            nonlocal captured_headers, captured_payload
            captured_headers = headers
            captured_payload = payload
            return True

        secret = "super_secure_aegis_key_2026"
        webhook = WebhookAlertDestination(
            endpoint_url="https://soc.company.internal/alerts",
            signing_secret=secret,
            mock_sender=mock_poster,
        )

        alert = self.engine.build_incident_alert(
            fusion_result=self.engine.fuse(hash_chain_ok=True, ai_score=0.88),
            frame_sequence_range=[40, 70],
            forensic_hash="0123456789abcdef0123456789abcdef",
        )
        success = webhook.deliver(alert)

        self.assertTrue(success)
        self.assertIn("X-AEGIS-Signature", captured_headers)
        expected_sig = "sha256=" + hmac.new(secret.encode(), captured_payload, hashlib.sha256).hexdigest()
        self.assertEqual(captured_headers["X-AEGIS-Signature"], expected_sig)
        self.assertEqual(captured_headers["X-AEGIS-Severity"], "P1_CRITICAL")

    # ─────────────────────────────────────────────────────────────────────────
    # 4. End-to-End: AI Track Synthetic Detection -> SIEM Alert Destination
    # ─────────────────────────────────────────────────────────────────────────

    def test_e2e_ai_synthetic_alert_routing(self):
        """
        [E2E SCENARIO 1] AI track detects deepfake facial synthesis on authentic stream headers.
        Verifies:
          - Anomaly triggers NEURAL_FACIAL_SYNTHESIS
          - Severity resolved to P1_CRITICAL (Wazuh rule 100201)
          - Alert delivered to Memory receiver, File log, and Evidence Vault
          - Contains all required evidence fields (model contributions, sequence range, hash)
        """
        cam_meta = {
            "camera_id": "cam-briefing-room",
            "ip_address": "10.0.4.12",
            "location": "Executive Briefing Room",
            "certificate_fingerprint": "SHA256:4b9211c4e976f2d2",
        }
        model_scores = {
            "video-classifier": 0.941,
            "rppg": 0.825,
            "syncnet": 0.860,
        }

        fusion_res, alert = self.engine.fuse_and_route(
            hash_chain_ok=True,
            integrity_anomalies=[],
            prnu_ok=True,
            prnu_pce=120.0,
            ai_score=0.892,  # AI detector triggers strong fake
            camera_metadata=cam_meta,
            frame_sequence_range=[450, 520],
            forensic_hash="8f835b7194f4c281729b827e8bcda1a3e895471c26b7139177bc",
            model_contributions=model_scores,
        )

        self.assertEqual(fusion_res.verdict, "SYNTHETIC")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.threat_classification, "NEURAL_FACIAL_SYNTHESIS")
        self.assertEqual(alert.severity, "P1_CRITICAL")
        self.assertEqual(alert.wazuh_rule_id, 100201)

        # 1. Received in memory destination
        self.assertEqual(self.mem_dest.count, 1)
        rec = self.mem_dest.received_alerts[0]
        self.assertEqual(rec.camera_metadata.camera_id, "cam-briefing-room")
        self.assertEqual(rec.evidence_bundle.model_contributions["video-classifier"], 0.941)

        # 2. Received in File destination (Wazuh NDJSON log)
        self.assertTrue(self.log_file.exists())
        with open(self.log_file, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["threat_classification"], "NEURAL_FACIAL_SYNTHESIS")

        # 3. Vault destination recorded immutable audit reference
        self.assertIsNotNone(alert.evidence_bundle.vault_incident_id)
        self.assertTrue(alert.evidence_bundle.snapshot_uri.startswith("vault://incidents/"))

    # ─────────────────────────────────────────────────────────────────────────
    # 5. End-to-End: PRNU Hardware Sensor Mismatch (Physical Device Spoofing)
    # ─────────────────────────────────────────────────────────────────────────

    def test_e2e_prnu_sensor_mismatch_alert_routing(self):
        """
        [E2E SCENARIO 2] Physical camera swap / foreign sensor PRNU splice.
        Verifies:
          - PRNU PCE 16.5 < 50.0 triggers PRNU_SENSOR_MISMATCH
          - Core tenet: integrity failure forces INTEGRITY_UNKNOWN and P1_CRITICAL
          - Evidence bundle contains pce_score and pce_threshold
          - Actionable playbooks include socket severance and security dispatch
        """
        cam_meta = {
            "camera_id": "cam-gate-04",
            "ip_address": "192.168.10.45",
            "location": "North Perimeter Gate",
            "certificate_fingerprint": "SHA256:7e8b91a24d55c911832b49",
        }

        fusion_res, alert = self.engine.fuse_and_route(
            hash_chain_ok=True,
            integrity_anomalies=[],
            prnu_ok=False,
            prnu_pce=16.54,
            ai_score=0.22,  # AI model might look clean, but hardware sensor proves foreign device!
            camera_metadata=cam_meta,
            frame_sequence_range=[1024, 1054],
            forensic_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            broken_at_sequence=1024,
        )

        self.assertEqual(fusion_res.verdict, "INTEGRITY_UNKNOWN")
        self.assertEqual(alert.threat_classification, "PRNU_SENSOR_MISMATCH")
        self.assertEqual(alert.severity, "P1_CRITICAL")
        self.assertEqual(alert.wazuh_rule_id, 100201)
        self.assertEqual(alert.evidence_bundle.pce_score, 16.54)
        self.assertEqual(alert.evidence_bundle.pce_threshold, 50.0)
        self.assertEqual(alert.evidence_bundle.broken_at_sequence, 1024)
        self.assertEqual(alert.containment_action, "SOCKET_SEVERED")

    # ─────────────────────────────────────────────────────────────────────────
    # 6. End-to-End: Stream Sequence Gap & Replay Anomaly
    # ─────────────────────────────────────────────────────────────────────────

    def test_e2e_sequence_gap_and_replay_alert_routing(self):
        """
        [E2E SCENARIO 3] StreamValidator detects sequence gap & timestamp replay.
        Verifies:
          - Anomaly classified as STREAM_REPLAY_ATTACK
          - Proper severity and automated containment action
        """
        validator = StreamValidator(fps=30)
        validator.check(1, 1000)
        # Duplicate sequence + backward timestamp regression
        anomalies = validator.check(1, 500)

        fusion_res, alert = self.engine.fuse_and_route(
            hash_chain_ok=True,
            integrity_anomalies=anomalies,
            prnu_ok=True,
            prnu_pce=100.0,
            ai_score=0.15,
            frame_sequence_range=[1, 2],
            forensic_hash="abcdef0123456789abcdef0123456789abcdef01",
        )

        self.assertEqual(fusion_res.verdict, "INTEGRITY_UNKNOWN")
        self.assertIn("REPLAY", alert.threat_classification)
        self.assertEqual(alert.severity, "P1_CRITICAL")
        self.assertEqual(self.mem_dest.count, 1)

    # ─────────────────────────────────────────────────────────────────────────
    # 7. SIEM Alert Throttling & Deduplication (SR-09 / SR-16)
    # ─────────────────────────────────────────────────────────────────────────

    def test_alert_deduplication_and_throttling(self):
        """
        Validates alert router deduplication to prevent analyst alert fatigue
        and SIEM storage DoS (SR-09, SR-16).
        """
        cam = CameraMetadata(camera_id="cam-throttle-01")
        bundle = EvidenceBundle(
            forensic_hash="ffff0000ffff0000ffff0000ffff0000ffff0000",
            frame_sequence_range=[10, 20],
            technical_detail="Minor network jitter warning.",
        )
        alert = AEGISAlert(
            severity="P3_WARNING",
            camera_metadata=cam,
            threat_classification="STREAM_SEQUENCE_GAP",
            anomaly_score=0.40,
            evidence_bundle=bundle,
        )

        # First alert routes
        res1 = self.router.route_alert(alert)
        self.assertTrue(len(res1) > 0)
        self.assertEqual(self.mem_dest.count, 1)

        # Immediate rapid second alert with same threat should be deduplicated
        res2 = self.router.route_alert(alert)
        self.assertEqual(res2, {})
        self.assertEqual(self.mem_dest.count, 1, "Duplicate alert within window must be deduplicated")
        self.assertEqual(self.router.total_dropped_dedup, 1)


if __name__ == "__main__":
    unittest.main()
