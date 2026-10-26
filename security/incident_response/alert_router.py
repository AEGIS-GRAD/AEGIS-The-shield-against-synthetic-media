"""
AEGIS Incident Response & Alert Routing Engine
===============================================
Implements the real-time incident-response and SIEM/SOC alert routing workflow
designed in Week 2 (security/docs/incident_response_workflow.md, AEGIS-SOP-IR-001).

Connects triggered anomalies (from the AI track's FeedFusionEngine, StreamValidator,
and PRNU hardware forensics) to SIEM / SOC destinations:
  1. Wazuh SIEM (NDJSON agent queue / syslog / local event log)
  2. SOC Alert Webhook (HTTP POST with HMAC-SHA256 signature)
  3. Evidence Vault (ISO/IEC 27037 tamper-evident archive)
  4. Next.js SOC Dashboard (SSE / WebSocket event stream)
  5. In-Memory Mock Destination (deterministic unit and integration testing)

Complies with:
  - NIST SP 800-61 Rev. 2 (Computer Security Incident Handling Guide)
  - ISO/IEC 27037 (Digital Evidence Handling & Chain of Custody)
  - NIST SP 800-207 (Zero Trust Architecture)
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import uuid

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("aegis.incident_response.router")

# Severity enumeration
SEVERITY_LEVELS = ("P1_CRITICAL", "P2_HIGH", "P3_WARNING", "P4_INFO")

# Wazuh custom rule ID mapping per AEGIS-SOP-IR-001 Section 3 & 4
WAZUH_RULE_MAP: Dict[str, int] = {
    "P1_CRITICAL": 100201,
    "P2_HIGH": 100202,
    "P3_WARNING": 100203,
    "P4_INFO": 100204,
}

# Standard recommended playbooks per threat classification
PLAYBOOK_RECOMMENDATIONS: Dict[str, List[str]] = {
    "CRYPTOGRAPHIC_HASH_MISMATCH": [
        "Sever live ingestion TCP socket immediately",
        "Lock last authentic frame sequence in SQLite vault",
        "Trigger visual strobe on SOC operator console",
        "Investigate potential inline MitM packet injection",
    ],
    "PRNU_SENSOR_MISMATCH": [
        "Sever live ingestion socket immediately",
        "Flag potential foreign camera hardware spoofing",
        "Dispatch physical perimeter security to camera location",
        "Seal sequence in forensic vault with ISO/IEC 27037 manifest",
    ],
    "STREAM_REPLAY_ATTACK": [
        "Drop replayed stream frames",
        "Freeze live display on standby warning slate",
        "Verify physical area activity via secondary sensor/camera",
    ],
    "STREAM_SEQUENCE_GAP": [
        "Flag video stream with amber risk overlay",
        "Inspect network switch / interface for packet drop or burst jitter",
        "Request client sequence resynchronization",
    ],
    "ROGUE_CREDENTIAL_ATTEMPT": [
        "Reject TLS handshake immediately (mTLS certificate required)",
        "Add client IP/fingerprint to temporary gateway blackhole",
        "Alert infrastructure administrator of unauthorized device access",
    ],
    "NEURAL_FACIAL_SYNTHESIS": [
        "Trigger visual red strobe on SOC Operator Station",
        "Hold active stream on last verified authentic frame",
        "Initiate secondary multimodal detector pass (rPPG + SyncNet)",
        "Notify Watch Commander via SOC escalation webhook",
    ],
    "AUDIO_VOICE_CLONING": [
        "Flag audio stream for acoustic synthetic manipulation",
        "Inspect spectral artifacts in AASIST voice spoofing log",
        "Mute synthesized audio channel on live monitoring desk",
    ],
    "AUDIO_VISUAL_LIP_SYNC_DESYNC": [
        "Flag potential audio-visual splice divergence",
        "Log SyncNet cross-modal synchronization offset (ms)",
        "Escalate to Tier 2 forensic specialist for manual inspection",
    ],
}


class CameraMetadata(BaseModel):
    """Camera identification and location metadata for actionable incident triage."""
    camera_id: str = Field(..., description="Unique camera identifier, e.g., cam-gate-04")
    ip_address: str = Field(default="127.0.0.1", description="Source IP address of camera stream")
    location: str = Field(default="Main Facility Perimeter", description="Physical installation zone")
    certificate_fingerprint: str = Field(
        default="SHA256:0000000000000000000000000000000000000000000000000000000000000000",
        description="x509 client certificate SHA-256 fingerprint for mTLS audit"
    )


class EvidenceBundle(BaseModel):
    """Tamper-evident forensic evidence fields proving why the alert was fired."""
    forensic_hash: str = Field(..., description="SHA-256 hash of the evidentiary frame or window")
    frame_sequence_range: List[int] = Field(
        ..., description="Sequence range [start, end] bounded by the detection window"
    )
    pce_score: Optional[float] = Field(None, description="Measured PRNU Peak-to-Correlation Energy")
    pce_threshold: Optional[float] = Field(None, description="Enrolled PRNU baseline threshold (typically 50.0)")
    broken_at_sequence: Optional[int] = Field(None, description="Sequence index where integrity failed")
    model_contributions: Optional[Dict[str, float]] = Field(
        None, description="Per-detector scores (e.g. video-classifier, rppg, syncnet)"
    )
    technical_detail: str = Field(
        ..., description="Forensic and mathematical explanation of the detected anomaly"
    )
    snapshot_uri: Optional[str] = Field(
        None, description="URI or relative path to archived evidence blob in vault"
    )
    vault_incident_id: Optional[str] = Field(
        None, description="UUID of record in SurveillanceEvidenceVault ledger"
    )


class AEGISAlert(BaseModel):
    """
    Actionable Incident Alert Contract.
    Conforms strictly to the JSON Schema specified in AEGIS-SOP-IR-001 Section 5.1.
    """
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_iso: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )
    severity: str = Field(..., description="P1_CRITICAL, P2_HIGH, P3_WARNING, or P4_INFO")
    camera_metadata: CameraMetadata
    threat_classification: str = Field(
        ...,
        description="Standardized threat enum (e.g. NEURAL_FACIAL_SYNTHESIS, PRNU_SENSOR_MISMATCH)"
    )
    anomaly_score: float = Field(..., ge=0.0, le=1.0, description="Combined anomaly score [0.0 - 1.0]")
    evidence_bundle: EvidenceBundle
    recommended_actions: List[str] = Field(default_factory=list)
    wazuh_rule_id: int = Field(default=100201, description="Mapped Wazuh rule ID")
    containment_action: str = Field(
        default="AUDIT_LOGGED",
        description="Automated action taken (SOCKET_SEVERED, RISK_OVERLAY, HOLD_SLATE, AUDIT_LOGGED)"
    )

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        if v not in SEVERITY_LEVELS:
            raise ValueError(f"Severity must be one of {SEVERITY_LEVELS}, got '{v}'")
        return v

    def to_wazuh_ndjson(self) -> str:
        """
        Formats alert as a sanitized single-line NDJSON event for Wazuh manager/agent queue.
        Safeguards against NDJSON injection (CVE-2026-56699) by stripping interior newlines.
        """
        payload = self.model_dump()
        payload["integration"] = "AEGIS-Wazuh-SIEM"
        payload["wazuh_rule"] = {
            "id": self.wazuh_rule_id,
            "level": 12 if self.severity == "P1_CRITICAL" else (8 if self.severity == "P2_HIGH" else 4),
            "description": f"AEGIS {self.severity}: {self.threat_classification} detected on {self.camera_metadata.camera_id}",
        }
        raw_json = json.dumps(payload, separators=(",", ":"))
        # Sanitize against NDJSON newline injection
        clean_json = raw_json.replace("\r", " ").replace("\n", " ")
        return clean_json + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# Threat Classification & Severity Resolution Helpers
# ─────────────────────────────────────────────────────────────────────────────

def severity_from_verdict_and_score(
    verdict: str, combined_score: float, integrity_ok: bool, ai_score: float = 0.0
) -> str:
    """
    Computes alert severity following Section 3.1 Severity Classification Matrix:
    - P1_CRITICAL: Non-negotiable hard integrity failure (broken hash, PRNU PCE < 50, rogue cert)
                   OR AI / combined anomaly score >= 0.70 (or SYNTHETIC verdict).
    - P2_HIGH: Deepfake confidence 0.50 <= S < 0.70 or sequence gap > 5.
    - P3_WARNING: Score 0.35 <= S < 0.50 or network jitter / lighting drop.
    - P4_INFO: Score < 0.35, clean authentic stream.
    """
    if not integrity_ok:
        return "P1_CRITICAL"
    effective_score = max(combined_score, ai_score)
    if effective_score >= 0.70 or verdict == "SYNTHETIC":
        return "P1_CRITICAL"
    if effective_score >= 0.50:
        return "P2_HIGH"
    if effective_score >= 0.35:
        return "P3_WARNING"
    return "P4_INFO"


def classify_threat_from_fusion(
    verdict: str,
    hash_chain_ok: bool,
    prnu_ok: bool,
    anomaly_count: int,
    ai_score: float,
    anomalies: Optional[List[str]] = None,
) -> str:
    """
    Determines the specific STRIDE/incident threat classification from fusion signals.
    """
    if not hash_chain_ok:
        return "CRYPTOGRAPHIC_HASH_MISMATCH"
    if not prnu_ok:
        return "PRNU_SENSOR_MISMATCH"
    if anomaly_count > 0:
        anom_str = " ".join(anomalies or []).upper()
        if "REPLAY" in anom_str or "REGRESSION" in anom_str or "DUPLICATE" in anom_str:
            return "STREAM_REPLAY_ATTACK"
        return "STREAM_SEQUENCE_GAP"
    if ai_score >= 0.65 or verdict == "SYNTHETIC":
        return "NEURAL_FACIAL_SYNTHESIS"
    return "INFORMATIONAL_TELEMETRY"


# ─────────────────────────────────────────────────────────────────────────────
# Destination Interfaces and Implementations
# ─────────────────────────────────────────────────────────────────────────────

class BaseAlertDestination(abc.ABC):
    """Abstract interface for a SIEM/SOC alert routing endpoint."""

    @abc.abstractmethod
    def deliver(self, alert: AEGISAlert) -> bool:
        """Deliver the alert. Returns True on success, False on failure."""
        pass

    @property
    def destination_name(self) -> str:
        return self.__class__.__name__


class MemoryAlertDestination(BaseAlertDestination):
    """In-memory receiver for unit testing, integration tests, and programmatic queries."""

    def __init__(self):
        self.received_alerts: List[AEGISAlert] = []
        self._lock = threading.Lock()

    def deliver(self, alert: AEGISAlert) -> bool:
        with self._lock:
            self.received_alerts.append(alert)
        return True

    def clear(self):
        with self._lock:
            self.received_alerts.clear()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self.received_alerts)


class FileAlertDestination(BaseAlertDestination):
    """
    Appends sanitized NDJSON alerts to a local log file or Wazuh agent intake directory.
    Atomic and thread-safe.
    """

    def __init__(self, log_path: Union[str, Path]):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def deliver(self, alert: AEGISAlert) -> bool:
        ndjson_line = alert.to_wazuh_ndjson()
        try:
            with self._lock:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(ndjson_line)
                    f.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to append alert to {self.log_path}: {e}")
            return False


class WebhookAlertDestination(BaseAlertDestination):
    """
    Dispatches alerts via HTTP/HTTPS POST to external SIEM/SOC or PagerDuty endpoints.
    Includes HMAC-SHA256 signature for payload verification and tamper prevention,
    with full support for mutual TLS (client certs and custom CA trust anchors).
    """

    def __init__(
        self,
        endpoint_url: str,
        signing_secret: str = "aegis_soc_webhook_secret_key",
        timeout_seconds: float = 3.0,
        mock_sender: Optional[Callable[[str, Dict[str, str], bytes], bool]] = None,
        client_cert: Optional[str] = None,
        client_key: Optional[str] = None,
        ca_cert: Optional[str] = None,
    ):
        self.endpoint_url = endpoint_url
        self.signing_secret = signing_secret.encode("utf-8")
        self.timeout_seconds = timeout_seconds
        self.mock_sender = mock_sender  # For testing without live network
        self.client_cert = client_cert
        self.client_key = client_key
        self.ca_cert = ca_cert
        self.sent_count = 0

    def compute_signature(self, payload_bytes: bytes) -> str:
        return hmac.new(self.signing_secret, payload_bytes, hashlib.sha256).hexdigest()

    def deliver(self, alert: AEGISAlert) -> bool:
        payload_bytes = alert.model_dump_json().encode("utf-8")
        signature = self.compute_signature(payload_bytes)
        headers = {
            "Content-Type": "application/json",
            "X-AEGIS-Signature": f"sha256={signature}",
            "X-AEGIS-Alert-ID": alert.alert_id,
            "X-AEGIS-Severity": alert.severity,
        }

        if self.mock_sender:
            success = self.mock_sender(self.endpoint_url, headers, payload_bytes)
            if success:
                self.sent_count += 1
            return success

        # In production environments with httpx/requests available:
        try:
            import httpx
            cert_param = None
            if self.client_cert and self.client_key:
                cert_param = (self.client_cert, self.client_key)
            verify_param = self.ca_cert if self.ca_cert else True

            with httpx.Client(timeout=self.timeout_seconds, cert=cert_param, verify=verify_param) as client:
                res = client.post(self.endpoint_url, content=payload_bytes, headers=headers)
                if res.is_success:
                    self.sent_count += 1
                    return True
                logger.warning(f"Webhook destination responded with status {res.status_code}")
                return False
        except Exception as e:
            logger.error(f"Webhook dispatch failed to {self.endpoint_url}: {e}")
            return False


class MTLSAlertDestination(BaseAlertDestination):
    """
    Dispatches alerts directly over an encrypted, mutually authenticated mTLS 1.3/1.2 TCP socket
    to internal SOC receivers, Wazuh agent intake, or secondary aggregation nodes.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8446,
        calling_service_name: str = "alert_router",
        expected_server_cn: str = "aegis-siem",
        certs_dir: Optional[str] = None,
        timeout_seconds: float = 3.0,
    ):
        self.host = host
        self.port = port
        self.calling_service_name = calling_service_name
        self.expected_server_cn = expected_server_cn
        self.certs_dir = certs_dir
        self.timeout_seconds = timeout_seconds
        self.sent_count = 0

    def deliver(self, alert: AEGISAlert) -> bool:
        try:
            from security.transport.mtls_service_mesh import MTLSServiceClient
            client = MTLSServiceClient(
                calling_service_name=self.calling_service_name,
                certs_dir=self.certs_dir,
                timeout=self.timeout_seconds,
            )
            resp = client.send_request(
                host=self.host,
                port=self.port,
                payload=alert.model_dump(),
                expected_server_cn=self.expected_server_cn,
            )
            if resp.get("status") in ("OK", "ACK"):
                self.sent_count += 1
                return True
            return False
        except Exception as e:
            logger.error(f"mTLS Alert delivery failed to {self.host}:{self.port}: {e}")
            return False


