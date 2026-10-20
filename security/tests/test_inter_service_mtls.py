"""
🛡️ AEGIS Inter-Service mTLS Mesh Test Suite (Task 6)
=====================================================
Validates end-to-end mutual TLS authentication across all internal services:
  1. Ingestion Gateway <--> Feed Fusion Service
  2. Feed Fusion Service <--> Alert Router
  3. Alert Router <--> Downstream SOC / SIEM Endpoint

Adheres to NIST SP 800-207 (Zero Trust Architecture) and RFC 8446 (TLS 1.3).
"""

import os
import ssl
import sys
import time
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SECURITY_DIR = os.path.join(REPO_ROOT, "security")
for path in (REPO_ROOT, SECURITY_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from security.transport.generate_certs import (
    generate_all_service_certs,
    generate_cert,
    save_cert,
)
from security.transport.mtls_service_mesh import (
    MTLSServiceClient,
    MTLSServiceServer,
)
from security.incident_response.alert_router import (
    AEGISAlert,
    CameraMetadata,
    EvidenceBundle,
    MTLSAlertDestination,
    WebhookAlertDestination,
)

CERTS_DIR = os.path.join(SECURITY_DIR, "transport", "certs")


@pytest.fixture(scope="session", autouse=True)
def ensure_all_certs():
    """Ensures all 6 service certificates exist and are signed with SANs."""
    generate_all_service_certs(CERTS_DIR)


class TestInterServiceMTLSMesh:
    """Tests the mutual TLS infrastructure across all internal AEGIS services."""

    def test_01_all_service_certificates_exist_and_have_sans(self):
        """Verifies that Root CA and all service certificates exist and contain Subject Alternative Names."""
        from cryptography import x509

        expected_services = ["ca", "gateway", "client", "fusion", "alert_router", "siem"]
        for svc in expected_services:
            cert_path = os.path.join(CERTS_DIR, f"{svc}.crt")
            key_path = os.path.join(CERTS_DIR, f"{svc}.key")
            assert os.path.exists(cert_path), f"Missing certificate for {svc}"
            assert os.path.exists(key_path), f"Missing private key for {svc}"

            with open(cert_path, "rb") as f:
                cert = x509.load_pem_x509_certificate(f.read())

            if svc != "ca":
                # Verify SAN extension exists
                san_ext = cert.extensions.get_extension_for_oid(x509.oid.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                assert san_ext is not None, f"Certificate for {svc} is missing SAN extension!"

    def test_02_gateway_to_fusion_mtls_rpc(self):
        """
        Validates mTLS RPC between Ingestion Gateway and Feed Fusion service.
        Both sides verify Root CA signatures and mutual identities.
        """
        port = 18445
        received_requests = []

        def fusion_handler(payload, client_cn):
            received_requests.append((payload, client_cn))
            return {"status": "OK", "fused_verdict": "AUTHENTIC", "integrity_ok": True}

        server = MTLSServiceServer(
            service_name="fusion",
            port=port,
            allowed_client_cns={"aegis-gateway"},
            request_handler=fusion_handler,
        )
        server.start_background()

        try:
            # Ingestion gateway client calls fusion over mTLS
            client = MTLSServiceClient(calling_service_name="gateway", timeout=3.0)
            resp = client.send_request(
                host="127.0.0.1",
                port=port,
                payload={"hash_chain_ok": True, "seq": 10, "prnu_ok": True},
                expected_server_cn="aegis-fusion",
            )

            assert resp.get("status") == "OK"
            assert resp.get("fused_verdict") == "AUTHENTIC"
            assert len(received_requests) == 1
            payload, caller_cn = received_requests[0]
            assert caller_cn == "aegis-gateway"
            assert payload["seq"] == 10
        finally:
            server.stop_background()

    def test_03_fusion_to_alert_router_mtls_rpc(self):
        """
        Validates mTLS RPC between Feed Fusion service and Alert Router.
        Alert Router verifies the caller is specifically 'aegis-fusion'.
        """
        port = 18446
        received_alerts = []

        def alert_handler(payload, client_cn):
            received_alerts.append((payload, client_cn))
            return {"status": "ACK", "alert_routed": True, "threat": payload.get("threat")}

        server = MTLSServiceServer(
            service_name="alert_router",
            port=port,
            allowed_client_cns={"aegis-fusion", "aegis-gateway"},
            request_handler=alert_handler,
        )
        server.start_background()

        try:
            # Fusion client dispatches alert to Alert Router
            client = MTLSServiceClient(calling_service_name="fusion", timeout=3.0)
            resp = client.send_request(
                host="127.0.0.1",
                port=port,
                payload={"threat": "PRNU_SENSOR_MISMATCH", "severity": "P1_CRITICAL"},
                expected_server_cn="aegis-alert-router",
            )

            assert resp.get("status") == "ACK"
            assert resp.get("alert_routed") is True
            assert len(received_alerts) == 1
            payload, caller_cn = received_alerts[0]
            assert caller_cn == "aegis-fusion"
            assert payload["threat"] == "PRNU_SENSOR_MISMATCH"
        finally:
            server.stop_background()

    def test_04_cross_role_impersonation_rejection(self):
        """
        Zero Trust Role Enforcement:
        An Edge Camera (client.crt, CN: camera-001) connects to the Alert Router.
        Even though camera-001 has a valid CA-signed cert, the Alert Router strictly rejects it
        because only 'aegis-fusion' and 'aegis-gateway' are authorized to dispatch alerts.
        """
        port = 18447

        server = MTLSServiceServer(
            service_name="alert_router",
            port=port,
            allowed_client_cns={"aegis-fusion", "aegis-gateway"},
        )
        server.start_background()

        try:
            # Camera client attempts to call Alert Router directly
            client = MTLSServiceClient(calling_service_name="client", timeout=3.0)
            resp = client.send_request(
                host="127.0.0.1",
                port=port,
                payload={"threat": "FORGED_ALERT_FROM_CAMERA"},
            )

            # Must be rejected due to unauthorized role
            assert resp.get("status") in ("REJECTED", "ERROR")
            assert "UNAUTHORIZED_SERVICE_ROLE" in resp.get("error", "") or resp.get("status") == "ERROR"
        finally:
            server.stop_background()

    def test_05_rogue_untrusted_ca_rejection(self, tmp_path):
        """
        Validates that a rogue client with a certificate issued by an untrusted external CA
        is severed immediately at the TLS handshake layer before sending any data.
        """
        port = 18448

        server = MTLSServiceServer(
            service_name="fusion",
            port=port,
        )
        server.start_background()

        try:
            # Generate a rogue CA and rogue certificate
            rogue_dir = str(tmp_path / "rogue_certs")
            os.makedirs(rogue_dir, exist_ok=True)
            r_ca_key, r_ca_cert, r_ca_sub = generate_cert("Rogue Hacker Root CA", is_ca=True)
            r_key, r_cert, _ = generate_cert("aegis-gateway", issuer_name=r_ca_sub, issuer_key=r_ca_key)
            save_cert(rogue_dir, "ca", r_ca_key, r_ca_cert)
            save_cert(rogue_dir, "rogue_svc", r_key, r_cert)

            # Attempt to connect to fusion with the rogue cert
            rogue_client = MTLSServiceClient(calling_service_name="rogue_svc", certs_dir=rogue_dir)

            with pytest.raises((ssl.SSLError, ConnectionResetError, BrokenPipeError, TimeoutError)):
                rogue_client.send_request(
                    host="127.0.0.1",
                    port=port,
                    payload={"malicious": "payload"},
                )
        finally:
            server.stop_background()

    def test_06_mtls_alert_destination_e2e(self):
        """
        Validates MTLSAlertDestination delivering a structured AEGISAlert over mTLS
        to a simulated Wazuh/SIEM intake server.
        """
        port = 18449
        delivered_alerts = []

        def siem_receiver(payload, client_cn):
            delivered_alerts.append((payload, client_cn))
            return {"status": "OK", "ack": True, "wazuh_event_id": "WAZUH-9981"}

        siem_server = MTLSServiceServer(
            service_name="siem",
            port=port,
            allowed_client_cns={"aegis-alert-router"},
            request_handler=siem_receiver,
        )
        siem_server.start_background()

        try:
            dest = MTLSAlertDestination(
                host="127.0.0.1",
                port=port,
                calling_service_name="alert_router",
                expected_server_cn="aegis-siem",
            )

            test_alert = AEGISAlert(
                severity="P1_CRITICAL",
                threat_classification="CRYPTOGRAPHIC_HASH_MISMATCH",
                anomaly_score=1.0,
                camera_metadata=CameraMetadata(
                    camera_id="camera-north-gate",
                    ip_address="192.168.1.50",
                    location="Perimeter North",
                ),
                evidence_bundle=EvidenceBundle(
                    forensic_hash="abcd1234ef5678",
                    frame_sequence_range=[100, 100],
                    broken_at_sequence=100,
                    technical_detail="Hash mismatch detected in load testing",
                ),
            )

            success = dest.deliver(test_alert)
            assert success is True
            assert dest.sent_count == 1
            assert len(delivered_alerts) == 1
            received_data, caller = delivered_alerts[0]
            assert caller == "aegis-alert-router"
            assert received_data["threat_classification"] == "CRYPTOGRAPHIC_HASH_MISMATCH"
            assert received_data["camera_metadata"]["camera_id"] == "camera-north-gate"
        finally:
            siem_server.stop_background()

    def test_07_webhook_destination_mtls_config(self):
        """Validates that WebhookAlertDestination accepts and configures mTLS client certificates."""
        dest = WebhookAlertDestination(
            endpoint_url="https://siem.soc.local:9200/alerts",
            client_cert=os.path.join(CERTS_DIR, "alert_router.crt"),
            client_key=os.path.join(CERTS_DIR, "alert_router.key"),
            ca_cert=os.path.join(CERTS_DIR, "ca.crt"),
        )
        assert dest.client_cert.endswith("alert_router.crt")
        assert dest.ca_cert.endswith("ca.crt")
