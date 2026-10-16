"""
AEGIS Debate & Arbitration Protocol — Multi-Round Judge Agent.
=============================================================
Implements the 3-round Structured Debate Protocol:
  Round 1: Claim Submission & Ingestion (via claim_wrapper)
  Round 2: Cross-Examination & Context Injection (manifest constraints, LIMITATIONS.md, gaps)
  Round 3: Adjudication & Forensic Ruling (Forensic Precedence Matrix + Judge Guards G1/G2)

Outputs an ISO/IEC 27037 compliant CourtAdmissibleVerdict bound inside an auditable JudgeReport.
Supports Dual-Mode operation:
  - "expert_deterministic_judge" / "deterministic": Zero-latency deterministic precedence matrix.
  - "llm_agentic_judge" / "llm": LLM-synthesized forensic narrative with automatic deterministic fallback.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from debate.arbitrator import JudgeArbitrator
from debate.claim_wrapper import (
    wrap_detector_response,
    wrap_video_detector_outputs,
)
from debate.disagreement import (
    evaluate_disagreement,
    is_coverage_gap,
)
from debate.judge_prompt import JUDGE_PROMPT_VERSION, build_judge_prompt
from debate.llm_client import call_judge_llm
from debate.schemas import (
    ClaimPolarity,
    CourtAdmissibleVerdict,
    CrossExaminationFinding,
    DebateRound,
    DisagreementAnalysis,
    DisagreementType,
    ForensicClaim,
    JudgeReport,
    JudgeVerdictClass,
    OperatingConditions,
)

logger = logging.getLogger("aegis.debate.judge_agent")

DEFAULT_MANIFESTS_DIR = Path(__file__).resolve().parent.parent / "capability_manifests"


class JudgeAgent:
    """The Multi-Round Judge Agent for single-file evidentiary arbitration."""

    def __init__(
        self,
        mode: str = "deterministic",
        arbitrator: Optional[JudgeArbitrator] = None,
        manifests_dir: Optional[Path] = None,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.mode = "llm" if mode.lower() in ("llm", "llm_agentic_judge", "agentic") else "deterministic"
        self.arbitrator = arbitrator or JudgeArbitrator(weights=weights)
        self.manifests_dir = manifests_dir or DEFAULT_MANIFESTS_DIR
        self._manifests_cache: Dict[str, Dict[str, Any]] = self._load_manifests()

    def _load_manifests(self) -> Dict[str, Dict[str, Any]]:
        """Loads capability manifests if present on disk, otherwise empty cache."""
        cache: Dict[str, Dict[str, Any]] = {}
        if self.manifests_dir and self.manifests_dir.is_dir():
            for p in self.manifests_dir.glob("*.json"):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        name = data.get("detector_name")
                        if name:
                            cache[name] = data
                except Exception as exc:
                    logger.debug(f"Failed to read manifest {p.name}: {exc}")
        return cache

    def judge_file(
        self,
        raw_responses: Dict[str, Optional[Dict[str, Any]]],
        conditions: Optional[OperatingConditions] = None,
        job_id: Optional[str] = None,
    ) -> JudgeReport:
        """Single entry point: evaluates raw detector responses for a single file."""
        t0 = time.time()
        resolved_job_id = job_id
        if not resolved_job_id:
            for resp in raw_responses.values():
                if resp and isinstance(resp, dict) and resp.get("job_id"):
                    resolved_job_id = resp["job_id"]
                    break
        resolved_job_id = resolved_job_id or f"job-{uuid.uuid4().hex[:10]}"

        # Round 1: Claim Submissions
        claims = wrap_video_detector_outputs(raw_responses, conditions=conditions)
        return self._execute_debate(claims, conditions=conditions, job_id=resolved_job_id, start_time=t0)

    def judge_claims(
        self,
        claims: List[ForensicClaim],
        conditions: Optional[OperatingConditions] = None,
        job_id: Optional[str] = None,
    ) -> JudgeReport:
        """Evaluates pre-wrapped ForensicClaim objects."""
        t0 = time.time()
        resolved_job_id = job_id or (claims[0].job_id if claims else f"job-{uuid.uuid4().hex[:10]}")
        return self._execute_debate(claims, conditions=conditions, job_id=resolved_job_id, start_time=t0)

    # ── Core Multi-Round Execution ───────────────────────────────────────────
    def _execute_debate(
        self,
        claims: List[ForensicClaim],
        conditions: Optional[OperatingConditions],
        job_id: str,
        start_time: float,
    ) -> JudgeReport:
        rounds: List[DebateRound] = []

        # Round 1: Claim Submissions
        round_1_entries = []
        for c in claims:
            round_1_entries.append({
                "detector_id": c.detector_id,
                "domain": c.domain.value,
                "polarity": c.polarity.value,
                "confidence": c.confidence,
                "effective_confidence": c.effective_confidence,
                "claim": c.claim,
                "flags": c.flags,
                "coverage_gap": c.coverage_gap,
            })
        rounds.append(
            DebateRound(
                round_number=1,
                round_name="Claim Submissions",
                summary=f"Ingested {len(claims)} detector claims across spatial, physiological, and AV domains.",
                details={"claims": round_1_entries},
            )
        )

        # Round 2: Cross-Examination & Context Injection
        findings = self.cross_examine(claims, conditions=conditions)
        findings_entries = [f.model_dump() for f in findings]
        rounds.append(
            DebateRound(
                round_number=2,
                round_name="Cross-Examination & Context Injection",
                summary=f"Cross-examined claims against manifests and LIMITATIONS: {len(findings)} findings logged.",
                details={"findings": findings_entries},
            )
        )

        # Step 1 of Round 3: Baseline Arbitration via Precedence Matrix
        verdict: CourtAdmissibleVerdict = self.arbitrator.arbitrate(claims, job_id=job_id, conditions=conditions)
        analysis: DisagreementAnalysis = evaluate_disagreement(claims)

        # Step 2 of Round 3: Apply Judge Guards (G1 & G2)
        guarded_verdict, guards_applied = self.apply_judge_guards(
            verdict=verdict,
            analysis=analysis,
            claims=claims,
            conditions=conditions,
        )

        # Step 3 of Round 3: Adjudication Narrative & Explainability Mode
        llm_model: Optional[str] = None
        llm_fallback_used: bool = False
        llm_fallback_reason: Optional[str] = None
        prompt_ver: Optional[str] = None
        effective_mode_str = "expert_deterministic_judge"

        active_detector_ids = [c.detector_id for c in claims if not is_coverage_gap(c)]
        applied_rules_in_ruling = [
            adj.discount_reason for adj in guarded_verdict.adjudications if adj.discount_reason
        ]

        if self.mode == "llm":
            prompt_ver = JUDGE_PROMPT_VERSION
            prompt = build_judge_prompt(
                job_id=job_id,
                claims=claims,
                analysis=analysis,
                locked_verdict=guarded_verdict,
                conditions=conditions,
                cross_exam_findings=findings,
            )

            llm_res, model_name, _, err = call_judge_llm(
                prompt=prompt,
                active_detector_ids=active_detector_ids,
                locked_verdict_str=guarded_verdict.final_verdict.value,
                calibrated_score=guarded_verdict.calibrated_score,
                applied_rules=applied_rules_in_ruling,
                guards_applied=guards_applied,
            )

            if llm_res and not err:
                llm_model = model_name
                effective_mode_str = "llm_agentic_judge"
                guarded_verdict.arbitration_mode = "llm_agentic_judge"
                guarded_verdict.forensic_justification = llm_res["forensic_justification"]
            else:
                llm_fallback_used = True
                llm_fallback_reason = err or "LLM generation returned empty payload"
                llm_model = model_name

        rounds.append(
            DebateRound(
                round_number=3,
                round_name="Adjudication & Forensic Ruling",
                summary=(
                    f"Rendered {guarded_verdict.final_verdict.value} (score={guarded_verdict.calibrated_score:.2f}) "
                    f"via {guarded_verdict.arbitration_mode}. Guards triggered: {len(guards_applied)}."
                ),
                details={
                    "job_id": guarded_verdict.job_id,
                    "final_verdict": guarded_verdict.final_verdict.value,
                    "calibrated_score": guarded_verdict.calibrated_score,
                    "siem_tier": guarded_verdict.siem_alert_tier,
                    "guards_applied": guards_applied,
                    "adjudications": [a.model_dump() for a in guarded_verdict.adjudications],
                },
            )
        )

        total_latency_ms = round((time.time() - start_time) * 1000.0, 2)
        transcript_hash = self.compute_transcript_hash(rounds, guarded_verdict)

        return JudgeReport(
            job_id=job_id,
            verdict=guarded_verdict,
            judge_mode=effective_mode_str,
            rounds=rounds,
            cross_examination_findings=findings,
            guards_applied=guards_applied,
            llm_model=llm_model,
            llm_fallback_used=llm_fallback_used,
            llm_fallback_reason=llm_fallback_reason,
            prompt_version=prompt_ver,
            debate_transcript_hash=transcript_hash,
            adjudication_latency_ms=total_latency_ms,
        )

    # ── Round 2: Cross-Examination Engine ────────────────────────────────────
    def cross_examine(
        self,
        claims: List[ForensicClaim],
        conditions: Optional[OperatingConditions] = None,
    ) -> List[CrossExaminationFinding]:
        """Cross-examines each detector's claim against capability manifests and known limitations."""
        findings: List[CrossExaminationFinding] = []
        cond = conditions or OperatingConditions()

        for c in claims:
            det = c.detector_id
            manifest = self._manifests_cache.get(det, {})
            input_constraints = manifest.get("input_constraints", {})

            # 1. Operating Constraint Checks
            min_dur = input_constraints.get("min_duration_seconds")
            if min_dur and cond.duration_seconds is not None and cond.duration_seconds < min_dur:
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det,
                        check_category="operating_constraint",
                        severity="HIGH",
                        finding=(
                            f"Input duration ({cond.duration_seconds:.1f}s) is below required minimum "
                            f"({min_dur:.1f}s) specified in manifest."
                        ),
                        rule_reference="Rule 2 (Short Duration Minimum)",
                        source="capability_manifest",
                    )
                )

            req_audio = input_constraints.get("requires_audio", False)
            if req_audio and (cond.audio_present is False or "not_applicable" in c.flags or "silent_video" in c.flags):
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det,
                        check_category="operating_constraint",
                        severity="MEDIUM",
                        finding="Audio track required by detector manifest is absent from media.",
                        rule_reference="Coverage Gap Isolation",
                        source="capability_manifest",
                    )
                )

            # 2. Known Failure Modes Checks (from LIMITATIONS.md & manifests)
            if det == "rppg":
                if cond.mean_luminance is not None and cond.mean_luminance < 40.0:
                    findings.append(
                        CrossExaminationFinding(
                            detector_id="rppg",
                            check_category="known_failure_mode",
                            severity="HIGH",
                            finding=(
                                f"Mean luminance ({cond.mean_luminance:.1f}/255) violates rPPG lighting threshold "
                                "(<40.0). Chromatic noise mimics flat synthetic skin."
                            ),
                            rule_reference="Rule 1 (Low-Light Inversion Trap)",
                            source="limitations_doc",
                        )
                    )
                if "low_light_attenuation" in c.flags or "insufficient_lighting" in c.flags:
                    findings.append(
                        CrossExaminationFinding(
                            detector_id="rppg",
                            check_category="known_failure_mode",
                            severity="HIGH",
                            finding="Detector self-reported low-light attenuation flag.",
                            rule_reference="Rule 1 (Low-Light Inversion Trap)",
                            source="operating_conditions",
                        )
                    )
                if "short_clip_attenuation" in c.flags:
                    findings.append(
                        CrossExaminationFinding(
                            detector_id="rppg",
                            check_category="known_failure_mode",
                            severity="MEDIUM",
                            finding="Detector self-reported short-clip attenuation flag.",
                            rule_reference="Rule 2 (Short Clip Convergence)",
                            source="operating_conditions",
                        )
                    )
                if "atypical_heart_rate" in c.flags:
                    findings.append(
                        CrossExaminationFinding(
                            detector_id="rppg",
                            check_category="known_failure_mode",
                            severity="LOW",
                            finding="Estimated cardiac frequency is outside standard resting human physiological range.",
                            source="limitations_doc",
                        )
                    )

            if det == "syncnet":
                if "audio_visual_mismatch" in c.flags or "sync_offset_detected" in c.flags:
                    findings.append(
                        CrossExaminationFinding(
                            detector_id="syncnet",
                            check_category="known_failure_mode",
                            severity="MEDIUM",
                            finding="Audio-visual desync detected; cross-examined for narration or foreign dubbing.",
                            rule_reference="Rule 4 (Language/Narration Dubbing)",
                            source="limitations_doc",
                        )
                    )

            # 3. Check Borderline Scores Treated as Coverage Gaps
            if c.polarity == ClaimPolarity.INCONCLUSIVE and not c.coverage_gap:
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det,
                        check_category="borderline_dropped",
                        severity="LOW",
                        finding=(
                            f"Detector confidence ({c.confidence:.2f}) falls in ambiguous borderline zone "
                            "[0.35, 0.65]. Isolated as non-voting gap in arbitration to prevent noise injection."
                        ),
                        source="guardrail",
                    )
                )

            # 4. Explicit Coverage Gaps
            if c.coverage_gap:
                findings.append(
                    CrossExaminationFinding(
                        detector_id=det,
                        check_category="coverage_gap",
                        severity="INFO",
                        finding=f"Coverage gap confirmed for '{det}': {c.claim}",
                        source="guardrail",
                    )
                )

        return findings

    # ── Round 3: Judge Guards Policy Engine ──────────────────────────────────
    def apply_judge_guards(
        self,
        verdict: CourtAdmissibleVerdict,
        analysis: DisagreementAnalysis,
        claims: List[ForensicClaim],
        conditions: Optional[OperatingConditions] = None,
    ) -> Tuple[CourtAdmissibleVerdict, List[str]]:
        """Applies AEGIS forensic integrity guardrails.

        Guards only ever downgrade toward INTEGRITY_UNKNOWN, never toward AUTHENTIC.
        """
        guards_applied: List[str] = []
        active_claims = [c for c in claims if not is_coverage_gap(c)]

        # ── Guard 1 (G1): Unresolved Polarity Conflict Anti-Default ──────────
        # If an active detector asserted SYNTHETIC while another asserted AUTHENTIC,
        # but no Forensic Precedence Rule (Rules 1-4) discounted the contradiction,
        # the system MUST NOT declare AUTHENTIC based merely on weighted averages.
        if analysis.primary_disagreement_type == DisagreementType.POLARITY_INVERSION:
            rule_fired = any(adj.discount_reason is not None for adj in verdict.adjudications)
            if not rule_fired and verdict.final_verdict == JudgeVerdictClass.AUTHENTIC:
                verdict.final_verdict = JudgeVerdictClass.INTEGRITY_UNKNOWN
                verdict.siem_alert_tier = "P2_ELEVATED"
                verdict.arbitration_mode = "expert_deterministic_judge"
                g1_note = (
                    "Guard 1 Triggered (Unresolved Conflict): Active detectors exhibited direct polarity inversion "
                    f"({analysis.conflicting_detectors}), but no Forensic Precedence Rule applied. "
                    "Under Dr. Amr's Anti-Default Mandate, contradictory evidence cannot be certified AUTHENTIC. "
                    "Verdict downgraded to INTEGRITY_UNKNOWN."
                )
                guards_applied.append(g1_note)
                verdict.forensic_justification += f"\n\n[FORENSIC INTEGRITY GUARD]: {g1_note}"

        # ── Guard 2 (G2): Minimum Corroboration for Authentic ────────────────
        # A single detector operating alone while other modalities suffer coverage
        # gaps or dropouts cannot authoritatively certify AUTHENTIC.
        # Under forensic integrity rules, cross-modal corroboration is required.
        if verdict.final_verdict == JudgeVerdictClass.AUTHENTIC:
            if len(active_claims) <= 1 and len(claims) > 1:
                det_name = active_claims[0].detector_id if active_claims else "None"
                verdict.final_verdict = JudgeVerdictClass.INTEGRITY_UNKNOWN
                verdict.siem_alert_tier = "P2_ELEVATED"
                g2_note = (
                    f"Guard 2 Triggered (Single-Detector Corroboration): Detector '{det_name}' "
                    "is the sole active witness while other modalities suffered coverage gaps. "
                    "Under forensic integrity standards, certifying authenticity requires cross-modal corroboration. "
                    "Verdict downgraded to INTEGRITY_UNKNOWN."
                )
                guards_applied.append(g2_note)
                verdict.forensic_justification += f"\n\n[FORENSIC INTEGRITY GUARD]: {g2_note}"

        return verdict, guards_applied

    # ── Tamper-Evident Transcript Hashing ─────────────────────────────────────
    def compute_transcript_hash(
        self,
        rounds: List[DebateRound],
        verdict: CourtAdmissibleVerdict,
    ) -> str:
        """Computes deterministic SHA-256 digest over the entire 3-round debate transcript."""
        payload = {
            "job_id": verdict.job_id,
            "final_verdict": verdict.final_verdict.value,
            "calibrated_score": verdict.calibrated_score,
            "rounds": [r.model_dump() for r in rounds],
            "evidence_manifest_hash": verdict.evidence_manifest_hash,
        }
        raw_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()