class EvidenceVaultDestination(BaseAlertDestination):
    """
    Connects alerts to the ISO/IEC 27037 SurveillanceEvidenceVault.
    Preserves raw evidentiary frames in content-addressed storage and updates
    the alert with the immutable snapshot URI.
    """

    def __init__(self, vault_instance: Optional[Any] = None):
        if vault_instance is None:
            try:
                from security.forensics.evidence_vault import SurveillanceEvidenceVault
                self.vault = SurveillanceEvidenceVault()
            except ImportError:
                self.vault = None
        else:
            self.vault = vault_instance

    def deliver(self, alert: AEGISAlert) -> bool:
        if self.vault is None:
            return False
        try:
            # Check if alert already has vault incident, otherwise create audit record
            if not alert.evidence_bundle.vault_incident_id:
                incident = self.vault.store_incident(
                    camera_id=alert.camera_metadata.camera_id,
                    threat_type=alert.threat_classification,
                    sequence_number=(
                        alert.evidence_bundle.broken_at_sequence
                        or (alert.evidence_bundle.frame_sequence_range[-1] if alert.evidence_bundle.frame_sequence_range else 0)
                    ),
                    timestamp_ms=int(time.time() * 1000),
                    primary_frame_bytes=b"AEGIS_EVIDENTIARY_WINDOW_HASH:" + alert.evidence_bundle.forensic_hash.encode(),
                    telemetry={
                        "anomaly_score": alert.anomaly_score,
                        "pce_score": alert.evidence_bundle.pce_score,
                        "model_contributions": alert.evidence_bundle.model_contributions,
                    },
                    reasoning_narrative=alert.evidence_bundle.technical_detail,
                    severity="CRITICAL" if "CRITICAL" in alert.severity else "HIGH",
                )
                alert.evidence_bundle.vault_incident_id = incident.incident_id
                alert.evidence_bundle.snapshot_uri = f"vault://incidents/{incident.incident_id}"
            return True
        except Exception as e:
            logger.error(f"Evidence vault delivery error: {e}")
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Main Alert Router
# ─────────────────────────────────────────────────────────────────────────────

