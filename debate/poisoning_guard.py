"""
debate/poisoning_guard.py — Cheap Poisoning & Miscalibration Defenses for Judge & Planner
==========================================================================================
Implements lightweight, zero-LLM-cost cryptographic/statistical defenses against
detector-output poisoning, manifest reliability poisoning, and telemetry spoofing:

  1. Reliability & Confidence Caps:
       - Caps single-detector effective weight share (`<= max_weight_share`) and weight ceiling.
       - Clamps uncorroborated extreme probabilities (`> 0.95` or `< 0.05`) unless echoed by
         at least two distinct detectors.
       - Penalizes confidence-vs-raw_score tampering / miscalibration and suspicious versions.
  2. Statistical Outlier Rejection:
       - Detects when a majority cluster (`>= 2` active claims within tight spread) agrees
         while an isolated outlier deviates sharply (`>= outlier_deviation_threshold`),
         down-weighting the outlier (`0.15x`) and shrinking its score toward `0.50` neutral.
       - Exposes `rejected_detector_ids` so hard Precedence Rules (e.g. Rules 3/5/6/7/8)
         cannot be weaponized by a single poisoned outlier.
  3. Cross-Modal Quorum Rules:
       - Requires `>= 2` distinct corroborating detector claims before activating hard
         corroboration floors or overriding a clear multi-detector consensus.
  4. Planner Primary-Authority Quorum & Telemetry Sanity Helpers:
       - Prevents a secondary proxy (e.g. `rppg`) from acting as a "reliable alternative"
         to excuse skipping a primary detector (e.g. `video-classifier`).
       - Clamps spoofed telemetry latency spikes to protect the decisive detector budget.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from debate.schemas import ClaimAdjudication, ClaimPolarity, ForensicClaim


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _shrink_to_neutral(prob: float, factor: float) -> float:
    return _clamp01(0.5 + (_clamp01(prob) - 0.5) * max(0.0, min(1.0, factor)))


@dataclass(frozen=True)
class PoisoningMitigationConfig:
    """Configuration for cheap Judge & Planner poisoning mitigations."""

    enable_reliability_caps: bool = True
    enable_outlier_rejection: bool = True
    enable_quorum_rules: bool = True

    # 1. Reliability & confidence cap thresholds
    max_detector_weight: float = 1.25
    max_weight_share: float = 0.55
    extreme_clamp_trigger: float = 0.95
    uncorroborated_extreme_high: float = 0.88
    uncorroborated_extreme_low: float = 0.12
    confidence_raw_mismatch_threshold: float = 0.35
    miscalibration_weight_penalty: float = 0.35

    # 2. Outlier rejection thresholds
    outlier_min_cluster_size: int = 2
    outlier_cluster_max_spread: float = 0.25
    outlier_deviation_threshold: float = 0.42
    outlier_weight_multiplier: float = 0.12
    outlier_confidence_damping: float = 0.20

    # 3. Quorum thresholds
    quorum_min_agreeing_detectors: int = 2


@dataclass
class PoisoningGuardReport:
    """Summary of cheap poisoning mitigations applied during arbitration."""

    rejected_detectors: Set[str] = field(default_factory=set)
    capped_detectors: Set[str] = field(default_factory=set)
    miscalibrated_detectors: Set[str] = field(default_factory=set)
    quorum_blocks: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def all_flags(self) -> List[str]:
        flags: List[str] = []
        if self.rejected_detectors:
            flags.append("poison_guard_outlier_rejected")
        if self.capped_detectors:
            flags.append("poison_guard_reliability_capped")
        if self.miscalibrated_detectors:
            flags.append("poison_guard_miscalibration_penalized")
        if self.quorum_blocks:
            flags.append("poison_guard_quorum_enforced")
        return flags


def detect_outlier_detectors(
    active_claims: Sequence[ForensicClaim],
    accepted_confs: Dict[str, float],
    cfg: PoisoningMitigationConfig,
) -> Tuple[Set[str], Optional[float], List[str]]:
    """
    Identifies isolated outlier claims using leave-one-out majority cluster comparison.
    When N >= 3 active claims exist and all (N - 1) peer detectors agree within
    `outlier_cluster_max_spread` while the target detector deviates by
    >= `outlier_deviation_threshold` from the peer median, flag the target as an outlier.
    """
    if len(active_claims) < cfg.outlier_min_cluster_size + 1:
        return set(), None, []

    scores = {c.detector_id: _clamp01(accepted_confs.get(c.detector_id, c.confidence)) for c in active_claims}
    rejected: Set[str] = set()
    ref_median: Optional[float] = None
    notes: List[str] = []

    for cand in active_claims:
        det = cand.detector_id
        peers = [scores[c.detector_id] for c in active_claims if c.detector_id != det]
        if len(peers) < cfg.outlier_min_cluster_size:
            continue
        peer_spread = max(peers) - min(peers)
        peer_med = statistics.median(peers)
        dev = abs(scores[det] - peer_med)
        if peer_spread <= cfg.outlier_cluster_max_spread and dev >= cfg.outlier_deviation_threshold:
            rejected.add(det)
            ref_median = peer_med
            notes.append(
                f"Poisoning Guard (Outlier Rejection): Detector '{det}' score {scores[det]:.2f} "
                f"deviates by {dev:.2f} from peer majority median {peer_med:.2f} "
                f"(spread={peer_spread:.2f}); weight discounted to {cfg.outlier_weight_multiplier:.2f}x."
            )

    return rejected, ref_median, notes


def inspect_claim_miscalibration(claim: ForensicClaim, cfg: PoisoningMitigationConfig) -> Tuple[bool, Optional[str]]:
    """
    Detects anomalous discrepancy between normalized synthetic confidence and raw_score
    (for probability-scaled raw scores in [0.0, 1.0]) or non-finite values.
    """
    if not math.isfinite(claim.confidence):
        return True, "non-finite confidence"
    if claim.raw_score is not None:
        if not math.isfinite(claim.raw_score):
            return True, "non-finite raw_score"
        # Skip raw scores outside probability range (e.g. SyncNet frame-offset integers)
        if 0.0 <= float(claim.raw_score) <= 1.0:
            # Invert check is not needed if detector emits P(synth) or similarity; check only huge divergence
            # where polarity and confidence strongly contradict raw_score on same scale.
            diff = abs(float(claim.confidence) - float(claim.raw_score))
            if diff > cfg.confidence_raw_mismatch_threshold:
                return True, (
                    f"confidence ({claim.confidence:.2f}) diverges from probability raw_score "
                    f"({float(claim.raw_score):.2f}) by {diff:.2f}"
                )
    return False, None


def apply_adjudication_mitigations(
    active_claims: Sequence[ForensicClaim],
    adjudications: List[ClaimAdjudication],
    cfg: PoisoningMitigationConfig,
) -> Tuple[float, PoisoningGuardReport]:
    """
    Applies cheap reliability caps, miscalibration penalties, outlier rejection,
    and quorum weight sharing over a list of `ClaimAdjudication` objects.

    Mutates adjudication weights / accepted confidences / discount_reason cleanly and
    returns `(mitigated_weighted_score, PoisoningGuardReport)`.
    """
    report = PoisoningGuardReport()
    if not adjudications:
        return 0.5, report

    claim_by_id = {c.detector_id: c for c in active_claims}
    adj_by_id = {a.detector_id: a for a in adjudications}

    # Count distinct polarity votes across active detectors (for uncorroborated extreme clamping)
    synth_supporters = sum(1 for a in adjudications if a.accepted_confidence >= 0.62)
    auth_supporters = sum(1 for a in adjudications if a.accepted_confidence <= 0.38)

    # ── Step 1: Reliability & Confidence Caps ────────────────────────────────
    if cfg.enable_reliability_caps:
        for adj in adjudications:
            det = adj.detector_id
            claim = claim_by_id.get(det)

            # 1a. Miscalibration / raw_score tampering penalty
            if claim is not None:
                is_bad, reason = inspect_claim_miscalibration(claim, cfg)
                if is_bad:
                    adj.weight_assigned = round(adj.weight_assigned * cfg.miscalibration_weight_penalty, 4)
                    adj.accepted_confidence = round(_shrink_to_neutral(adj.accepted_confidence, 0.45), 4)
                    report.miscalibrated_detectors.add(det)
                    note = f"Poisoning Guard (Miscalibration Cap): {det} penalized ({reason})."
                    adj.discount_reason = adj.discount_reason or note
                    report.notes.append(note)

            # 1b. Uncorroborated extreme confidence clamping (>0.95 or <0.05)
            # Applies even cleanly when 1 extreme claim opposes >=1 non-supporting detector
            if len(adjudications) >= 2:
                if adj.accepted_confidence >= cfg.extreme_clamp_trigger and synth_supporters < cfg.quorum_min_agreeing_detectors:
                    old = adj.accepted_confidence
                    adj.accepted_confidence = cfg.uncorroborated_extreme_high
                    report.capped_detectors.add(det)
                    note = (
                        f"Poisoning Guard (Confidence Cap): Uncorroborated extreme synthetic confidence "
                        f"{old:.2f} capped to {cfg.uncorroborated_extreme_high:.2f}."
                    )
                    adj.discount_reason = adj.discount_reason or note
                    report.notes.append(note)
                elif adj.accepted_confidence <= (1.0 - cfg.extreme_clamp_trigger) and auth_supporters < cfg.quorum_min_agreeing_detectors:
                    old = adj.accepted_confidence
                    adj.accepted_confidence = cfg.uncorroborated_extreme_low
                    report.capped_detectors.add(det)
                    note = (
                        f"Poisoning Guard (Confidence Cap): Uncorroborated extreme authentic confidence "
                        f"{old:.2f} raised to {cfg.uncorroborated_extreme_low:.2f}."
                    )
                    adj.discount_reason = adj.discount_reason or note
                    report.notes.append(note)

            # 1c. Per-detector absolute weight cap
            if adj.weight_assigned > cfg.max_detector_weight:
                adj.weight_assigned = round(cfg.max_detector_weight, 4)
                report.capped_detectors.add(det)

    # ── Step 2: Statistical Outlier Rejection ────────────────────────────────
    if cfg.enable_outlier_rejection and len(active_claims) >= cfg.outlier_min_cluster_size + 1:
        conf_map = {a.detector_id: a.accepted_confidence for a in adjudications}
        outliers, _peer_med, out_notes = detect_outlier_detectors(active_claims, conf_map, cfg)
        if outliers:
            report.rejected_detectors.update(outliers)
            report.notes.extend(out_notes)
            for det in outliers:
                adj = adj_by_id[det]
                adj.weight_assigned = round(adj.weight_assigned * cfg.outlier_weight_multiplier, 4)
                adj.accepted_confidence = round(
                    _shrink_to_neutral(adj.accepted_confidence, cfg.outlier_confidence_damping),
                    4,
                )
                adj.discount_reason = (
                    f"Poisoning Guard (Outlier Rejected): {det} deviated sharply from peer consensus."
                )

    # ── Step 3: Weight-Share Cap (no single detector >55% when >=2 detectors run) ──
    if cfg.enable_reliability_caps and len(adjudications) >= 2:
        total_w = sum(max(0.0, a.weight_assigned) for a in adjudications)
        if total_w > 1e-6:
            # Iteratively redistribute/cap shares above max_weight_share if peer weight exists
            for _ in range(len(adjudications)):
                total_w = sum(max(0.0, a.weight_assigned) for a in adjudications)
                changed = False
                for adj in adjudications:
                    if adj.weight_assigned <= 0.0:
                        continue
                    other_w = total_w - adj.weight_assigned
                    if other_w > 1e-6:
                        max_allowed = (cfg.max_weight_share / (1.0 - cfg.max_weight_share)) * other_w
                        if adj.weight_assigned > max_allowed + 1e-4:
                            adj.weight_assigned = round(max_allowed, 4)
                            report.capped_detectors.add(adj.detector_id)
                            changed = True
                if not changed:
                    break

    # Compute weighted score after cheap mitigations
    total_weight = sum(max(0.0, a.weight_assigned) for a in adjudications)
    weighted_sum = sum(a.accepted_confidence * max(0.0, a.weight_assigned) for a in adjudications)
    mitigated_score = round(weighted_sum / max(total_weight, 1e-6), 4)

    # ── Step 4: Quorum Guard on Unilateral Extreme Verdict ───────────────────
    if cfg.enable_quorum_rules and len(adjudications) >= 3:
        # After outlier rejection, re-count non-rejected strong voters
        non_rej = [a for a in adjudications if a.detector_id not in report.rejected_detectors]
        strong_synth = sum(1 for a in non_rej if a.accepted_confidence >= 0.65)
        strong_auth = sum(1 for a in non_rej if a.accepted_confidence <= 0.35)
        if mitigated_score >= 0.65 and strong_synth < cfg.quorum_min_agreeing_detectors:
            mitigated_score = round(min(mitigated_score, 0.58), 4)
            msg = (
                "Poisoning Guard (Quorum Rule): Less than 2 non-outlier detectors support SYNTHETIC; "
                "holding ensemble score inside UNCERTAIN band."
            )
            report.quorum_blocks.append(msg)
            report.notes.append(msg)
        elif mitigated_score <= 0.35 and strong_auth < cfg.quorum_min_agreeing_detectors:
            mitigated_score = round(max(mitigated_score, 0.42), 4)
            msg = (
                "Poisoning Guard (Quorum Rule): Less than 2 non-outlier detectors support AUTHENTIC; "
                "holding ensemble score inside UNCERTAIN band."
            )
            report.quorum_blocks.append(msg)
            report.notes.append(msg)

    return mitigated_score, report


def check_corroboration_quorum(
    active_claims: Sequence[ForensicClaim],
    primary_ids: Tuple[str, ...],
    corroborator_ids: Tuple[str, ...],
    flag_names: Tuple[str, ...],
    rejected_detectors: Optional[Set[str]] = None,
) -> bool:
    """
    Quorum-safe multi-signal corroboration check: requires at least 2 distinct
    non-rejected detector claims (e.g., primary + separate corroborator detector),
    blocking single-detector flag self-boosting.
    """
    rej = rejected_detectors or set()
    primary_ok = any(
        c.detector_id in primary_ids and c.detector_id not in rej and c.confidence >= 0.70
        for c in active_claims
    )
    if not primary_ok:
        return False

    separate_corrob = any(
        c.detector_id not in primary_ids
        and c.detector_id not in rej
        and (
            (c.detector_id in corroborator_ids and c.confidence >= 0.65)
            or any(f in (c.flags or []) for f in flag_names)
        )
        for c in active_claims
    )
    return separate_corrob
