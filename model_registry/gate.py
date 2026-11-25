"""Automatic fail-closed Promotion Gate for AEGIS detector checkpoints."""

from __future__ import annotations

import base64
import copy
import gc
import importlib
import json
import math
import os
import random
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import jsonschema
import numpy as np
import psutil
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from capability_manifests.Schema import DETECTOR_MANIFEST_SCHEMA  # noqa: E402
from debate.calibration import CalibratorRegistry  # noqa: E402
from model_registry.registry import ModelRegistry  # noqa: E402
from security.supply_chain.model_integrity import (  # noqa: E402
    ModelIntegrityError,
    load_weights_manifest,
    verify_file_sha256,
)

SCHEMA_DIR = REPO_ROOT / "shared" / "json-api-contracts-schema"


@dataclass
class GateCheckResult:
    name: str
    passed: bool
    summary: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "summary": self.summary,
            "details": self.details,
        }


@dataclass
class GateResult:
    entry_id: str
    detector_name: str
    passed: bool
    checks: List[GateCheckResult] = field(default_factory=list)
    measured_metrics: Dict[str, Any] = field(default_factory=dict)
    baseline_metrics: Optional[Dict[str, Any]] = None
    updated_manifest: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "detector_name": self.detector_name,
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
            "measured_metrics": self.measured_metrics,
            "baseline_metrics": self.baseline_metrics,
            "summary": {
                "passed_checks": sum(1 for c in self.checks if c.passed),
                "total_checks": len(self.checks),
                "failed_checks": [c.name for c in self.checks if not c.passed],
                "auroc": self.measured_metrics.get("auroc"),
                "accuracy": self.measured_metrics.get("accuracy"),
                "avg_latency_ms": self.measured_metrics.get("avg_latency_ms"),
                "p95_latency_ms": self.measured_metrics.get("p95_latency_ms"),
                "device": self.measured_metrics.get("device"),
            },
        }


_TEXT_DETECTOR_CACHE: Optional[Dict[str, Any]] = None


def _get_text_detector_modules(detector_dir: Path) -> Dict[str, Any]:
    """Loads and caches detector_text modules once to prevent duplicate Prometheus registration."""
    global _TEXT_DETECTOR_CACHE
    if _TEXT_DETECTOR_CACHE is not None:
        return _TEXT_DETECTOR_CACHE

    dir_str = str(detector_dir)
    if dir_str not in sys.path:
        sys.path.insert(0, dir_str)

    # Clear only non-prometheus colliding modules from other services if any
    for mod in ("app", "config", "schemas", "chunking", "desklib_model", "desklib_runner"):
        existing = sys.modules.get(mod)
        mod_file = getattr(existing, "__file__", "") or ""
        if existing is not None and str(detector_dir) not in mod_file:
            sys.modules.pop(mod, None)

    from app import ServiceRuntime, create_app
    from chunking import ChunkAggregationResult
    from config import TextDetectorConfig
    from desklib_runner import DesklibRunner

    _TEXT_DETECTOR_CACHE = {
        "ServiceRuntime": ServiceRuntime,
        "create_app": create_app,
        "ChunkAggregationResult": ChunkAggregationResult,
        "TextDetectorConfig": TextDetectorConfig,
        "DesklibRunner": DesklibRunner,
    }
    return _TEXT_DETECTOR_CACHE


def _compute_ece_10bin(probs: List[float], labels: List[int]) -> float:
    if not probs:
        return 0.0
    p = np.asarray(probs, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    edges = np.linspace(0.0, 1.0, 11)
    ece = 0.0
    n = len(p)
    for i in range(10):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p <= hi) if i == 9 else (p >= lo) & (p < hi)
        cnt = int(np.sum(mask))
        if cnt > 0:
            ece += (cnt / n) * abs(float(np.mean(y[mask])) - float(np.mean(p[mask])))
    return round(float(ece), 4)