class AlertRouter:
    """
    Coordinates alert routing from detection engines to SIEM/SOC destinations.
    Enforces rate-limiting, deduplication, and automated containment callbacks.
    """

    def __init__(
        self,
        destinations: Optional[List[BaseAlertDestination]] = None,
        min_severity: str = "P3_WARNING",
        dedup_window_seconds: float = 2.0,
        containment_callback: Optional[Callable[[AEGISAlert], None]] = None,
    ):
        self.destinations: List[BaseAlertDestination] = destinations or []
        self.min_severity = min_severity
        self.dedup_window_seconds = dedup_window_seconds
        self.containment_callback = containment_callback

        self._lock = threading.Lock()
        self._recent_signatures: Dict[str, float] = {}
        self.total_routed = 0
        self.total_dropped_dedup = 0
        self.stats_by_severity: Dict[str, int] = {s: 0 for s in SEVERITY_LEVELS}

    def add_destination(self, destination: BaseAlertDestination):
        """Register a new routing destination."""
        with self._lock:
            self.destinations.append(destination)

    def _should_route_severity(self, severity: str) -> bool:
        """Determines if alert meets configured minimum severity threshold."""
        order = {"P1_CRITICAL": 1, "P2_HIGH": 2, "P3_WARNING": 3, "P4_INFO": 4}
        return order.get(severity, 5) <= order.get(self.min_severity, 3)

    def _is_duplicate(self, alert: AEGISAlert) -> bool:
        """Deduplicates rapid flapping alerts from the same camera & threat within dedup window."""
        now = time.monotonic()
        key = f"{alert.camera_metadata.camera_id}:{alert.threat_classification}"
        with self._lock:
            last_time = self._recent_signatures.get(key, 0.0)
            if now - last_time < self.dedup_window_seconds and alert.severity != "P1_CRITICAL":
                self.total_dropped_dedup += 1
                return True
            self._recent_signatures[key] = now
            return False

    def route_alert(self, alert: AEGISAlert) -> Dict[str, bool]:
        """
        Dispatches an incident alert to all configured destinations.

        Returns:
            Dictionary mapping destination name to delivery success status.
        """
        if not self._should_route_severity(alert.severity):
            return {}

        if self._is_duplicate(alert):
            return {}

        # Automated containment hook (e.g. sever socket or hold feed)
        if self.containment_callback and alert.severity == "P1_CRITICAL":
            try:
                self.containment_callback(alert)
                alert.containment_action = "SOCKET_SEVERED"
            except Exception as e:
                logger.error(f"Containment callback error: {e}")

        delivery_results: Dict[str, bool] = {}
        for dest in self.destinations:
            try:
                success = dest.deliver(alert)
                delivery_results[dest.destination_name] = success
            except Exception as e:
                logger.error(f"Destination {dest.destination_name} raised exception: {e}")
                delivery_results[dest.destination_name] = False

        with self._lock:
            self.total_routed += 1
            self.stats_by_severity[alert.severity] = self.stats_by_severity.get(alert.severity, 0) + 1

        return delivery_results

    def build_and_route_alert(
        self,
        verdict: str,
        combined_score: float,
        integrity_ok: bool,
        camera_metadata: Union[CameraMetadata, Dict[str, Any]],
        evidence_bundle: Union[EvidenceBundle, Dict[str, Any]],
        threat_classification: Optional[str] = None,
        recommended_actions: Optional[List[str]] = None,
    ) -> Optional[AEGISAlert]:
        """
        Constructs an AEGISAlert from raw fusion outputs, validates the contract,
        and routes it to all SIEM/SOC destinations.
        """
        cam_meta = (
            camera_metadata
            if isinstance(camera_metadata, CameraMetadata)
            else CameraMetadata(**camera_metadata)
        )
        ev_bundle = (
            evidence_bundle
            if isinstance(evidence_bundle, EvidenceBundle)
            else EvidenceBundle(**evidence_bundle)
        )

        severity = severity_from_verdict_and_score(verdict, combined_score, integrity_ok)
        threat_type = threat_classification or "ANOMALY_DETECTED"
        rule_id = WAZUH_RULE_MAP.get(severity, 100201)

        actions = recommended_actions or PLAYBOOK_RECOMMENDATIONS.get(
            threat_type,
            ["Log incident to flight recorder", "Notify SOC Tier 1 Operator"]
        )

        containment = "SOCKET_SEVERED" if severity == "P1_CRITICAL" else (
            "RISK_OVERLAY" if severity == "P2_HIGH" else "AUDIT_LOGGED"
        )

        alert = AEGISAlert(
            severity=severity,
            camera_metadata=cam_meta,
            threat_classification=threat_type,
            anomaly_score=combined_score,
            evidence_bundle=ev_bundle,
            recommended_actions=actions,
            wazuh_rule_id=rule_id,
            containment_action=containment,
        )

        self.route_alert(alert)
        return alert
