"""CLI and Desklib promotion/rollback demonstration for AEGIS Model Registry."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model_registry.gate import PromotionGate  # noqa: E402
from model_registry.registry import ModelRegistry  # noqa: E402


def _render_demo_markdown(payload: Dict[str, Any]) -> str:
    pre = payload["pre_promotion"]
    gate = payload["gate_result"]
    prom = payload["promoted_state"]
    rb = payload["rollback_state"]

    cand = gate["measured_metrics"]
    base = gate.get("baseline_metrics") or {}

    lines = [
        "# AEGIS Model Registry & Promotion Gate — Desklib Promotion & Rollback Demo",
        "",
        f"**Registry File:** `{payload['registry_path']}`  ",
        f"**Target Detector:** `{payload['detector_name']}`  ",
        f"**Staged Evaluation Subset:** `{cand.get('eval_manifest')}` ($N = {cand.get('n_samples')}$ stratified samples)  ",
        f"**Execution Device:** `{str(cand.get('device', 'cpu')).upper()}`",
        "",
        "---",
        "",
        "## 1. Pre-Promotion Baseline State",
        "",
        f"- **Active Entry:** `{pre['active_entry_id']}`",
        f"- **Manifest `version`:** `{pre['manifest_version']}`",
        f"- **Calibration Checkpoint:** `{pre['calibration_checkpoint']}`",
        "",
        "---",
        "",
        "## 2. Automatic Promotion Gate Checks (`detector_text@1.1.0-lora-finetuned`)",
        "",
        "| Gate Check | Status | Summary |",
        "| :--- | :---: | :--- |",
    ]
    for chk in gate["checks"]:
        badge = "PASS" if chk["passed"] else "FAIL"
        lines.append(f"| `{chk['name']}` | **{badge}** | {chk['summary']} |")

    lines.extend(
        [
            "",
            "### Staged Subset Regression & Resource Comparison",
            "",
            "| Metric | As-Is Baseline (`1.0.0-asis`) | Fine-Tuned LoRA (`1.1.0-lora-finetuned`) | Delta |",
            "| :--- | :---: | :---: | :---: |",
            f"| **ROC-AUC** | {base.get('auroc', 'N/A')} | **{cand.get('auroc')}** | {round(cand.get('auroc', 0) - base.get('auroc', 0), 4):+.4f} |",
            f"| **Accuracy @ 0.5** | {base.get('accuracy', 'N/A')} | **{cand.get('accuracy')}** | {round(cand.get('accuracy', 0) - base.get('accuracy', 0), 4):+.4f} |",
            f"| **F1 @ 0.5** | {base.get('f1', 'N/A')} | **{cand.get('f1')}** | {round(cand.get('f1', 0) - base.get('f1', 0), 4):+.4f} |",
            f"| **TPR @ 1% FPR** | {base.get('tpr_at_1pct_fpr', 'N/A')} | **{cand.get('tpr_at_1pct_fpr')}** | {round(cand.get('tpr_at_1pct_fpr', 0) - base.get('tpr_at_1pct_fpr', 0), 4):+.4f} |",
            f"| **Calibrated ECE (10-bin)** | {base.get('calibrated_ece', 'N/A')} | **{cand.get('calibrated_ece')}** | {round(cand.get('calibrated_ece', 0) - base.get('calibrated_ece', 0), 4):+.4f} |",
            f"| **Avg Latency (ms)** | {base.get('avg_latency_ms', 'N/A')} | **{cand.get('avg_latency_ms')}** | {round(cand.get('avg_latency_ms', 0) - base.get('avg_latency_ms', 0), 2):+.2f} |",
            f"| **P95 Latency (ms)** | {base.get('p95_latency_ms', 'N/A')} | **{cand.get('p95_latency_ms')}** | {round(cand.get('p95_latency_ms', 0) - base.get('p95_latency_ms', 0), 2):+.2f} |",
            f"| **Peak RAM (MB)** | {base.get('peak_ram_mb', 'N/A')} | **{cand.get('peak_ram_mb')}** | — |",
            "",
            "---",
            "",
            "## 3. Promoted State (Post-Gate Activation)",
            "",
            f"- **Active Entry:** `{prom['active_entry_id']}` (previous `{prom['from_entry_id']}` → `archived`)",
            f"- **Updated Manifest `version`:** `{prom['manifest_version']}`",
            f"- **Updated Manifest `registry_entry_id`:** `{prom['manifest_registry_entry_id']}`",
            f"- **Updated `performance.measured_on`:** `{prom['manifest_measured_on']}`",
            "",
            "---",
            "",
            "## 4. Rollback State (Restored to As-Is Baseline)",
            "",
            f"- **Active Entry:** `{rb['active_entry_id']}` (rolled back `{rb['rolled_back_from']}` → `rolled_back`)",
            f"- **Restored Manifest `version`:** `{rb['manifest_version']}`",
            f"- **Restored Calibration Checkpoint:** `{rb['calibration_checkpoint']}`",
            f"- **Manifest Schema Valid:** `{rb['manifest_schema_valid']}`",
            "",
        ]
    )
    return "\n".join(lines)


def run_desklib_demo(
    registry: ModelRegistry,
    max_samples: int = 16,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Promotes `detector_text@1.1.0-lora-finetuned` over `as-is` and rolls it back."""
    out_dir = Path(output_dir) if output_dir else (REPO_ROOT / "eval" / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    detector = "detector_text"
    candidate_id = "detector_text@1.1.0-lora-finetuned"
    pre_active = registry.get_active_entry(detector)
    assert pre_active is not None
    manifest_path = registry._resolve_repo_path(pre_active["manifest_path"])
    pre_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    pre_snapshot = {
        "active_entry_id": pre_active["entry_id"],
        "manifest_version": pre_manifest.get("version"),
        "calibration_checkpoint": pre_manifest.get("calibration", {}).get("checkpoint"),
    }

    gate = PromotionGate(registry)
    gate_result, activation = gate.promote(
        candidate_id,
        max_samples=max_samples,
        reason="Task #5 demonstration: promote fine-tuned Desklib LoRA over as-is baseline",
    )
    if not gate_result.passed or activation is None:
        raise RuntimeError(
            f"Desklib promotion gate failed unexpectedly: {json.dumps(gate_result.to_dict(), indent=2)}"
        )

    prom_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    promoted_state = {
        "active_entry_id": registry.get_active_entry(detector)["entry_id"],  # type: ignore[index]
        "from_entry_id": activation["from_entry_id"],
        "manifest_version": prom_manifest.get("version"),
        "manifest_registry_entry_id": prom_manifest.get("registry_entry_id"),
        "manifest_measured_on": prom_manifest.get("performance", {}).get("measured_on"),
    }

    rb_res = registry.rollback(
        detector_name=detector,
        reason="Task #5 demonstration: rollback fine-tuned Desklib to as-is baseline",
    )
    rb_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    from capability_manifests.Schema import DETECTOR_MANIFEST_SCHEMA
    import jsonschema

    jsonschema.validate(instance=rb_manifest, schema=DETECTOR_MANIFEST_SCHEMA)
    rollback_state = {
        "active_entry_id": registry.get_active_entry(detector)["entry_id"],  # type: ignore[index]
        "rolled_back_from": rb_res["rolled_back_from"],
        "manifest_version": rb_manifest.get("version"),
        "calibration_checkpoint": rb_manifest.get("calibration", {}).get("checkpoint"),
        "manifest_schema_valid": True,
    }

    payload: Dict[str, Any] = {
        "registry_path": str(registry.registry_path),
        "detector_name": detector,
        "pre_promotion": pre_snapshot,
        "gate_result": gate_result.to_dict(),
        "promoted_state": promoted_state,
        "rollback_state": rollback_state,
    }

    json_out = out_dir / "model_registry_promotion_demo.json"
    md_out = out_dir / "model_registry_promotion_demo.md"
    json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_out.write_text(_render_demo_markdown(payload), encoding="utf-8")
    return payload


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="AEGIS Versioned Model Registry & Promotion Gate CLI"
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="Path to registry.json (defaults to model_registry/registry.json)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List registered model entries")
    p_list.add_argument("--detector", default=None)

    sub.add_parser("verify", help="Verify all registry hashes, schemas, and calibrations")

    p_reg = sub.add_parser("register", help="Register a new candidate entry from JSON file")
    p_reg.add_argument("--file", type=Path, required=True)
    p_reg.add_argument("--no-verify-files", action="store_true")

    p_gate = sub.add_parser("gate", help="Dry-run promotion gate on an entry")
    p_gate.add_argument("entry_id")
    p_gate.add_argument("--max-samples", type=int, default=16)

    p_prom = sub.add_parser("promote", help="Run promotion gate and activate entry if passed")
    p_prom.add_argument("entry_id")
    p_prom.add_argument("--max-samples", type=int, default=16)
    p_prom.add_argument("--reason", default="CLI promotion")

    p_rb = sub.add_parser("rollback", help="Roll back a detector to its prior active entry")
    p_rb.add_argument("detector_name")
    p_rb.add_argument("--to", dest="target_entry_id", default=None)
    p_rb.add_argument("--reason", default="CLI rollback")

    p_demo = sub.add_parser(
        "demo-desklib",
        help="Promote fine-tuned Desklib over as-is Desklib, then roll back cleanly",
    )
    p_demo.add_argument("--max-samples", type=int, default=16)
    p_demo.add_argument("--output-dir", type=Path, default=None)

    args = parser.parse_args(argv)
    registry = ModelRegistry(registry_path=args.registry)

    if args.command == "list":
        out = {
            "active": registry.data["active"],
            "entries": registry.list_entries(detector_name=args.detector),
        }
        print(json.dumps(out, indent=2))
        return 0

    if args.command == "verify":
        res = registry.verify_all()
        print(json.dumps(res, indent=2))
        return 0 if res["all_verified"] else 1

    if args.command == "register":
        entry = json.loads(args.file.read_text(encoding="utf-8"))
        saved = registry.register_entry(entry, verify_files=not args.no_verify_files)
        print(json.dumps(saved, indent=2))
        return 0

    if args.command == "gate":
        gate = PromotionGate(registry)
        res = gate.evaluate(args.entry_id, max_samples=args.max_samples)
        print(json.dumps(res.to_dict(), indent=2))
        return 0 if res.passed else 1

    if args.command == "promote":
        gate = PromotionGate(registry)
        res, act = gate.promote(args.entry_id, max_samples=args.max_samples, reason=args.reason)
        print(json.dumps({"gate": res.to_dict(), "activation": act}, indent=2))
        return 0 if res.passed else 1

    if args.command == "rollback":
        res = registry.rollback(
            args.detector_name,
            target_entry_id=args.target_entry_id,
            reason=args.reason,
        )
        print(json.dumps(res, indent=2))
        return 0

    if args.command == "demo-desklib":
        res = run_desklib_demo(
            registry,
            max_samples=args.max_samples,
            output_dir=args.output_dir,
        )
        print(json.dumps(res, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