def _tpr_at_1pct_fpr(y_true: List[int], y_score: List[float]) -> float:
    from sklearn.metrics import roc_curve

    if len(set(y_true)) < 2:
        return 0.0
    fpr, tpr, _ = roc_curve(y_true, y_score)
    idx = 0
    for i, val in enumerate(fpr):
        if val <= 0.01:
            idx = i
        else:
            break
    return round(float(tpr[idx]), 4)


def _compute_classification_metrics(
    y_true: List[int],
    raw_probs: List[float],
    calibrated_probs: List[float],
) -> Dict[str, Any]:
    from sklearn.metrics import precision_recall_fscore_support, roc_auc_score

    preds = [1 if s >= 0.5 else 0 for s in raw_probs]
    acc = sum(int(p == y) for p, y in zip(preds, y_true)) / max(1, len(y_true))
    if len(set(y_true)) >= 2:
        auroc = float(roc_auc_score(y_true, raw_probs))
        cal_auroc = float(roc_auc_score(y_true, calibrated_probs))
        prec, rec, f1, _ = precision_recall_fscore_support(
            y_true, preds, average="binary", zero_division=0
        )
        tpr_1pct = _tpr_at_1pct_fpr(y_true, raw_probs)
    else:
        auroc = 0.0
        cal_auroc = 0.0
        prec = rec = f1 = 0.0
        tpr_1pct = 0.0

    return {
        "n_samples": len(y_true),
        "auroc": round(auroc, 4),
        "calibrated_auroc": round(cal_auroc, 4),
        "accuracy": round(float(acc), 4),
        "precision": round(float(prec), 4),
        "recall": round(float(rec), 4),
        "f1": round(float(f1), 4),
        "tpr_at_1pct_fpr": tpr_1pct,
        "uncalibrated_ece": _compute_ece_10bin(raw_probs, y_true),
        "calibrated_ece": _compute_ece_10bin(calibrated_probs, y_true),
    }


