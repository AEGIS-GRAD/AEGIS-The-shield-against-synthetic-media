"""
AEGIS Debate & Arbitration Protocol — Judge Agent Prompt Builder.
Builds structured prompts for the LLM Explainability Mode (ISO/IEC 27037 Court-Admissible Standard).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from debate.schemas import (
    CourtAdmissibleVerdict,
    CrossExaminationFinding,
    DisagreementAnalysis,
    ForensicClaim,
    OperatingConditions,
)

JUDGE_PROMPT_VERSION = "judge-v1.0"


def build_judge_prompt(
    job_id: str,
    claims: List[ForensicClaim],
    analysis: DisagreementAnalysis,
    locked_verdict: CourtAdmissibleVerdict,
    conditions: Optional[OperatingConditions] = None,
    cross_exam_findings: Optional[List[CrossExaminationFinding]] = None,
) -> str:
    """Builds an authoritative prompt for the LLM Judge Agent.

    The mathematical verdict and calibrated score are strictly locked facts.
    The LLM's mandate is to draft an exhaustive, court-admissible forensic justification.
    """
    findings_list = cross_exam_findings or []
    
    # Format claims cleanly for the prompt
    claims_payload = []
    for c in claims:
        claims_payload.append({
            "detector_id": c.detector_id,
            "domain": c.domain.value,
            "polarity": c.polarity.value,
            "raw_confidence": c.confidence,
            "effective_confidence": c.effective_confidence,
            "claim": c.claim,
            "flags": c.flags,
            "coverage_gap": c.coverage_gap,
            "attenuation": c.attenuation_factors.model_dump(),
        })

    findings_payload = []
    for f in findings_list:
        findings_payload.append({
            "detector_id": f.detector_id,
            "category": f.check_category,
            "severity": f.severity,
            "finding": f.finding,
            "source": f.source,
        })

    adjudications_payload = []
    for adj in locked_verdict.adjudications:
        adjudications_payload.append({
            "detector_id": adj.detector_id,
            "accepted_confidence": adj.accepted_confidence,
            "weight_assigned": adj.weight_assigned,
            "discount_reason": adj.discount_reason,
        })

    cond_dict = (
        conditions.model_dump()
        if conditions
        else {"duration_seconds": None, "mean_luminance": None, "face_detected": True, "audio_present": True}
    )

    prompt = f"""# AEGIS CHIEF FORENSIC ARBITRATOR & JUDGE AGENT (v{JUDGE_PROMPT_VERSION})
Standard: ISO/IEC 27037 Digital Evidence Admissibility & Chain of Custody

You are the impartial forensic Judge Agent for the AEGIS Synthetic Media Verification Platform.
Your task is to draft a definitive, court-admissible chain-of-evidence narrative justifying the arbitration ruling rendered below.

## SECTION 1. VERDICT FACT SHEET (LOCKED BY FORENSIC PRECEDENCE MATRIX)
- Job ID: {job_id}
- Final Verdict: {locked_verdict.final_verdict.value} (NON-NEGOTIABLE)
- Calibrated Forensic Score: {locked_verdict.calibrated_score:.4f} [Scale: 0.00 = Authentic, 1.00 = Synthetic]
- Confidence Interval: [{locked_verdict.confidence_interval[0]:.3f}, {locked_verdict.confidence_interval[1]:.3f}]
- Arbitration Mode: {locked_verdict.arbitration_mode}
- SIEM Alert Tier: {locked_verdict.siem_alert_tier}
- Disagreement Classification: {analysis.primary_disagreement_type.value} (Spread Δ = {analysis.confidence_spread:.2f})

## SECTION 2. OPERATING CONDITIONS
{json.dumps(cond_dict, indent=2)}

## SECTION 3. SUBMITTED DETECTOR CLAIMS (ROUND 1)
{json.dumps(claims_payload, indent=2)}

## SECTION 4. CROSS-EXAMINATION FINDINGS (ROUND 2)
{json.dumps(findings_payload, indent=2)}

## SECTION 5. CLAIM ADJUDICATIONS & APPLIED PRECEDENCE WEIGHTS
{json.dumps(adjudications_payload, indent=2)}

## SECTION 6. MANDATORY REASONING GUIDELINES
1. NEVER contradict the locked Final Verdict ({locked_verdict.final_verdict.value}) or Calibrated Score ({locked_verdict.calibrated_score:.2f}).
2. Explicitly address each active detector by name ({", ".join(c.detector_id for c in claims if not c.coverage_gap)}).
3. Clearly explain why any evidence was discounted (e.g. low-light chromatic noise on rPPG, donor pulse preservation in face-swap inpainting, or audio dubbing).
4. If coverage gaps exist ({", ".join(analysis.coverage_gaps) if analysis.coverage_gaps else "None"}), confirm they were treated as unobserved blind spots rather than evidence of authenticity or synthesis.
5. If the verdict is INTEGRITY_UNKNOWN, state clearly that unresolved contradiction or environmental degradation prevents certifying authenticity under forensic standards.
6. Return ONLY valid JSON with no markdown wrapping outside the code block.

## EXPECTED JSON OUTPUT SCHEMA:
{{
  "forensic_justification": "Comprehensive narrative explaining the evidentiary basis, physical interpretations, applied forensic rules, and final conclusion.",
  "adjudication_summary": "One-sentence executive summary of the ruling."
}}
"""
    return prompt.strip()
