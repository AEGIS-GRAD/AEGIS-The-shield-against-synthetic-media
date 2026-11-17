"""CLI runner for AEGIS Adversarial Robustness v2 (adaptive, agentic, hard negatives & mitigation re-test)."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.adaptive_robustness.agentic_text_paraphraser import (  # noqa: E402
    AdaptiveHeuristicParaphraser,
    OpenRouterParaphraser,
    TextEvasionTrace,
    run_agentic_text_evasion,
    summarize_text_curves,
)
from eval.adaptive_robustness.benchmark_data import (  # noqa: E402
    load_text_benchmark_samples,
    load_vision_benchmark_samples,
)
from eval.adaptive_robustness.blackbox_evasion import (  # noqa: E402
    EvasionCurveRow,
    VisionEvasionTrace,
    run_adaptive_transform_attack,
    run_square_attack,
    summarize_vision_curves,
)
from eval.adaptive_robustness.detectors import (  # noqa: E402
    AdaptiveTarget,
    HTTPDetectorTarget,
    HardenedTextDefense,
    HardenedVisionDefense,
    LocalImageFrameTarget,
    LocalTextForensicTarget,
    LocalVideoEfficientNetTarget,
)
from eval.adaptive_robustness.hard_negatives import export_hard_negatives  # noqa: E402


def _write_curves_csv(rows: List[EvasionCurveRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "phase",
        "modality",
        "detector_name",
        "attack_method",
        "budget_unit",
        "budget_value",
        "total_detected_clean",
        "evaded_count",
        "asr",
        "mean_confidence",
        "mean_score_drop",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for phase, row in rows:
            data = asdict(row)
            data["phase"] = phase
            writer.writerow(data)


def _format_markdown_report(
    generated_utc: str,
    threshold: float,
    eps: float,
    max_queries: int,
    max_turns: int,
    baseline_vision: List[VisionEvasionTrace],
    mitigated_vision: List[VisionEvasionTrace],
    baseline_text: List[TextEvasionTrace],
    mitigated_text: List[TextEvasionTrace],
    curve_rows: List[Tuple[str, EvasionCurveRow]],
    hn_summary: Dict[str, Any],
) -> str:
    lines: List[str] = [
        "# AEGIS Adversarial Robustness v2 — Adaptive & Agentic Evasion Report",
        "",
        f"- **Generated (UTC):** `{generated_utc}`",
        f"- **Threshold:** `{threshold:.2f}` (evaded when confidence `< {threshold:.2f}`)",
        f"- **Vision Query Budgets:** Square Attack `L_inf <= {eps:.3f}` (`{int(round(eps * 255))}/255`), `max_queries={max_queries}`; Adaptive Transform Search `max_queries=60`",
        f"- **Agentic Text Budget:** `max_turns={max_turns}`, beam candidates per turn, semantic similarity `>= 0.35`, word-count guard `>= 40`",
        "",
        "## 1. Before vs. After Mitigation Summary",
        "",
        "| Modality | Detector | Attack Method | Phase | Clean Detected | Evaded | Final ASR | Mean Score Drop |",
        "| :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: |",
    ]

    def _add_vision_summary(phase: str, traces: List[VisionEvasionTrace]) -> None:
        grouped: Dict[Tuple[str, str, str], List[VisionEvasionTrace]] = {}
        for t in traces:
            if t.clean_confidence >= threshold:
                grouped.setdefault((t.modality, t.detector_name, t.attack_method), []).append(t)
        for (mod, det, atk), items in sorted(grouped.items()):
            evaded = sum(1 for x in items if x.flipped)
            drop = sum(x.score_drop for x in items) / len(items)
            lines.append(
                f"| `{mod}` | `{det}` | `{atk}` | **{phase}** | {len(items)} | {evaded} | **{evaded / len(items):.1%}** | `{drop:+.3f}` |"
            )

    def _add_text_summary(phase: str, traces: List[TextEvasionTrace]) -> None:
        grouped: Dict[Tuple[str, str], List[TextEvasionTrace]] = {}
        for t in traces:
            if t.clean_confidence >= threshold:
                grouped.setdefault((t.detector_name, t.rewriter_name), []).append(t)
        for (det, atk), items in sorted(grouped.items()):
            evaded = sum(1 for x in items if x.flipped)
            drop = sum(x.score_drop for x in items) / len(items)
            lines.append(
                f"| `text` | `{det}` | `{atk}` | **{phase}** | {len(items)} | {evaded} | **{evaded / len(items):.1%}** | `{drop:+.3f}` |"
            )

    _add_vision_summary("before_mitigation", baseline_vision)
    _add_vision_summary("after_mitigation", mitigated_vision)
    _add_text_summary("before_mitigation", baseline_text)
    _add_text_summary("after_mitigation", mitigated_text)

    lines.extend([
        "",
        "## 2. Evasion Success-Rate Curves (ASR vs. Budget)",
        "",
        "| Phase | Modality | Detector | Attack | Budget | ASR | Mean Conf | Mean Drop |",
        "| :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: |",
    ])
    for phase, r in curve_rows:
        lines.append(
            f"| `{phase}` | `{r.modality}` | `{r.detector_name}` | `{r.attack_method}` | `{r.budget_value} {r.budget_unit}` | {r.asr:.1%} | `{r.mean_confidence:.3f}` | `{r.mean_score_drop:+.3f}` |"
        )

    lines.extend([
        "",
        "## 3. Hard-Negative Pool Exported for AI Fine-Tuning",
        "",
        f"- **Manifest JSONL:** `{hn_summary.get('jsonl_path')}`",
        f"- **Manifest CSV:** `{hn_summary.get('csv_path')}`",
        f"- **Total Hard Negatives Exported:** `{hn_summary.get('total_exported')}` (`{hn_summary.get('by_modality')}`)",
        "",
        "## 4. Prioritized Hardening Recommendations",
        "",
        "1. **[P0 — Vision Query Stability]** Deploy multi-view randomized smoothing (`HardenedVisionDefense`: 5 random jittered crops + JPEG-80 re-encoding + light noise average) before model scoring to disrupt greedy Square Attack trajectory monotonicity.",
        "2. **[P0 — Output Quantization & Query-Burst Guard]** Quantize externally exposed detector confidences to `0.05` increments (or verdict-tier bands at the gateway) and rate-limit near-identical perceptual hash (`aHash`) probe bursts to block zeroth-order finite-difference and Square searches.",
        "3. **[P1 — Text Window Floor Pooling]** Aggregate overlapping 3-sentence windows with a `max`/percentile floor (`HardenedTextDefense`) rather than whole-document mean alone so injecting human-like filler sentences cannot dilute synthetic regions.",
        "4. **[P1 — Adversarial Retraining on Hard Negatives]** Fine-tune `OwensLab/commfor-model-384`, `EfficientNet-B0`, and `Desklib LoRA` on the exported `eval/datasets/hard_negatives/` manifest (paired Square Attack, adaptive transform, and multi-turn paraphrased positives).",
        "5. **[P2 — Decision-Only External Exposure]** Keep raw float logits internal to the Judge arbitration bus while returning discrete confidence bands outside the trust boundary.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="AEGIS Adversarial Robustness v2 Runner")
    parser.add_argument("--image-url", default="", help="Optional live HTTP/HTTPS image detector URL")
    parser.add_argument("--video-url", default="", help="Optional live HTTP/HTTPS video detector URL")
    parser.add_argument("--text-url", default="", help="Optional live HTTP/HTTPS text detector URL")
    parser.add_argument("--internal-token", default="", help="Optional x-internal-token header")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--eps", type=float, default=16.0 / 255.0)
    parser.add_argument("--max-queries", type=int, default=120)
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--beam-size", type=int, default=3)
    parser.add_argument("--max-samples", type=int, default=6)
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "eval" / "reports"))
    parser.add_argument("--hard-neg-dir", default=str(REPO_ROOT / "eval" / "datasets" / "hard_negatives"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    img_samples, vid_samples = load_vision_benchmark_samples(
        max_images=args.max_samples, max_video_clips=args.max_samples, frames_per_clip=4
    )
    txt_samples = load_text_benchmark_samples(limit=args.max_samples)

    img_target: AdaptiveTarget = (
        HTTPDetectorTarget("commfor_http", "image", args.image_url, internal_token=args.internal_token or None)
        if args.image_url
        else LocalImageFrameTarget()
    )
    vid_target: AdaptiveTarget = (
        HTTPDetectorTarget("video_http", "video", args.video_url, internal_token=args.internal_token or None)
        if args.video_url
        else LocalVideoEfficientNetTarget()
    )
    txt_target: AdaptiveTarget = (
        HTTPDetectorTarget("desklib_http", "text", args.text_url, internal_token=args.internal_token or None)
        if args.text_url
        else LocalTextForensicTarget(chunk_floor_defense=False)
    )

    rewriter = (
        OpenRouterParaphraser()
        if os.getenv("OPENROUTER_API_KEY", "").strip()
        else AdaptiveHeuristicParaphraser(seed=args.seed)
    )

    baseline_vision_traces: List[VisionEvasionTrace] = []
    vision_artifacts: List[Tuple[VisionEvasionTrace, Any]] = []
    baseline_text_traces: List[TextEvasionTrace] = []

    print("[Phase 1/3] Running adaptive black-box evasion BEFORE mitigations...")
    for i, sample in enumerate(img_samples):
        tr_sq, adv_sq = run_square_attack(
            sample.sample_id, sample.payload, img_target, threshold=args.threshold, eps=args.eps, max_queries=args.max_queries, seed=args.seed + i
        )
        baseline_vision_traces.append(tr_sq)
        vision_artifacts.append((tr_sq, adv_sq))
        tr_tf, adv_tf = run_adaptive_transform_attack(
            sample.sample_id, sample.payload, img_target, threshold=args.threshold, max_queries=60, seed=args.seed + 100 + i
        )
        baseline_vision_traces.append(tr_tf)
        vision_artifacts.append((tr_tf, adv_tf))

    for i, sample in enumerate(vid_samples):
        tr_sq, adv_sq = run_square_attack(
            sample.sample_id, sample.payload, vid_target, threshold=args.threshold, eps=args.eps, max_queries=args.max_queries, seed=args.seed + 200 + i
        )
        baseline_vision_traces.append(tr_sq)
        vision_artifacts.append((tr_sq, adv_sq))
        tr_tf, adv_tf = run_adaptive_transform_attack(
            sample.sample_id, sample.payload, vid_target, threshold=args.threshold, max_queries=60, seed=args.seed + 300 + i
        )
        baseline_vision_traces.append(tr_tf)
        vision_artifacts.append((tr_tf, adv_tf))

    for sample in txt_samples:
        baseline_text_traces.append(
            run_agentic_text_evasion(
                sample.sample_id, sample.text, txt_target, rewriter, threshold=args.threshold, max_turns=args.max_turns, beam_size=args.beam_size
            )
        )

    print("[Phase 2/3] Exporting worst evading examples to AI hard-negative pool...")
    hn_summary = export_hard_negatives(
        vision_artifacts=vision_artifacts,
        text_traces=baseline_text_traces,
        out_dir=Path(args.hard_neg_dir),
        max_per_modality=8,
    )

    print("[Phase 3/3] Re-testing identical attacks AFTER inference-time mitigations...")
    defended_img = HardenedVisionDefense(img_target, num_views=5, confidence_quantum=0.05, query_burst_limit=45, seed=args.seed)
    defended_vid = HardenedVisionDefense(vid_target, num_views=5, confidence_quantum=0.05, query_burst_limit=45, seed=args.seed + 1)
    defended_txt = HardenedTextDefense(txt_target, confidence_quantum=0.05)

    mitigated_vision_traces: List[VisionEvasionTrace] = []
    mitigated_text_traces: List[TextEvasionTrace] = []

    for i, sample in enumerate(img_samples):
        tr_sq, _ = run_square_attack(
            sample.sample_id, sample.payload, defended_img, threshold=args.threshold, eps=args.eps, max_queries=args.max_queries, seed=args.seed + i
        )
        mitigated_vision_traces.append(tr_sq)
        tr_tf, _ = run_adaptive_transform_attack(
            sample.sample_id, sample.payload, defended_img, threshold=args.threshold, max_queries=60, seed=args.seed + 100 + i
        )
        mitigated_vision_traces.append(tr_tf)

    for i, sample in enumerate(vid_samples):
        tr_sq, _ = run_square_attack(
            sample.sample_id, sample.payload, defended_vid, threshold=args.threshold, eps=args.eps, max_queries=args.max_queries, seed=args.seed + 200 + i
        )
        mitigated_vision_traces.append(tr_sq)
        tr_tf, _ = run_adaptive_transform_attack(
            sample.sample_id, sample.payload, defended_vid, threshold=args.threshold, max_queries=60, seed=args.seed + 300 + i
        )
        mitigated_vision_traces.append(tr_tf)

    for sample in txt_samples:
        mitigated_text_traces.append(
            run_agentic_text_evasion(
                sample.sample_id, sample.text, defended_txt, rewriter, threshold=args.threshold, max_turns=args.max_turns, beam_size=args.beam_size
            )
        )

    all_curves: List[Tuple[str, EvasionCurveRow]] = []
    for r in summarize_vision_curves(baseline_vision_traces, threshold=args.threshold):
        all_curves.append(("before_mitigation", r))
    for r in summarize_text_curves(baseline_text_traces, threshold=args.threshold, max_turns=args.max_turns):
        all_curves.append(("before_mitigation", r))
    for r in summarize_vision_curves(mitigated_vision_traces, threshold=args.threshold):
        all_curves.append(("after_mitigation", r))
    for r in summarize_text_curves(mitigated_text_traces, threshold=args.threshold, max_turns=args.max_turns):
        all_curves.append(("after_mitigation", r))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    csv_path = out_dir / "adaptive_robustness_v2_curves.csv"
    _write_curves_csv(all_curves, csv_path)

    json_path = out_dir / "adaptive_robustness_v2_results.json"
    json_path.write_text(
        json.dumps(
            {
                "generated_at_utc": generated_utc,
                "threshold": args.threshold,
                "eps": args.eps,
                "max_queries": args.max_queries,
                "max_turns": args.max_turns,
                "hard_negatives": hn_summary,
                "curves": [{"phase": ph, **asdict(r)} for ph, r in all_curves],
                "baseline_vision": [asdict(t) for t in baseline_vision_traces],
                "mitigated_vision": [asdict(t) for t in mitigated_vision_traces],
                "baseline_text": [
                    {**{k: v for k, v in asdict(t).items() if k != "history"}, "turns_logged": len(t.history)}
                    for t in baseline_text_traces
                ],
                "mitigated_text": [
                    {**{k: v for k, v in asdict(t).items() if k != "history"}, "turns_logged": len(t.history)}
                    for t in mitigated_text_traces
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    md_path = out_dir / "adaptive_robustness_v2_report.md"
    md_path.write_text(
        _format_markdown_report(
            generated_utc,
            args.threshold,
            args.eps,
            args.max_queries,
            args.max_turns,
            baseline_vision_traces,
            mitigated_vision_traces,
            baseline_text_traces,
            mitigated_text_traces,
            all_curves,
            hn_summary,
        ),
        encoding="utf-8",
    )
    print(f"[DONE] Curves CSV: {csv_path}")
    print(f"[DONE] Report MD : {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