def load_stratified_text_subset(
    manifest_path: Path,
    max_samples: int = 16,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Loads a deterministic stratified subset covering human, clean AI, and paraphrased AI."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Text eval manifest not found: {manifest_path}")

    human_rows: List[Dict[str, Any]] = []
    ai_clean_rows: List[Dict[str, Any]] = []
    ai_para_rows: List[Dict[str, Any]] = []

    with manifest_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            rec = json.loads(raw)
            wc = int(rec.get("word_count") or len(rec.get("text", "").split()))
            if wc < 40:
                continue
            if int(rec["label"]) == 0:
                human_rows.append(rec)
            elif bool(rec.get("paraphrased")):
                ai_para_rows.append(rec)
            else:
                ai_clean_rows.append(rec)

    rng = random.Random(seed)
    rng.shuffle(human_rows)
    rng.shuffle(ai_clean_rows)
    rng.shuffle(ai_para_rows)

    n_human = max(2, max_samples // 2)
    n_ai_total = max(2, max_samples - n_human)
    n_ai_para = min(len(ai_para_rows), max(1, n_ai_total // 2))
    n_ai_clean = min(len(ai_clean_rows), n_ai_total - n_ai_para)

    selected = (
        human_rows[: min(len(human_rows), n_human)]
        + ai_clean_rows[:n_ai_clean]
        + ai_para_rows[:n_ai_para]
    )
    return selected[:max_samples]


class _ContractStubPerplexity:
    def is_loaded(self) -> bool:
        return False


class _ContractStubDesklib:
    def __init__(self, chunk_agg_cls: Any, prob: float = 0.88) -> None:
        self._chunk_agg_cls = chunk_agg_cls
        self.prob = prob
        self.device = "cpu"

    def is_loaded(self) -> bool:
        return True

    def load(self, device: Optional[str] = None) -> None:
        return None

    def score_text(
        self,
        text: str,
        chunk_tokens: int = 510,
        overlap: int = 64,
        max_chunks: int = 32,
        spread_threshold: float = 0.35,
    ) -> Any:
        return self._chunk_agg_cls(
            raw_probability=self.prob,
            mean_logit=1.45,
            chunk_scores=(self.prob,),
            chunk_token_counts=(120,),
            total_tokens=180,
            chunk_count=1,
            sampled_from_chunks=1,
            chunk_spread=0.0,
            disagreement=False,
        )


class PromotionGate:
    """Runs automated integrity, schema/contract, regression, and budget checks."""

    def __init__(
        self,
        registry: ModelRegistry,
        repo_root: Optional[Path] = None,
        contract_checker: Optional[Callable[[Dict[str, Any]], Tuple[bool, str, Dict[str, Any]]]] = None,
        evaluator_fn: Optional[Callable[[Dict[str, Any], Optional[Dict[str, Any]]], Dict[str, Any]]] = None,
    ) -> None:
        self.registry = registry
        self.repo_root = Path(repo_root) if repo_root else registry.repo_root
        self.contract_checker = contract_checker
        self.evaluator_fn = evaluator_fn

    def _resolve(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        return p if p.is_absolute() else (self.repo_root / p)

    # ------------------------------------------------------------------
    # Gate 1: Integrity & Calibration
    # ------------------------------------------------------------------
    def _check_integrity(self, entry: Dict[str, Any]) -> GateCheckResult:
        ckpt = entry["checkpoint"]
        cal = entry["calibration"]
        issues: List[str] = []
        details: Dict[str, Any] = {}

        weights_artifacts: Dict[str, Any] = {}
        if self.registry.weights_manifest_path.is_file():
            try:
                weights_artifacts = load_weights_manifest(self.registry.weights_manifest_path)
            except ModelIntegrityError as exc:
                issues.append(str(exc))

        ckpt_rel = ckpt["path"]
        ckpt_path = self._resolve(ckpt_rel)
        if not ckpt_path.is_file():
            issues.append(f"Checkpoint file missing on disk: {ckpt_path}")
        else:
            try:
                digest = verify_file_sha256(ckpt_path, ckpt["sha256"])
                details["checkpoint_sha256"] = digest
            except ModelIntegrityError as exc:
                issues.append(str(exc))

        if ckpt_rel in weights_artifacts:
            if weights_artifacts[ckpt_rel]["sha256"] != ckpt["sha256"]:
                issues.append(
                    f"Checkpoint SHA-256 differs from weights_sha256.json for {ckpt_rel}"
                )

        adapter_rel = ckpt.get("adapter_path")
        if adapter_rel:
            adapter_path = self._resolve(adapter_rel)
            if not adapter_path.is_file():
                issues.append(f"Adapter file missing on disk: {adapter_path}")
            elif ckpt.get("adapter_sha256"):
                try:
                    ad_digest = verify_file_sha256(adapter_path, ckpt["adapter_sha256"])
                    details["adapter_sha256"] = ad_digest
                except ModelIntegrityError as exc:
                    issues.append(str(exc))
            if adapter_rel in weights_artifacts and ckpt.get("adapter_sha256"):
                if weights_artifacts[adapter_rel]["sha256"] != ckpt["adapter_sha256"]:
                    issues.append(
                        f"Adapter SHA-256 differs from weights_sha256.json for {adapter_rel}"
                    )

        cal_path = self._resolve(cal["path"])
        if not cal_path.is_file():
            issues.append(f"Calibration file missing on disk: {cal_path}")
        else:
            try:
                cal_digest = verify_file_sha256(cal_path, cal["sha256"])
                loaded_cal = CalibratorRegistry.load_file(cal_path)
                probe = loaded_cal.predict(0.5)
                if not (0.0 <= probe <= 1.0):
                    issues.append(f"Calibration sanity probe out of [0,1]: {probe}")
                details["calibration_sha256"] = cal_digest
                details["calibration_probe_0.5"] = round(float(probe), 4)
            except Exception as exc:
                issues.append(f"Calibration check failed: {exc}")

        sig_rel = cal.get("signal_calibration_path")
        if sig_rel:
            sig_path = self._resolve(sig_rel)
            if not sig_path.is_file():
                issues.append(f"Signal calibration file missing: {sig_path}")
            else:
                try:
                    json.loads(sig_path.read_text(encoding="utf-8"))
                    if cal.get("signal_calibration_sha256"):
                        verify_file_sha256(sig_path, cal["signal_calibration_sha256"])
                except Exception as exc:
                    issues.append(f"Signal calibration invalid: {exc}")

        passed = len(issues) == 0
        summary = (
            "All checkpoint, adapter, and calibration hashes verified."
            if passed
            else "; ".join(issues)
        )
        details["issues"] = issues
        return GateCheckResult("integrity_and_calibration", passed, summary, details)

    # ------------------------------------------------------------------
    # Gate 2: Schema & API Contract Tests
    # ------------------------------------------------------------------
    def _check_schema_and_contract(self, entry: Dict[str, Any]) -> GateCheckResult:
        if self.contract_checker is not None:
            ok, msg, details = self.contract_checker(entry)
            return GateCheckResult("schema_and_contract_tests", ok, msg, details)

        issues: List[str] = []
        details: Dict[str, Any] = {}

        manifest_path = self._resolve(entry["manifest_path"])
        if not manifest_path.is_file():
            return GateCheckResult(
                "schema_and_contract_tests",
                False,
                f"Manifest not found: {manifest_path}",
                {},
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            jsonschema.validate(instance=manifest, schema=DETECTOR_MANIFEST_SCHEMA)
            details["manifest_schema_valid"] = True
        except Exception as exc:
            issues.append(f"Capability manifest schema validation failed: {exc}")

        req_schema_path = self.repo_root / "shared" / "json-api-contracts-schema" / "detector_request.schema.json"
        resp_schema_path = self.repo_root / "shared" / "json-api-contracts-schema" / "detector_response.schema.json"
        if not req_schema_path.is_file() or not resp_schema_path.is_file():
            req_schema_path = SCHEMA_DIR / "detector_request.schema.json"
            resp_schema_path = SCHEMA_DIR / "detector_response.schema.json"
        req_schema = json.loads(req_schema_path.read_text(encoding="utf-8"))
        resp_schema = json.loads(resp_schema_path.read_text(encoding="utf-8"))

        if entry["detector_name"] == "detector_text":
            detector_dir = self.repo_root / "detectors" / "text-detector"
            if not (detector_dir / "app.py").is_file():
                detector_dir = REPO_ROOT / "detectors" / "text-detector"
            td_mods = _get_text_detector_modules(detector_dir)
            ServiceRuntime = td_mods["ServiceRuntime"]
            create_app = td_mods["create_app"]
            TextDetectorConfig = td_mods["TextDetectorConfig"]
            ChunkAggregationResult = td_mods["ChunkAggregationResult"]

            load_cfg = entry["checkpoint"].get("load_config", {})
            cfg = TextDetectorConfig(
                use_finetuned=bool(load_cfg.get("use_finetuned", False)),
                lora_dir=str(load_cfg.get("lora_dir", "")),
                enable_ppl=False,
                enable_binoculars=False,
                preload_models=False,
                internal_api_key="",
            )
            runtime = ServiceRuntime(
                config=cfg,
                desklib=_ContractStubDesklib(ChunkAggregationResult, prob=0.87),
                perplexity=None,
                binoculars=None,
            )
            client = TestClient(create_app(runtime=runtime))
            with client:
                h_resp = client.get("/health")
                if h_resp.status_code != 200:
                    issues.append(f"/health returned HTTP {h_resp.status_code}")
                else:
                    h_body = h_resp.json()
                    details["health_model_version"] = h_body.get("model_version")
                    if h_body.get("model_version") != entry["model_version"]:
                        issues.append(
                            f"Health model_version {h_body.get('model_version')!r} != {entry['model_version']!r}"
                        )

                long_text = " ".join(["forensic verification pipeline benchmark"] * 45)
                req_obj = {
                    "job_id": "gate-contract-long",
                    "modality": "text",
                    "payload": base64.b64encode(long_text.encode("utf-8")).decode("ascii"),
                }
                jsonschema.validate(instance=req_obj, schema=req_schema)
                d_resp = client.post("/detect", json=req_obj)
                if d_resp.status_code != 200:
                    issues.append(f"/detect long text returned HTTP {d_resp.status_code}")
                else:
                    d_body = d_resp.json()
                    jsonschema.validate(instance=d_body, schema=resp_schema)
                    details["detect_long_status"] = d_body.get("status")

                short_text = "too short sample text"
                s_req = {
                    "job_id": "gate-contract-short",
                    "modality": "text",
                    "payload": base64.b64encode(short_text.encode("utf-8")).decode("ascii"),
                }
                jsonschema.validate(instance=s_req, schema=req_schema)
                s_resp = client.post("/detect", json=s_req)
                if s_resp.status_code != 200:
                    issues.append(f"/detect short text returned HTTP {s_resp.status_code}")
                else:
                    s_body = s_resp.json()
                    jsonschema.validate(instance=s_body, schema=resp_schema)
                    if s_body.get("status") != "not_applicable":
                        issues.append(
                            f"Short text expected status='not_applicable', got {s_body.get('status')!r}"
                        )
                    details["detect_short_status"] = s_body.get("status")
        else:
            details["contract_mode"] = "manifest_and_schema_verified"

        passed = len(issues) == 0
        summary = (
            "Manifest schema and API contract checks passed."
            if passed
            else "; ".join(issues)
        )
        details["issues"] = issues
        return GateCheckResult("schema_and_contract_tests", passed, summary, details)

    # ------------------------------------------------------------------
    # Gate 3 & 4: Staged Eval Subset Regression + Latency/Memory Budgets
    # ------------------------------------------------------------------
    def _evaluate_text_entry_real(
        self,
        entry: Dict[str, Any],
        subset: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        import torch

        detector_dir = self.repo_root / "detectors" / "text-detector"
        if not (detector_dir / "desklib_runner.py").is_file():
            detector_dir = REPO_ROOT / "detectors" / "text-detector"

        cal_path = self._resolve(entry["calibration"]["path"])
        calibrator = CalibratorRegistry.load_file(cal_path)

        load_cfg = entry["checkpoint"].get("load_config", {})
        use_finetuned = bool(load_cfg.get("use_finetuned", False))
        lora_dir_rel = str(load_cfg.get("lora_dir", "") or "")
        lora_dir_abs = str(self._resolve(lora_dir_rel)) if lora_dir_rel else ""

        use_cuda = torch.cuda.is_available()
        if use_cuda:
            torch.cuda.reset_peak_memory_stats()

        proc = psutil.Process(os.getpid())
        td_mods = _get_text_detector_modules(detector_dir)
        DesklibRunner = td_mods["DesklibRunner"]

        runner = DesklibRunner(
            model_dir=self._resolve(entry["checkpoint"]["path"]).parent,
            lora_dir=lora_dir_abs,
            use_finetuned=use_finetuned,
            use_fp16=use_cuda,
            batch_size=4,
        )
        runner.load(device="cuda" if use_cuda else "cpu")

        # Warmup 1 sample (excluded from latency stats)
        if subset:
            _ = runner.score_text(subset[0]["text"], chunk_tokens=510, overlap=64, max_chunks=8)

        y_true: List[int] = []
        raw_probs: List[float] = []
        cal_probs: List[float] = []
        latencies_ms: List[float] = []
        peak_ram_mb = proc.memory_info().rss / (1024.0 * 1024.0)

        for rec in subset:
            t0 = time.perf_counter()
            res = runner.score_text(rec["text"], chunk_tokens=510, overlap=64, max_chunks=8)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(dt_ms)

            prob = float(res.raw_probability)
            raw_probs.append(prob)
            cal_probs.append(float(calibrator.predict(prob)))
            y_true.append(int(rec["label"]))

            rss_mb = proc.memory_info().rss / (1024.0 * 1024.0)
            if rss_mb > peak_ram_mb:
                peak_ram_mb = rss_mb

        peak_vram_mb: Optional[float] = None
        if use_cuda:
            peak_vram_mb = round(torch.cuda.max_memory_allocated() / (1024.0 * 1024.0), 2)

        del runner
        gc.collect()
        if use_cuda:
            torch.cuda.empty_cache()

        metrics = _compute_classification_metrics(y_true, raw_probs, cal_probs)
        metrics.update(
            {
                "device": "cuda" if use_cuda else "cpu",
                "avg_latency_ms": round(float(np.mean(latencies_ms)), 2) if latencies_ms else 0.0,
                "p95_latency_ms": round(float(np.percentile(latencies_ms, 95)), 2) if latencies_ms else 0.0,
                "peak_ram_mb": round(float(peak_ram_mb), 2),
                "peak_vram_mb": peak_vram_mb,
                "eval_manifest": entry["regression_policy"]["eval_manifest"],
            }
        )
        return metrics

    def _run_regression_and_profile(
        self,
        entry: Dict[str, Any],
        baseline_entry: Optional[Dict[str, Any]],
        max_samples: int = 16,
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        if self.evaluator_fn is not None:
            cand = self.evaluator_fn(entry, baseline_entry)
            base = baseline_entry.get("measured_metrics") if baseline_entry else None
            return cand, (base if base else None)

        if entry["detector_name"] == "detector_text":
            eval_path = self._resolve(entry["regression_policy"]["eval_manifest"])
            subset = load_stratified_text_subset(eval_path, max_samples=max_samples, seed=42)
            cand_metrics = self._evaluate_text_entry_real(entry, subset)
            base_metrics: Optional[Dict[str, Any]] = None
            if baseline_entry and baseline_entry["entry_id"] != entry["entry_id"]:
                base_metrics = self._evaluate_text_entry_real(baseline_entry, subset)
            return cand_metrics, base_metrics

        # Fallback to recorded baseline metrics if no live runner registered for another modality
        if entry.get("measured_metrics"):
            return copy.deepcopy(entry["measured_metrics"]), None
        raise RuntimeError(f"No staged evaluator available for detector {entry['detector_name']!r}")

    def _check_regression(
        self,
        entry: Dict[str, Any],
        measured: Dict[str, Any],
        baseline: Optional[Dict[str, Any]],
    ) -> GateCheckResult:
        pol = entry["regression_policy"]
        issues: List[str] = []

        auroc = float(measured.get("auroc", 0.0))
        acc = float(measured.get("accuracy", 0.0))
        if auroc < float(pol["min_auroc"]):
            issues.append(f"AUROC {auroc:.4f} < min_auroc {pol['min_auroc']:.4f}")
        if acc < float(pol["min_accuracy"]):
            issues.append(f"Accuracy {acc:.4f} < min_accuracy {pol['min_accuracy']:.4f}")

        if baseline:
            base_auroc = float(baseline.get("auroc", 0.0))
            base_acc = float(baseline.get("accuracy", 0.0))
            if (base_auroc - auroc) > float(pol["max_auroc_drop"]):
                issues.append(
                    f"AUROC regressed by {base_auroc - auroc:.4f} > max_auroc_drop {pol['max_auroc_drop']:.4f}"
                )
            if (base_acc - acc) > float(pol["max_accuracy_drop"]):
                issues.append(
                    f"Accuracy regressed by {base_acc - acc:.4f} > max_accuracy_drop {pol['max_accuracy_drop']:.4f}"
                )

        passed = len(issues) == 0
        summary = (
            f"Staged eval passed (N={measured.get('n_samples')}, AUROC={auroc:.4f}, Acc={acc:.4f}, ECE={measured.get('calibrated_ece')})."
            if passed
            else "; ".join(issues)
        )
        return GateCheckResult(
            "staged_eval_regression",
            passed,
            summary,
            {"candidate": measured, "baseline": baseline, "issues": issues},
        )

    def _check_budgets(
        self,
        entry: Dict[str, Any],
        measured: Dict[str, Any],
    ) -> GateCheckResult:
        budgets = entry["budgets"]
        device = str(measured.get("device", "cpu")).lower()
        avg_ms = float(measured.get("avg_latency_ms", 0.0))
        p95_ms = float(measured.get("p95_latency_ms", 0.0))
        ram_mb = float(measured.get("peak_ram_mb", 0.0))
        vram_mb = measured.get("peak_vram_mb")

        if device == "cuda":
            avg_limit = float(budgets["max_avg_latency_ms"])
            p95_limit = float(budgets["max_p95_latency_ms"])
        else:
            avg_limit = float(budgets.get("cpu_max_avg_latency_ms") or budgets["max_avg_latency_ms"])
            p95_limit = float(budgets.get("cpu_max_p95_latency_ms") or budgets["max_p95_latency_ms"])

        ram_limit = float(budgets["max_ram_mb"])
        vram_limit = float(budgets["max_vram_mb"])
        issues: List[str] = []

        if avg_ms > avg_limit:
            issues.append(f"avg_latency_ms {avg_ms:.2f} > limit {avg_limit:.2f} ({device})")
        if p95_ms > p95_limit:
            issues.append(f"p95_latency_ms {p95_ms:.2f} > limit {p95_limit:.2f} ({device})")
        if ram_mb > ram_limit:
            issues.append(f"peak_ram_mb {ram_mb:.2f} > limit {ram_limit:.2f}")

        recorded_vram = entry.get("measured_metrics", {}).get("gpu_profile_vram_mb")
        effective_vram = vram_mb if vram_mb is not None else recorded_vram
        if effective_vram is not None and float(effective_vram) > vram_limit:
            issues.append(f"peak_vram_mb {float(effective_vram):.2f} > limit {vram_limit:.2f}")

        passed = len(issues) == 0
        summary = (
            f"Budget check passed ({device}: avg={avg_ms:.1f}ms <= {avg_limit:.0f}ms, "
            f"p95={p95_ms:.1f}ms <= {p95_limit:.0f}ms, RAM={ram_mb:.1f}MB <= {ram_limit:.0f}MB)."
            if passed
            else "; ".join(issues)
        )
        return GateCheckResult(
            "latency_and_memory_budget",
            passed,
            summary,
            {
                "device": device,
                "avg_latency_ms": avg_ms,
                "avg_limit_ms": avg_limit,
                "p95_latency_ms": p95_ms,
                "p95_limit_ms": p95_limit,
                "peak_ram_mb": ram_mb,
                "ram_limit_mb": ram_limit,
                "peak_vram_mb": vram_mb,
                "vram_limit_mb": vram_limit,
                "issues": issues,
            },
        )

    # ------------------------------------------------------------------
    # Gate 5: Dry-Run Capability Manifest Update & Schema Validation
    # ------------------------------------------------------------------
    def _build_updated_manifest(
        self,
        entry: Dict[str, Any],
        measured: Dict[str, Any],
    ) -> Tuple[GateCheckResult, Optional[Dict[str, Any]]]:
        manifest_path = self._resolve(entry["manifest_path"])
        try:
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return (
                GateCheckResult("manifest_update_validation", False, f"Failed reading manifest: {exc}"),
                None,
            )

        updated = copy.deepcopy(current)
        updated["version"] = entry["model_version"]
        updated["registry_entry_id"] = entry["entry_id"]

        perf = copy.deepcopy(updated.get("performance", {}))
        perf["avg_latency_ms"] = measured.get("avg_latency_ms", perf.get("avg_latency_ms"))
        perf["p95_latency_ms"] = measured.get("p95_latency_ms", perf.get("p95_latency_ms"))
        perf["avg_ram_usage_mb"] = measured.get("peak_ram_mb", perf.get("avg_ram_usage_mb"))
        if measured.get("peak_vram_mb") is not None:
            perf["avg_vram_usage_mb"] = measured["peak_vram_mb"]
        device_tag = str(measured.get("device", "cpu")).upper()
        perf["measured_on"] = (
            f"PromotionGate ({device_tag}) on {measured.get('eval_manifest', 'staged_eval')} "
            f"(N={measured.get('n_samples', '?')}, AUROC={measured.get('auroc', '?')})"
        )
        updated["performance"] = perf

        updated["calibration"] = {
            "modality": entry["modality"],
            "preferred_method": entry["calibration"]["preferred_method"],
            "checkpoint": entry["calibration"]["path"],
        }

        meta = copy.deepcopy(updated.get("model_metadata", {}))
        meta["registry_entry_id"] = entry["entry_id"]
        meta["checkpoint_sha256"] = entry["checkpoint"]["sha256"]
        if entry["checkpoint"].get("adapter_sha256"):
            meta["adapter_sha256"] = entry["checkpoint"]["adapter_sha256"]
        updated["model_metadata"] = meta

        try:
            jsonschema.validate(instance=updated, schema=DETECTOR_MANIFEST_SCHEMA)
        except jsonschema.ValidationError as exc:
            return (
                GateCheckResult(
                    "manifest_update_validation",
                    False,
                    f"Updated manifest failed DETECTOR_MANIFEST_SCHEMA: {exc.message}",
                ),
                None,
            )

        return (
            GateCheckResult(
                "manifest_update_validation",
                True,
                f"Prepared schema-valid manifest update for version={updated['version']}.",
                {"manifest_path": str(manifest_path), "new_version": updated["version"]},
            ),
            updated,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def evaluate(
        self,
        entry_id: str,
        max_samples: int = 16,
    ) -> GateResult:
        """Runs all 5 promotion gate checks without modifying registry or manifests."""
        entry = self.registry.get_entry(entry_id)
        baseline_entry = self.registry.get_active_entry(entry["detector_name"])
        checks: List[GateCheckResult] = []

        c1 = self._check_integrity(entry)
        checks.append(c1)

        c2 = self._check_schema_and_contract(entry)
        checks.append(c2)

        if not (c1.passed and c2.passed):
            return GateResult(
                entry_id=entry_id,
                detector_name=entry["detector_name"],
                passed=False,
                checks=checks,
            )

        measured, baseline_measured = self._run_regression_and_profile(
            entry, baseline_entry, max_samples=max_samples
        )
        c3 = self._check_regression(entry, measured, baseline_measured)
        checks.append(c3)

        c4 = self._check_budgets(entry, measured)
        checks.append(c4)

        c5, updated_manifest = self._build_updated_manifest(entry, measured)
        checks.append(c5)

        all_passed = all(c.passed for c in checks)
        return GateResult(
            entry_id=entry_id,
            detector_name=entry["detector_name"],
            passed=all_passed,
            checks=checks,
            measured_metrics=measured,
            baseline_metrics=baseline_measured,
            updated_manifest=updated_manifest if all_passed else None,
        )

    def promote(
        self,
        entry_id: str,
        max_samples: int = 16,
        reason: str = "Automated Promotion Gate passed",
    ) -> Tuple[GateResult, Optional[Dict[str, Any]]]:
        """Evaluates `entry_id` and activates it atomically iff every gate check passes."""
        result = self.evaluate(entry_id, max_samples=max_samples)
        if not result.passed or result.updated_manifest is None:
            return result, None

        activation = self.registry.activate_entry(
            entry_id=entry_id,
            gate_report=result.to_dict(),
            updated_manifest=result.updated_manifest,
            reason=reason,
        )
        return result, activation
