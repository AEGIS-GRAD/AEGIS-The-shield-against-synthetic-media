"""
Feed Fusion Engine for AEGIS.
Combines Cybersecurity feed-integrity signals (hash-chain, timestamp/sequence anomalies, PRNU)
with the AI track's rolling content-anomaly score into a single unified verdict.

Verdict States:
- AUTHENTIC: Feed integrity intact and AI score low (authentic).
- SYNTHETIC: Feed intact or metadata forged, but content anomaly score indicates fake.
- INTEGRITY_UNKNOWN: Feed integrity broken (hash mismatch, timestamp/sequence gaps/regressions, PRNU foreign sensor).
  Per AEGIS core tenets, integrity failures must NEVER resolve to AUTHENTIC.
- UNCERTAIN: Content/integrity signals in borderline or ambiguous range.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union, Tuple

try:
    from security.incident_response.alert_router import (
        AEGISAlert,
        CameraMetadata,
        EvidenceBundle,
        AlertRouter,
        classify_threat_from_fusion,
        severity_from_verdict_and_score,
    )
except (ImportError, ValueError):
    try:
        from incident_response.alert_router import (
            AEGISAlert,
            CameraMetadata,
            EvidenceBundle,
            AlertRouter,
            classify_threat_from_fusion,
            severity_from_verdict_and_score,
        )
    except (ImportError, ValueError):
        try:
            from ..incident_response.alert_router import (
                AEGISAlert,
                CameraMetadata,
                EvidenceBundle,
                AlertRouter,
                classify_threat_from_fusion,
                severity_from_verdict_and_score,
            )
        except Exception:
            AEGISAlert = None
            CameraMetadata = None
            EvidenceBundle = None
            AlertRouter = None
            classify_threat_from_fusion = None
            severity_from_verdict_and_score = None


@dataclass
class FusionResult:
    """Represents the fused verdict and detailed breakdown for a single window."""
    verdict: str
    combined_score: float
    integrity_score: float
    ai_score: float
    integrity_ok: bool
    evidence: Dict[str, Any] = field(default_factory=dict)
    alert: Optional[Any] = None
    tier: int = 1
    calibrated_score: Optional[float] = None
    hysteresis_applied: bool = False


class FeedFusionEngine:
    """
    Tiered Feed Fusion Engine for AEGIS.
    Combines feed-integrity indicators with calibrated AI content anomaly scores.

    Architecture (Month 3 Tiered Fusion):
        Tier 1: Hardware & Feed Integrity Verification
            Hard alerts on broken hash chain, sequence/timestamp gap, or PRNU foreign
            sensor mismatch. An integrity failure MUST NEVER resolve to AUTHENTIC and
            immediately yields INTEGRITY_UNKNOWN regardless of AI content score.
        Tier 2: Content Anomaly Scoring with Anti-Flapping Hysteresis
            When feed integrity is clean, the calibrated AI content score decides
            the verdict directly (decoupled from the 0.5 dilution penalty of Month 2).
            Hysteresis bands prevent rapid flapping when scores sit near decision boundaries.

    Parameters:
        w_integrity: Weight given to integrity score in legacy mode (default: 0.5)
        w_ai: Weight given to AI anomaly score in legacy mode (default: 0.5)
        synthetic_threshold: Threshold above which content is deemed synthetic (default: 0.65)
        authentic_threshold: Threshold below which content is deemed authentic (default: 0.40)
        pce_threshold: PRNU Peak-to-Correlation Energy threshold (default: 50.0)
        hysteresis_margin: Deadband margin around thresholds to suppress flapping (default: 0.05)
        mode: Fusion mode, 'tiered' (default) or 'legacy' (Month 2 equal-weights)
        calibrator: Optional callable or scikit-learn compatible object for score calibration
        alert_router: Optional AlertRouter instance for dispatching SIEM/SOC alerts.
    """

    def __init__(
        self,
        w_integrity: float = 0.5,
        w_ai: float = 0.5,
        synthetic_threshold: float = 0.65,
        authentic_threshold: float = 0.40,
        pce_threshold: float = 50.0,
        hysteresis_margin: float = 0.05,
        mode: str = "tiered",
        calibrator: Optional[Any] = None,
        alert_router: Optional[Any] = None,
    ):
        self.w_integrity = w_integrity
        self.w_ai = w_ai
        self.synthetic_threshold = synthetic_threshold
        self.authentic_threshold = authentic_threshold
        self.pce_threshold = pce_threshold
        self.hysteresis_margin = hysteresis_margin
        self.mode = mode
        self.calibrator = calibrator
        self.alert_router = alert_router

        # Rolling state for anti-flapping hysteresis
        self.last_content_state: Optional[str] = None
        self.state_history: List[str] = []
        self.window_count: int = 0

    def reset(self) -> None:
        """Resets stream state and hysteresis tracking buffers."""
        self.last_content_state = None
        self.state_history.clear()
        self.window_count = 0

    def calibrate_score(self, score: float) -> float:
        """Applies calibration mapping to raw content anomaly score."""
        if self.calibrator is not None:
            if callable(self.calibrator):
                return float(self.calibrator(score))
            elif hasattr(self.calibrator, "predict_proba"):
                return float(self.calibrator.predict_proba([[score]])[0][1])
            elif hasattr(self.calibrator, "calibrate"):
                return float(self.calibrator.calibrate(score))
        return float(score)

    def compute_integrity_score(
        self,
        hash_chain_ok: bool,
        anomaly_count: int,
        prnu_ok: bool,
        prnu_pce: Optional[float] = None,
    ) -> float:
        """
        Maps integrity signals to a normalized 0.0 - 1.0 anomaly penalty score.
        0.0 = fully clean/intact, 1.0 = severely tampered.
        """
        score = 0.0
        if not hash_chain_ok:
            score += 1.0
        # Evaluate PRNU boolean status as well as numeric PCE threshold
        prnu_mismatch = (not prnu_ok) or (prnu_pce is not None and prnu_pce < self.pce_threshold)
        if prnu_mismatch:
            score += 0.8
        if anomaly_count > 0:
            # 3 or more stream timestamp/sequence anomalies saturates to full 1.0
            score += min(1.0, anomaly_count / 3.0)

        return min(1.0, score)

    def fuse(
        self,
        hash_chain_ok: bool,
        integrity_anomalies: Optional[List[Any]] = None,
        prnu_ok: bool = True,
        prnu_pce: float = 100.0,
        ai_score: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
        stateful: bool = True,
    ) -> FusionResult:
        """
        Fuses the integrity indicators with AI anomaly score for the rolling window.

        Args:
            hash_chain_ok: True if hash chain verified successfully for all frames in window.
            integrity_anomalies: List of timestamp/sequence anomalies (from StreamValidator).
            prnu_ok: True if PRNU sensor fingerprint matched baseline.
            prnu_pce: PCE value from PRNU computation.
            ai_score: Rolling content-anomaly score from AI detector [0.0 - 1.0].
            details: Optional extra debugging/forensics metadata.
            stateful: Whether to update rolling anti-flapping hysteresis state.

        Returns:
            FusionResult containing tier, combined score, and verdict.
        """
        if integrity_anomalies is None:
            integrity_anomalies = []

        anomaly_count = len(integrity_anomalies)
        prnu_check_ok = prnu_ok and (prnu_pce is None or prnu_pce >= self.pce_threshold)
        integrity_ok = hash_chain_ok and prnu_check_ok and (anomaly_count == 0)

        integrity_score = self.compute_integrity_score(
            hash_chain_ok=hash_chain_ok,
            anomaly_count=anomaly_count,
            prnu_ok=prnu_ok,
            prnu_pce=prnu_pce,
        )

        calibrated_score = self.calibrate_score(ai_score)
        hysteresis_applied = False

        if not integrity_ok:
            # -------------------------------------------------------------
            # Tier 1: Hardware / Feed Integrity Compromise (Hard Alert)
            # -------------------------------------------------------------
            tier = 1
            verdict = "INTEGRITY_UNKNOWN"
            if self.mode == "tiered":
                # Hard alert penalty reflects full integrity compromise regardless of content
                combined_score = 1.0
            else:
                total_w = self.w_integrity + self.w_ai
                norm_w_integrity = self.w_integrity / total_w if total_w > 0 else 0.5
                norm_w_ai = self.w_ai / total_w if total_w > 0 else 0.5
                combined_score = (norm_w_integrity * integrity_score) + (norm_w_ai * ai_score)

            if stateful:
                self.last_content_state = None  # Reset rolling content state on hard tamper
        else:
            # -------------------------------------------------------------
            # Tier 2: Clean Stream Content Anomaly with Anti-Flapping Hysteresis
            # -------------------------------------------------------------
            tier = 2
            if self.mode == "tiered":
                # Calibrated content score decides directly without 0.5 dilution penalty
                combined_score = calibrated_score

                prev_state = self.last_content_state if stateful else None

                if prev_state is None:
                    if calibrated_score >= self.synthetic_threshold:
                        verdict = "SYNTHETIC"
                    elif calibrated_score <= self.authentic_threshold:
                        verdict = "AUTHENTIC"
                    else:
                        verdict = "UNCERTAIN"
                elif prev_state == "AUTHENTIC":
                    # Must exceed upper hysteresis margin to exit AUTHENTIC state
                    if calibrated_score >= self.synthetic_threshold + self.hysteresis_margin:
                        verdict = "SYNTHETIC"
                    elif calibrated_score > self.authentic_threshold + self.hysteresis_margin:
                        verdict = "UNCERTAIN"
                    else:
                        verdict = "AUTHENTIC"
                        if calibrated_score > self.authentic_threshold:
                            hysteresis_applied = True
                elif prev_state == "SYNTHETIC":
                    # Must fall below lower hysteresis margin to exit SYNTHETIC state
                    if calibrated_score <= self.authentic_threshold - self.hysteresis_margin:
                        verdict = "AUTHENTIC"
                    elif calibrated_score < self.synthetic_threshold - self.hysteresis_margin:
                        verdict = "UNCERTAIN"
                    else:
                        verdict = "SYNTHETIC"
                        if calibrated_score < self.synthetic_threshold:
                            hysteresis_applied = True
                else:  # prev_state == "UNCERTAIN"
                    if calibrated_score >= self.synthetic_threshold:
                        verdict = "SYNTHETIC"
                    elif calibrated_score <= self.authentic_threshold:
                        verdict = "AUTHENTIC"
                    else:
                        verdict = "UNCERTAIN"

                if stateful:
                    self.last_content_state = verdict
                    self.state_history.append(verdict)
                    self.window_count += 1
            else:
                # Legacy Month 2 equal-weighted combination
                total_w = self.w_integrity + self.w_ai
                norm_w_integrity = self.w_integrity / total_w if total_w > 0 else 0.5
                norm_w_ai = self.w_ai / total_w if total_w > 0 else 0.5
                combined_score = (norm_w_integrity * integrity_score) + (norm_w_ai * ai_score)

                if combined_score >= self.synthetic_threshold or ai_score >= self.synthetic_threshold:
                    verdict = "SYNTHETIC"
                elif combined_score <= self.authentic_threshold and ai_score <= self.authentic_threshold:
                    verdict = "AUTHENTIC"
                else:
                    verdict = "UNCERTAIN"

        evidence = {
            "tier": tier,
            "hash_chain_ok": hash_chain_ok,
            "anomaly_count": anomaly_count,
            "anomalies": [str(a) for a in integrity_anomalies],
            "prnu_ok": prnu_ok,
            "prnu_pce": prnu_pce,
            "pce_threshold": self.pce_threshold,
            "ai_score": ai_score,
            "calibrated_score": calibrated_score,
            "integrity_score": integrity_score,
            "combined_score": combined_score,
            "hysteresis_applied": hysteresis_applied,
            "mode": self.mode,
        }
        if details:
            evidence.update(details)

        result = FusionResult(
            verdict=verdict,
            combined_score=combined_score,
            integrity_score=integrity_score,
            ai_score=ai_score,
            integrity_ok=integrity_ok,
            evidence=evidence,
            tier=tier,
            calibrated_score=calibrated_score,
            hysteresis_applied=hysteresis_applied,
        )

        return result

    def build_incident_alert(
        self,
        fusion_result: FusionResult,
        camera_metadata: Optional[Union[CameraMetadata, Dict[str, Any]]] = None,
        frame_sequence_range: Optional[List[int]] = None,
        forensic_hash: Optional[str] = None,
        technical_detail: Optional[str] = None,
        model_contributions: Optional[Dict[str, float]] = None,
        broken_at_sequence: Optional[int] = None,
    ) -> Optional[Any]:
        """
        Builds a strictly-typed AEGISAlert contract from a FusionResult.
        Fills in all evidence bundle fields required by AEGIS-SOP-IR-001 Section 5.1.
        """
        if AEGISAlert is None:
            return None

        # Camera metadata defaults
        cam_meta = camera_metadata or {
            "camera_id": "cam-surveillance-01",
            "ip_address": "192.168.10.50",
            "location": "Sector 4 Main Gate",
            "certificate_fingerprint": "SHA256:4b9211c4e976f2d2b5918e8d53ef69b32e",
        }
        if not isinstance(cam_meta, CameraMetadata):
            cam_meta = CameraMetadata(**cam_meta)

        # Classify threat
        ev = fusion_result.evidence
        threat_type = classify_threat_from_fusion(
            verdict=fusion_result.verdict,
            hash_chain_ok=ev.get("hash_chain_ok", True),
            prnu_ok=ev.get("prnu_ok", True),
            anomaly_count=ev.get("anomaly_count", 0),
            ai_score=fusion_result.ai_score,
            anomalies=ev.get("anomalies", []),
        )

        # Technical detail narrative
        if technical_detail is None:
            if threat_type == "CRYPTOGRAPHIC_HASH_MISMATCH":
                narrative = (
                    f"Cryptographic hash chain broken in window {frame_sequence_range or []}. "
                    "Frame hash desynchronization indicates live packet splicing or unauthorized frame replacement."
                )
            elif threat_type == "PRNU_SENSOR_MISMATCH":
                pce = ev.get("prnu_pce", 0.0)
                narrative = (
                    f"Photo-Response Non-Uniformity residual failed correlation with enrolled sensor baseline. "
                    f"PCE dropped to {pce:.2f} (expected >= 50.0). Video feed originates from a foreign physical device."
                )
            elif threat_type in ("STREAM_REPLAY_ATTACK", "STREAM_SEQUENCE_GAP"):
                anoms = "; ".join(ev.get("anomalies", []))
                narrative = f"Stream validator identified temporal anomalies: {anoms}"
            elif threat_type == "NEURAL_FACIAL_SYNTHESIS":
                narrative = (
                    f"Multimodal AI detector identified facial synthetic manipulation artifacts. "
                    f"AI Anomaly Score: {fusion_result.ai_score:.3f} >= threshold {self.synthetic_threshold:.2f}."
                )
            else:
                narrative = f"Feed integrity status: {fusion_result.verdict} (Score: {fusion_result.combined_score:.3f})"
        else:
            narrative = technical_detail

        f_hash = forensic_hash or ev.get("hash") or "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        seq_range = frame_sequence_range or [0, 30]

        evidence_bundle = EvidenceBundle(
            forensic_hash=f_hash,
            frame_sequence_range=seq_range,
            pce_score=ev.get("prnu_pce"),
            pce_threshold=50.0 if not ev.get("prnu_ok", True) else None,
            broken_at_sequence=broken_at_sequence,
            model_contributions=model_contributions or (
                {"video-classifier": fusion_result.ai_score} if fusion_result.ai_score > 0 else None
            ),
            technical_detail=narrative,
        )

        severity = severity_from_verdict_and_score(
            verdict=fusion_result.verdict,
            combined_score=fusion_result.combined_score,
            integrity_ok=fusion_result.integrity_ok,
            ai_score=fusion_result.ai_score,
        )

        wazuh_rule = 100201 if severity == "P1_CRITICAL" else (
            100202 if severity == "P2_HIGH" else (100203 if severity == "P3_WARNING" else 100204)
        )

        actions = [
            "Sever live ingestion socket immediately",
            "Hold active feed on standby warning slate",
            "Seal window frames in SQLite forensic evidence vault",
        ] if severity == "P1_CRITICAL" else [
            "Flag feed with amber risk overlay",
            "Schedule secondary detector analysis pass",
        ]

        containment = "SOCKET_SEVERED" if severity == "P1_CRITICAL" else (
            "RISK_OVERLAY" if severity == "P2_HIGH" else "AUDIT_LOGGED"
        )

        return AEGISAlert(
            severity=severity,
            camera_metadata=cam_meta,
            threat_classification=threat_type,
            anomaly_score=round(fusion_result.combined_score, 4),
            evidence_bundle=evidence_bundle,
            recommended_actions=actions,
            wazuh_rule_id=wazuh_rule,
            containment_action=containment,
        )

    def fuse_and_route(
        self,
        hash_chain_ok: bool,
        integrity_anomalies: Optional[List[Any]] = None,
        prnu_ok: bool = True,
        prnu_pce: float = 100.0,
        ai_score: float = 0.0,
        camera_metadata: Optional[Union[CameraMetadata, Dict[str, Any]]] = None,
        frame_sequence_range: Optional[List[int]] = None,
        forensic_hash: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        model_contributions: Optional[Dict[str, float]] = None,
        broken_at_sequence: Optional[int] = None,
        alert_router: Optional[Any] = None,
    ) -> Tuple[FusionResult, Optional[Any]]:
        """
        Executes fusion calculation, builds actionable incident alert, and routes
        to SIEM/SOC destinations if an anomaly is triggered.

        Returns:
            Tuple of (FusionResult, Optional[AEGISAlert])
        """
        result = self.fuse(
            hash_chain_ok=hash_chain_ok,
            integrity_anomalies=integrity_anomalies,
            prnu_ok=prnu_ok,
            prnu_pce=prnu_pce,
            ai_score=ai_score,
            details=details,
        )

        router = alert_router or self.alert_router
        alert = None

        # Build alert if non-authentic or if router is active
        if result.verdict != "AUTHENTIC" or router is not None:
            alert = self.build_incident_alert(
                fusion_result=result,
                camera_metadata=camera_metadata,
                frame_sequence_range=frame_sequence_range,
                forensic_hash=forensic_hash,
                model_contributions=model_contributions,
                broken_at_sequence=broken_at_sequence,
            )
            result.alert = alert

            if router is not None and alert is not None:
                router.route_alert(alert)

        return result, alert
