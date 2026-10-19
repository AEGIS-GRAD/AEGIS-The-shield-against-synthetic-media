"""
AEGIS Incident Response & SIEM Routing Subsystem
Compliant with NIST SP 800-61 Rev. 2 and AEGIS-SOP-IR-001 specification.
"""

from .alert_router import (
    AEGISAlert,
    CameraMetadata,
    EvidenceBundle,
    AlertRouter,
    BaseAlertDestination,
    MemoryAlertDestination,
    FileAlertDestination,
    WebhookAlertDestination,
    EvidenceVaultDestination,
    classify_threat_from_fusion,
    severity_from_verdict_and_score,
)

__all__ = [
    "AEGISAlert",
    "CameraMetadata",
    "EvidenceBundle",
    "AlertRouter",
    "BaseAlertDestination",
    "MemoryAlertDestination",
    "FileAlertDestination",
    "WebhookAlertDestination",
    "EvidenceVaultDestination",
    "classify_threat_from_fusion",
    "severity_from_verdict_and_score",
]
