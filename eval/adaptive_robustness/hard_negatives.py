"""Exports worst adaptive evasion examples into AEGIS's AI hard-negative pool."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
from PIL import Image

from eval.adaptive_robustness.agentic_text_paraphraser import TextEvasionTrace
from eval.adaptive_robustness.blackbox_evasion import VisionEvasionTrace


def export_hard_negatives(
    vision_artifacts: Iterable[Tuple[VisionEvasionTrace, np.ndarray]],
    text_traces: Iterable[TextEvasionTrace],
    out_dir: Path,
    max_per_modality: int = 8,
) -> Dict[str, Any]:
    """Persists highest-impact evading/near-miss samples + JSONL/CSV manifests for AI retraining."""
    out_dir = Path(out_dir)
    img_dir = out_dir / "images"
    vid_dir = out_dir / "videos"
    txt_dir = out_dir / "texts"
    for d in (out_dir, img_dir, vid_dir, txt_dir):
        d.mkdir(parents=True, exist_ok=True)

    records: List[Dict[str, Any]] = []

    vision_by_mod: Dict[str, List[Tuple[VisionEvasionTrace, np.ndarray]]] = {}
    for trace, adv_arr in vision_artifacts:
        if trace.clean_confidence >= 0.5 and (trace.score_drop > 0.0 or trace.flipped):
            vision_by_mod.setdefault(trace.modality, []).append((trace, adv_arr))

    for modality, pairs in sorted(vision_by_mod.items()):
        ranked = sorted(
            pairs,
            key=lambda p: (
                0 if p[0].flipped else 1,
                -p[0].score_drop,
                p[0].queries_used,
            ),
        )[:max_per_modality]
        for idx, (trace, adv_arr) in enumerate(ranked, start=1):
            stem = f"{trace.sample_id}_{trace.attack_method}_{idx}"
            if modality == "image":
                artifact_path = img_dir / f"{stem}.png"
                Image.fromarray(np.asarray(adv_arr, dtype=np.uint8)).save(artifact_path, format="PNG")
            else:
                artifact_path = vid_dir / f"{stem}.npz"
                np.savez_compressed(artifact_path, frames=np.asarray(adv_arr, dtype=np.uint8))

            records.append(
                {
                    "sample_id": trace.sample_id,
                    "true_label": "fake",
                    "modality": modality,
                    "detector_name": trace.detector_name,
                    "attack_method": trace.attack_method,
                    "clean_confidence": trace.clean_confidence,
                    "evaded_confidence": trace.final_confidence,
                    "score_drop": trace.score_drop,
                    "flipped": trace.flipped,
                    "budget_used": trace.queries_used,
                    "budget_unit": "queries",
                    "linf_norm": trace.linf_norm,
                    "psnr_db": trace.psnr_db,
                    "semantic_similarity": "",
                    "artifact_path": artifact_path.relative_to(out_dir).as_posix(),
                    "text_excerpt": "",
                }
            )

    ranked_text = sorted(
        [t for t in text_traces if t.clean_confidence >= 0.5 and (t.score_drop > 0.0 or t.flipped)],
        key=lambda t: (0 if t.flipped else 1, -t.score_drop, -t.best_similarity),
    )[:max_per_modality]
    for idx, trace in enumerate(ranked_text, start=1):
        txt_path = txt_dir / f"{trace.sample_id}_adv_{idx}.txt"
        txt_path.write_text(trace.best_text, encoding="utf-8")
        records.append(
            {
                "sample_id": trace.sample_id,
                "true_label": "fake",
                "modality": "text",
                "detector_name": trace.detector_name,
                "attack_method": trace.rewriter_name,
                "clean_confidence": trace.clean_confidence,
                "evaded_confidence": trace.final_confidence,
                "score_drop": trace.score_drop,
                "flipped": trace.flipped,
                "budget_used": trace.turns_used,
                "budget_unit": "turns",
                "linf_norm": "",
                "psnr_db": "",
                "semantic_similarity": trace.best_similarity,
                "artifact_path": txt_path.relative_to(out_dir).as_posix(),
                "text_excerpt": trace.best_text[:240],
            }
        )

    jsonl_path = out_dir / "hard_negatives_manifest.jsonl"
    jsonl_path.write_text(
        "\n".join(json.dumps(r) for r in records) + ("\n" if records else ""),
        encoding="utf-8",
    )

    csv_path = out_dir / "hard_negatives_manifest.csv"
    fieldnames = [
        "sample_id",
        "true_label",
        "modality",
        "detector_name",
        "attack_method",
        "clean_confidence",
        "evaded_confidence",
        "score_drop",
        "flipped",
        "budget_used",
        "budget_unit",
        "linf_norm",
        "psnr_db",
        "semantic_similarity",
        "artifact_path",
        "text_excerpt",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    return {
        "total_exported": len(records),
        "jsonl_path": str(jsonl_path),
        "csv_path": str(csv_path),
        "by_modality": {
            mod: sum(1 for r in records if r["modality"] == mod)
            for mod in sorted({r["modality"] for r in records})
        },
    }
