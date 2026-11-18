"""Tests for AEGIS Adversarial Robustness v2: black-box query evasion, agentic text, hard negatives & defenses."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pytest

from eval.adaptive_robustness.agentic_text_paraphraser import (
    AdaptiveHeuristicParaphraser,
    run_agentic_text_evasion,
    semantic_similarity,
    summarize_text_curves,
)
from eval.adaptive_robustness.blackbox_evasion import (
    run_adaptive_transform_attack,
    run_square_attack,
    summarize_vision_curves,
)
from eval.adaptive_robustness.detectors import (
    AdaptiveTarget,
    HardenedTextDefense,
    HardenedVisionDefense,
    LocalImageFrameTarget,
    LocalTextForensicTarget,
    TargetScore,
)
from eval.adaptive_robustness.hard_negatives import export_hard_negatives


class _SensitivePixelTarget(AdaptiveTarget):
    """Deterministic surrogate image/video detector sensitive to patch pixels for black-box evasion tests."""

    def __init__(self, modality: str = "image") -> None:
        super().__init__()
        self.name = f"surrogate_{modality}"
        self.modality = modality
        self.model_version = "surrogate-v1"

    def _score_impl(self, payload: Any, meta: Dict[str, Any]) -> TargetScore:
        arr = np.asarray(payload, dtype=np.float32)
        if arr.ndim == 4:
            arr = arr.mean(axis=0)
        # Scores near 0.90 when center mean intensity >= 120; drops below 0.5 as intensities diverge from center mean
        patch = arr[16:48, 16:48, :]
        mean_val = float(patch.mean())
        conf = float(np.clip(0.92 - abs(128.0 - mean_val) * 0.04, 0.05, 0.99))
        return TargetScore(
            detector_name=self.name,
            model_version=self.model_version,
            modality=self.modality,
            confidence=round(conf, 4),
            raw_score=round(conf, 4),
            flags=["high_confidence_synthetic"] if conf >= 0.8 else [],
        )


def test_square_attack_respects_linf_and_query_budget_image_and_video():
    clean_img = np.full((64, 64, 3), 128, dtype=np.uint8)
    target = _SensitivePixelTarget("image")
    eps = 16.0 / 255.0
    trace, adv_img = run_square_attack(
        "s1", clean_img, target, threshold=0.5, eps=eps, max_queries=80, p_init=0.4, seed=7
    )
    assert trace.queries_used <= 80
    assert trace.linf_norm <= eps + (1.0 / 255.0)
    assert trace.score_drop > 0.0
    assert adv_img.shape == (64, 64, 3)

    # Multi-frame video case
    clean_vid = [clean_img.copy(), clean_img.copy(), clean_img.copy()]
    v_target = _SensitivePixelTarget("video")
    v_trace, adv_vid = run_square_attack(
        "v1", clean_vid, v_target, threshold=0.5, eps=eps, max_queries=80, p_init=0.4, seed=9
    )
    assert v_trace.modality == "video"
    assert v_trace.queries_used <= 80
    assert adv_vid.shape == (3, 64, 64, 3)

    curves = summarize_vision_curves([trace, v_trace], threshold=0.5)
    assert len(curves) >= 2


def test_adaptive_transform_search_respects_psnr_floor():
    rng = np.random.default_rng(1)
    clean_img = rng.integers(110, 145, size=(64, 64, 3), dtype=np.uint8)
    target = _SensitivePixelTarget("image")
    trace, adv = run_adaptive_transform_attack(
        "tf1", clean_img, target, threshold=0.5, max_queries=25, min_psnr_db=20.0, seed=5
    )
    assert trace.queries_used <= 25
    assert trace.psnr_db >= 20.0
    assert adv.shape == (64, 64, 3)


def test_agentic_text_paraphraser_feedback_and_semantic_gate():
    clean_text = (
        "Organizations frequently implement layered authentication controls to mitigate unauthorized network access. "
        "Furthermore, continuous monitoring frameworks demonstrate consistent improvements in threat detection accuracy across distributed environments. "
        "Additionally, security teams must evaluate configuration baselines routinely to maintain strict compliance posture. "
        "Therefore, adopting automated verification pipelines remains essential for safeguarding critical infrastructure systems. "
        "Consequently, consistent audit procedures facilitate rapid incident response."
    )
    target = LocalTextForensicTarget(chunk_floor_defense=False)
    rewriter = AdaptiveHeuristicParaphraser(seed=42)
    trace = run_agentic_text_evasion(
        "txt1", clean_text, target, rewriter, threshold=0.5, max_turns=5, beam_size=3, min_similarity=0.35
    )
    assert trace.clean_confidence > 0.5
    assert trace.score_drop > 0.0
    assert trace.best_similarity >= 0.35
    assert len(trace.history) >= 2
    assert semantic_similarity(clean_text, "short gibberish") < 0.35

    curves = summarize_text_curves([trace], threshold=0.5, max_turns=5)
    assert len(curves) == 6


def test_mitigation_wrappers_quantize_throttle_and_resist_evasion():
    clean_img = np.full((64, 64, 3), 128, dtype=np.uint8)
    base = _SensitivePixelTarget("image")
    hardened = HardenedVisionDefense(
        base, num_views=4, confidence_quantum=0.05, query_burst_limit=3, seed=11
    )
    r1 = hardened.query(clean_img)
    assert "defense_multiview_smoothing" in r1.flags
    assert round(r1.confidence * 20) == pytest.approx(r1.confidence * 20, abs=1e-6)
    for _ in range(3):
        last = hardened.query(clean_img)
    assert "query_burst_detected" in last.flags
    assert last.confidence >= 0.55

    text_base = LocalTextForensicTarget(chunk_floor_defense=False)
    text_def = HardenedTextDefense(text_base, confidence_quantum=0.05)
    ai_para = (
        "Furthermore, continuous monitoring frameworks demonstrate consistent improvements in threat detection accuracy. "
        "Additionally, security teams must evaluate configuration baselines routinely to maintain compliance. "
        "Therefore, automated verification remains essential. "
        "Wait — why not toss one chaotic, human-like tiny joke right here? Oops! Tiny blurb! "
        "Consequently, standardized compliance reporting demonstrates measurable progress across deployments."
    )
    res_raw = text_base.query(ai_para)
    res_def = text_def.query(ai_para)
    assert "defense_chunk_floor" in res_def.flags
    assert res_def.confidence >= res_raw.confidence - 0.05


def test_hard_negative_export_writes_artifacts_and_manifests(tmp_path: Path):
    clean_img = np.full((64, 64, 3), 128, dtype=np.uint8)
    target = _SensitivePixelTarget("image")
    tr_img, adv_img = run_square_attack("hn_img", clean_img, target, max_queries=30, eps=24 / 255)
    txt_target = LocalTextForensicTarget()
    txt = (
        "Organizations frequently implement layered controls to mitigate unauthorized access across environments. "
        "Furthermore, continuous monitoring frameworks demonstrate consistent accuracy gains across distributed networks. "
        "Additionally, security teams evaluate baselines routinely to ensure strict compliance posture. "
        "Therefore, automated pipelines remain essential for safeguarding critical infrastructure systems."
    )
    tr_txt = run_agentic_text_evasion("hn_txt", txt, txt_target, AdaptiveHeuristicParaphraser(), max_turns=3)

    summary = export_hard_negatives([(tr_img, adv_img)], [tr_txt], out_dir=tmp_path)
    assert summary["total_exported"] >= 1
    assert Path(summary["jsonl_path"]).is_file()
    assert Path(summary["csv_path"]).is_file()
    lines = [json.loads(line) for line in Path(summary["jsonl_path"]).read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == summary["total_exported"]
    for row in lines:
        assert (tmp_path / row["artifact_path"]).is_file()


def test_local_image_target_loads_real_edge_weights():
    img_target = LocalImageFrameTarget()
    arr = np.full((224, 224, 3), 120, dtype=np.uint8)
    res = img_target.query(arr)
    assert 0.0 <= res.confidence <= 1.0
    assert res.modality == "image"
