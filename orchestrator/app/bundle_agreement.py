"""
bundle_agreement.py
===================
Computes a cross-modal agreement view from per-modality verdicts.

Agreement states:
  agree_synthetic  — all modalities say SYNTHETIC
  agree_authentic  — all modalities say AUTHENTIC
  partial          — ≥ 75% agree, minority disagrees
  disagree         — roughly half say SYNTHETIC, half say AUTHENTIC
  single           — only one modality in bundle
  insufficient     — all detectors failed (NO_RESULTS)
"""

from dataclasses import dataclass, field
from typing import List
from bundle_fusion import BundleFusionResult, ModalityScore
from aggregate import AggregateOutcome


@dataclass
class BundleAgreement:
    state: str              # one of the states listed above
    agreement_score: float  # 1.0 = perfect agreement, 0.5 = complete split
    summary: str            # human-readable explanation
    fake_votes: int         # modalities that said SYNTHETIC
    real_votes: int         # modalities that said AUTHENTIC
    total_valid: int
    conflicting_modalities: List[str] = field(default_factory=list)


def compute_agreement(fusion: BundleFusionResult) -> BundleAgreement:
    """
    Compute a cross-modal agreement view from a BundleFusionResult.
    """
    valid = [
        s for s in fusion.modality_scores
        if s.verdict != AggregateOutcome.NO_RESULTS.value
    ]

    if not valid:
        return BundleAgreement(
            state="insufficient", agreement_score=0.0,
            summary="No valid detector results — all detectors failed.",
            fake_votes=0, real_votes=0, total_valid=0,
        )

    if len(valid) == 1:
        s = valid[0]
        return BundleAgreement(
            state="single",
            agreement_score=s.score,
            summary=f"Only one modality ({s.modality}) present — no cross-modal comparison.",
            fake_votes=1 if s.verdict == AggregateOutcome.SYNTHETIC.value else 0,
            real_votes=1 if s.verdict == AggregateOutcome.AUTHENTIC.value else 0,
            total_valid=1,
        )

    synth_mods = [s for s in valid if s.verdict == AggregateOutcome.SYNTHETIC.value]
    auth_mods  = [s for s in valid if s.verdict == AggregateOutcome.AUTHENTIC.value]
    total = len(valid)
    agreement_score = round(max(len(synth_mods), len(auth_mods)) / total, 4)

    if len(synth_mods) == total:
        return BundleAgreement(
            state="agree_synthetic", agreement_score=1.0,
            summary=f"All {total} modalities ({[s.modality for s in synth_mods]}) say SYNTHETIC.",
            fake_votes=total, real_votes=0, total_valid=total,
        )

    if len(auth_mods) == total:
        return BundleAgreement(
            state="agree_authentic", agreement_score=1.0,
            summary=f"All {total} modalities ({[s.modality for s in auth_mods]}) say AUTHENTIC.",
            fake_votes=0, real_votes=total, total_valid=total,
        )

    if agreement_score >= 0.75:
        if len(synth_mods) > len(auth_mods):
            conflict = [s.modality for s in auth_mods]
            return BundleAgreement(
                state="partial", agreement_score=agreement_score,
                summary=(f"Majority ({len(synth_mods)}/{total}) say SYNTHETIC. "
                         f"Disagreeing: {conflict}. "
                         "Possible partial manipulation — genuine caption on a fake image."),
                fake_votes=len(synth_mods), real_votes=len(auth_mods),
                total_valid=total, conflicting_modalities=conflict,
            )
        else:
            conflict = [s.modality for s in synth_mods]
            return BundleAgreement(
                state="partial", agreement_score=agreement_score,
                summary=(f"Majority ({len(auth_mods)}/{total}) say AUTHENTIC. "
                         f"Disagreeing: {conflict}. Possible AI-generated caption on real image."),
                fake_votes=len(synth_mods), real_votes=len(auth_mods),
                total_valid=total, conflicting_modalities=conflict,
            )

    # True disagreement — roughly 50/50
    conflict = [s.modality for s in (synth_mods if len(synth_mods) <= len(auth_mods) else auth_mods)]
    return BundleAgreement(
        state="disagree", agreement_score=agreement_score,
        summary=(
            f"Cross-modal DISAGREEMENT: {len(synth_mods)} modality/ies say SYNTHETIC "
            f"({[s.modality for s in synth_mods]}), "
            f"{len(auth_mods)} say AUTHENTIC ({[s.modality for s in auth_mods]}). "
            "Human review recommended."
        ),
        fake_votes=len(synth_mods), real_votes=len(auth_mods),
        total_valid=total, conflicting_modalities=conflict,
    )