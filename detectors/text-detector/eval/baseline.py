"""
Benchmark harness for AEGIS `detector_text`: compares as-is Desklib (512-token baseline)
against the full chunked + signal-enriched `/detect` pipeline.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score, roc_curve

DETECTOR_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = DETECTOR_DIR.parents[1]
if str(DETECTOR_DIR) not in sys.path:
    sys.path.insert(0, str(DETECTOR_DIR))

DEFAULT_MANIFEST = REPO_ROOT / "eval" / "data" / "text" / "text_eval_manifest.jsonl"
DEFAULT_REPORT = DETECTOR_DIR / "eval" / "text_detector_baseline.md"
DEFAULT_CSV = DETECTOR_DIR / "eval" / "text_detector_baseline_metrics.csv"


def load_manifest(path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
            if limit and len(records) >= limit:
                break
    return records


def _tpr_at_fpr(y_true: List[int], y_score: List[float], target_fpr: float = 0.01) -> tuple[float, float]:
    fpr, tpr, thresholds = roc_curve(y_true, y_score)
    idx = 0
    for i, f in enumerate(fpr):
        if f <= target_fpr:
            idx = i
        else:
            break
    return float(tpr[idx]), float(thresholds[idx])


def compute_binary_metrics(y_true: List[int], y_score: List[float], threshold: float = 0.5) -> Dict[str, Any]:
    if len(set(y_true)) < 2:
        preds = [1 if s >= threshold else 0 for s in y_score]
        acc = sum(int(p == y) for p, y in zip(preds, y_true)) / max(1, len(y_true))
        return {
            "n": len(y_true),
            "auroc": None,
            "tpr_at_1pct_fpr": None,
            "threshold_at_1pct_fpr": None,
            "accuracy": round(acc, 4),
            "precision": None,
            "recall": None,
            "f1": None,
        }

    auroc = roc_auc_score(y_true, y_score)
    tpr_1pct, thr_1pct = _tpr_at_fpr(y_true, y_score, 0.01)
    preds = [1 if s >= threshold else 0 for s in y_score]
    acc = sum(int(p == y) for p, y in zip(preds, y_true)) / len(y_true)
    prec, rec, f1, _ = precision_recall_fscore_support(
        y_true, preds, average="binary", zero_division=0
    )
    return {
        "n": len(y_true),
        "auroc": round(float(auroc), 4),
        "tpr_at_1pct_fpr": round(tpr_1pct, 4),
        "threshold_at_1pct_fpr": round(thr_1pct, 4),
        "accuracy": round(float(acc), 4),
        "precision": round(float(prec), 4),
        "recall": round(float(rec), 4),
        "f1": round(float(f1), 4),
    }


def _percentile(values: List[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    pos = (len(ordered) - 1) * (pct / 100.0)
    lo = int(math.floor(pos))
    hi = min(len(ordered) - 1, lo + 1)
    frac = pos - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def _run_as_is_baseline(records: List[Dict[str, Any]], fp16: bool = True) -> Dict[str, Any]:
    """Run raw `desklib/ai-text-detector-v1.01` with stock 512-token single-pass truncation."""
    from config import TextDetectorConfig
    from desklib_model import load_desklib

    cfg = TextDetectorConfig()
    source = str(cfg.model_dir) if (cfg.model_dir / "config.json").exists() else cfg.model_name
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    model, tokenizer, device = load_desklib(model_dir=source, device=device)
    if device.type == "cuda" and fp16:
        model = model.half()
    model.eval()

    latencies: List[float] = []
    rows_out: List[Dict[str, Any]] = []
    for rec in records:
        t0 = time.perf_counter()
        encoded = tokenizer(
            rec["text"],
            padding="max_length",
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        with torch.inference_mode():
            raw = model(
                input_ids=encoded["input_ids"].to(device),
                attention_mask=encoded["attention_mask"].to(device),
            )
            logits = raw["logits"] if isinstance(raw, dict) else (raw.logits if hasattr(raw, "logits") else raw)
            score = float(torch.sigmoid(logits).squeeze().detach().cpu().item())
        lat_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(lat_ms)
        rows_out.append({**rec, "score": score, "raw_score": score, "status": "ok", "latency_ms": lat_ms})

    peak_vram_mb = (
        round(torch.cuda.max_memory_allocated(device) / (1024**2), 2)
        if device.type == "cuda"
        else 0.0
    )
    del model
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return {
        "mode": "as_is_512tok",
        "device": str(device),
        "fp16": fp16 and device.type == "cuda",
        "peak_vram_mb": peak_vram_mb,
        "latencies_ms": latencies,
        "rows": rows_out,
    }


def _run_service_inprocess(
    records: List[Dict[str, Any]], write_calibration: bool = False
) -> Dict[str, Any]:
    """Run full `/detect` FastAPI pipeline (chunking + perplexity + stylometry + length gating)."""
    from fastapi.testclient import TestClient
    from app import create_app, create_default_runtime
    from config import TextDetectorConfig

    cfg = TextDetectorConfig()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    rt = create_default_runtime(cfg)
    rt.desklib.load()
    if rt.perplexity is not None:
        rt.perplexity.load()

    test_app = create_app(runtime=rt)
    headers = {"X-Internal-Token": cfg.internal_api_key} if cfg.internal_api_key else {}

    latencies: List[float] = []
    rows_out: List[Dict[str, Any]] = []
    human_ppls: List[float] = []
    human_covs: List[float] = []

    with TestClient(test_app) as client:
        for i, rec in enumerate(records):
            b64 = base64.b64encode(rec["text"].encode("utf-8")).decode("ascii")
            t0 = time.perf_counter()
            resp = client.post(
                "/detect",
                json={"job_id": f"eval-{i}", "modality": "text", "payload": b64},
                headers=headers,
            )
            lat_ms = (time.perf_counter() - t0) * 1000.0
            resp.raise_for_status()
            body = resp.json()
            latencies.append(lat_ms)

            ppl_info = body.get("signals", {}).get("perplexity", {})
            if rec["label"] == 0 and ppl_info.get("available"):
                if ppl_info.get("mean_perplexity") is not None:
                    human_ppls.append(float(ppl_info["mean_perplexity"]))
                if ppl_info.get("sentence_burstiness_cov") is not None:
                    human_covs.append(float(ppl_info["sentence_burstiness_cov"]))

            rows_out.append(
                {
                    **rec,
                    "score": float(body["confidence"]),
                    "raw_score": float(body["raw_score"]),
                    "status": body.get("status", "ok"),
                    "latency_ms": lat_ms,
                }
            )

    if write_calibration and human_ppls and human_covs:
        cal = {
            "source": str(DEFAULT_MANIFEST.name),
            "human_samples": len(human_ppls),
            "low_perplexity_threshold": round(_percentile(human_ppls, 10.0), 2),
            "high_perplexity_threshold": round(_percentile(human_ppls, 90.0), 2),
            "low_burstiness_cov_threshold": round(_percentile(human_covs, 10.0), 3),
            "binoculars_threshold": 0.90,
        }
        cfg.calibration_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.calibration_path.write_text(json.dumps(cal, indent=2) + "\n", encoding="utf-8")

    peak_vram_mb = (
        round(torch.cuda.max_memory_allocated() / (1024**2), 2)
        if torch.cuda.is_available()
        else 0.0
    )
    return {
        "mode": "service_detect",
        "device": str(rt.desklib.device),
        "fp16": cfg.use_fp16 and str(rt.desklib.device).startswith("cuda"),
        "peak_vram_mb": peak_vram_mb,
        "latencies_ms": latencies,
        "rows": rows_out,
        "human_ppl_count": len(human_ppls),
    }


def _summarize_run(run_data: Dict[str, Any]) -> Dict[str, Any]:
    rows = run_data["rows"]
    y_true = [int(r["label"]) for r in rows]
    # AUROC/TPR@1%FPR evaluated on raw_score when present so gating abstentions still preserve ranking
    y_raw = [float(r["raw_score"]) for r in rows]
    overall = compute_binary_metrics(y_true, y_raw, threshold=0.5)

    scored_rows = [r for r in rows if r["status"] == "ok"]
    abstained = len(rows) - len(scored_rows)
    conditional_acc = (
        sum(int((r["score"] >= 0.5) == bool(r["label"])) for r in scored_rows) / max(1, len(scored_rows))
    )

    by_bucket: Dict[str, Dict[str, Any]] = {}
    bucket_groups = defaultdict(list)
    for r in rows:
        bucket_groups[r.get("length_bucket", "unknown")].append(r)
    for bname, grp in sorted(bucket_groups.items()):
        by_bucket[bname] = compute_binary_metrics(
            [int(r["label"]) for r in grp], [float(r["score"]) for r in grp]
        )

    by_gen: Dict[str, Dict[str, Any]] = {}
    gen_groups = defaultdict(list)
    for r in rows:
        key = f"{r.get('generator', 'unknown')}{'_para' if r.get('paraphrased') else ''}"
        gen_groups[key].append(r)
    for gname, grp in sorted(gen_groups.items()):
        by_gen[gname] = {
            "n": len(grp),
            "true_class": "human" if grp[0]["label"] == 0 else "ai",
            "pred_ai_rate": round(sum(1 for r in grp if r["score"] >= 0.5) / len(grp), 4),
            "mean_score": round(statistics.mean(r["score"] for r in grp), 4),
        }

    lats = run_data["latencies_ms"]
    return {
        "mode": run_data["mode"],
        "device": run_data["device"],
        "fp16": run_data["fp16"],
        "peak_vram_mb": run_data["peak_vram_mb"],
        "avg_latency_ms": round(statistics.mean(lats), 2) if lats else 0.0,
        "p50_latency_ms": round(_percentile(lats, 50.0), 2),
        "p95_latency_ms": round(_percentile(lats, 95.0), 2),
        "abstained_not_applicable": abstained,
        "conditional_accuracy_at_0_5": round(conditional_acc, 4),
        "overall_raw": overall,
        "by_length_bucket": by_bucket,
        "by_generator": by_gen,
    }


def write_markdown_and_csv(
    summaries: List[Dict[str, Any]],
    manifest_path: Path,
    report_path: Path,
    csv_path: Path,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# AEGIS Text Detector (`desklib/ai-text-detector-v1.01`) Baseline Note",
        "",
        f"- **Generated:** {now}",
        f"- **Dataset:** `{manifest_path}` (**Interim public dataset from `yaful/MAGE`** pending AI Task 4 final text benchmark)",
        "- **Model Status:** As-is `desklib/ai-text-detector-v1.01` (`microsoft/deberta-v3-large`), zero fine-tuning applied (Task 3 owns LoRA adaptation).",
        "",
        "## 1. Headline Performance & GPU Budget",
        "",
        "| Mode | Device / Dtype | N | AUROC (raw) | TPR @ 1% FPR | Cond. Acc@0.5 | Not Applicable | Avg ms | P95 ms | Peak VRAM (MB) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summaries:
        ov = s["overall_raw"]
        dtype = "CUDA fp16" if s["fp16"] else f"{s['device']} fp32"
        lines.append(
            f"| `{s['mode']}` | {dtype} | {ov['n']} | {ov['auroc']} | {ov['tpr_at_1pct_fpr']} | "
            f"{s['conditional_accuracy_at_0_5']} | {s['abstained_not_applicable']} | "
            f"{s['avg_latency_ms']} | {s['p95_latency_ms']} | {s['peak_vram_mb']} |"
        )

    for s in summaries:
        lines.extend([
            "",
            f"## Breakdown — `{s['mode']}`",
            "",
            "### By Length Bucket",
            "",
            "| Length Bucket | N | AUROC | TPR @ 1% FPR | Accuracy@0.5 | F1@0.5 |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for bname, bm in s["by_length_bucket"].items():
            lines.append(
                f"| `{bname}` | {bm['n']} | {bm['auroc']} | {bm['tpr_at_1pct_fpr']} | {bm['accuracy']} | {bm['f1']} |"
            )
        lines.extend([
            "",
            "### By Generator / Subset",
            "",
            "| Generator | Class | N | Pred AI Rate (@0.5) | Mean Score |",
            "|---|---|---:|---:|---:|",
        ])
        for gname, gm in s["by_generator"].items():
            lines.append(
                f"| `{gname}` | {gm['true_class']} | {gm['n']} | {gm['pred_ai_rate']} | {gm['mean_score']} |"
            )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "mode",
                "device",
                "fp16",
                "n",
                "auroc",
                "tpr_at_1pct_fpr",
                "cond_accuracy_0_5",
                "abstained",
                "avg_latency_ms",
                "p95_latency_ms",
                "peak_vram_mb",
            ]
        )
        for s in summaries:
            ov = s["overall_raw"]
            writer.writerow(
                [
                    s["mode"],
                    s["device"],
                    s["fp16"],
                    ov["n"],
                    ov["auroc"],
                    ov["tpr_at_1pct_fpr"],
                    s["conditional_accuracy_at_0_5"],
                    s["abstained_not_applicable"],
                    s["avg_latency_ms"],
                    s["p95_latency_ms"],
                    s["peak_vram_mb"],
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AEGIS detector_text baseline benchmark.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--mode", choices=["as_is", "service", "both"], default="both")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--write-calibration", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    records = load_manifest(args.manifest, limit=args.limit)
    summaries: List[Dict[str, Any]] = []
    if args.mode in ("as_is", "both"):
        raw = _run_as_is_baseline(records, fp16=True)
        summaries.append(_summarize_run(raw))
    if args.mode in ("service", "both"):
        svc = _run_service_inprocess(records, write_calibration=args.write_calibration)
        summaries.append(_summarize_run(svc))

    write_markdown_and_csv(summaries, args.manifest, args.report, args.csv)
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()

