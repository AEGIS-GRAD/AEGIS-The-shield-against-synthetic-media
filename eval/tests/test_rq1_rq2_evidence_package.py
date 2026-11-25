"""Tests for Task #2: RQ1 & RQ2 Evidence Package, Statistical Tests & Executed Notebook."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from eval.scripts.run_rq1_rq2_evidence_package import (
    build_rq1_dataset,
    compute_paired_continuous_stats,
    run_evidence_package,
    run_rq1_experiment,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "eval" / "reports"
FIGURES_DIR = REPORTS_DIR / "rq1_rq2_figures"
NOTEBOOK_PATH = REPO_ROOT / "eval" / "notebooks" / "rq1_rq2_evidence_package.ipynb"


def test_rq1_dataset_covers_all_four_modalities():
    samples = build_rq1_dataset(seed=2026)
    assert len(samples) >= 40
    modalities = {s.modality for s in samples}
    assert modalities == {"video", "audio", "image", "text"}
    for mod in modalities:
        mod_samples = [s for s in samples if s.modality == mod]
        assert len(mod_samples) >= 8
        assert {s.ground_truth for s in mod_samples} == {"AUTHENTIC", "SYNTHETIC"}


def test_paired_stats_handles_ties_and_significant_diffs():
    # Exact tie case (single-detector clean modality)
    tie = compute_paired_continuous_stats([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert tie["t_p_value"] == 1.0
    assert tie["wilcoxon_p_value"] == 1.0
    assert tie["cohens_dz"] == 0.0

    # Clear positive difference
    sig = compute_paired_continuous_stats(
        [10.0, 12.0, 11.5, 13.0, 14.0, 10.5, 12.5, 13.5],
        [4.0, 5.0, 4.5, 5.5, 6.0, 4.2, 5.1, 5.3],
    )
    assert sig["mean_diff"] > 5.0
    assert sig["t_p_value"] < 0.001
    assert sig["wilcoxon_p_value"] < 0.05
    assert sig["cohens_dz"] > 1.0
    assert sig["rank_biserial_r"] == 1.0


def test_rq1_three_arm_efficiency_and_significance():
    res = run_rq1_experiment(seed=2026, live_llm=False)
    ov = res["overall_by_arm"]
    pw = res["pairwise_tests"]

    # LLM Planner reduces compute cost and wasted dispatches vs both baselines
    assert ov["llm_planner"]["mean_compute_cost_s"] < ov["rule_based"]["mean_compute_cost_s"]
    assert ov["rule_based"]["mean_compute_cost_s"] < ov["static_ensemble"]["mean_compute_cost_s"]
    assert ov["llm_planner"]["total_wasted_dispatches"] < ov["rule_based"]["total_wasted_dispatches"]
    assert ov["rule_based"]["total_wasted_dispatches"] < ov["static_ensemble"]["total_wasted_dispatches"]

    # Higher or equal budget compliance, no accuracy/safety regression
    assert ov["llm_planner"]["budget_compliance_rate"] >= ov["rule_based"]["budget_compliance_rate"]
    assert ov["llm_planner"]["budget_compliance_rate"] >= ov["static_ensemble"]["budget_compliance_rate"]
    assert ov["llm_planner"]["verdict_accuracy"] >= ov["static_ensemble"]["verdict_accuracy"]
    assert ov["llm_planner"]["false_authentics"] <= ov["static_ensemble"]["false_authentics"]

    # Significance tests valid and Holm-monotonic
    for contrast in ("llm_vs_static", "llm_vs_rule"):
        cc = pw[contrast]["compute_cost_s"]
        assert cc["wilcoxon_p_holm"] >= cc["wilcoxon_p_value"]
        assert cc["t_p_holm"] >= cc["t_p_value"]
        assert cc["wilcoxon_p_holm"] < 0.01
        assert cc["t_p_holm"] < 0.01


def test_evidence_package_end_to_end_in_tmp_dir(tmp_path: Path):
    summary = run_evidence_package(output_dir=tmp_path, seed=2026, live_llm=False)
    assert (tmp_path / "rq1_planner_efficiency_raw.csv").is_file()
    assert (tmp_path / "rq1_rq2_evidence_summary.json").is_file()
    assert (tmp_path / "rq1_rq2_evidence_report.md").is_file()

    fig_dir = tmp_path / "rq1_rq2_figures"
    for stem in (
        "fig1_rq1_modality_efficiency",
        "fig2_rq1_paired_savings_and_waste",
        "fig3_rq2_learning_curves",
        "fig4_rq2_specificity_and_safety",
    ):
        assert (fig_dir / f"{stem}.png").stat().st_size > 1000
        assert (fig_dir / f"{stem}.pdf").stat().st_size > 1000

    assert summary["rq2"]["augmented_tests"]["sample_level_s2_to_sN"]["compute_cost_s"]["wilcoxon_p_value"] < 0.001


def test_committed_evidence_artifacts_and_executed_notebook():
    nbformat = pytest.importorskip("nbformat")

    assert (REPORTS_DIR / "rq1_planner_efficiency_raw.csv").is_file()
    assert (REPORTS_DIR / "rq1_rq2_evidence_summary.json").is_file()
    assert (REPORTS_DIR / "rq1_rq2_evidence_report.md").is_file()
    assert NOTEBOOK_PATH.is_file()

    with (REPORTS_DIR / "rq1_planner_efficiency_raw.csv").open("r", encoding="utf-8") as fh:
        csv_rows = list(csv.DictReader(fh))
    assert len(csv_rows) == 48 * 3

    summary = json.loads((REPORTS_DIR / "rq1_rq2_evidence_summary.json").read_text(encoding="utf-8"))
    assert summary["rq1"]["overall_by_arm"]["llm_planner"]["mean_compute_cost_s"] < summary["rq1"]["overall_by_arm"]["static_ensemble"]["mean_compute_cost_s"]
    assert summary["rq2"]["statistics"]["loop_on"]["nominal_retention_rate"] == 1.0

    for stem in (
        "fig1_rq1_modality_efficiency",
        "fig2_rq1_paired_savings_and_waste",
        "fig3_rq2_learning_curves",
        "fig4_rq2_specificity_and_safety",
    ):
        assert (FIGURES_DIR / f"{stem}.png").is_file()
        assert (FIGURES_DIR / f"{stem}.pdf").is_file()

    nb = nbformat.read(NOTEBOOK_PATH, as_version=4)
    code_cells = [c for c in nb.cells if c.cell_type == "code"]
    assert len(code_cells) >= 5
    embedded_pngs = 0
    for cell in code_cells:
        assert cell.execution_count is not None, "Notebook contains unexecuted code cell!"
        for out in cell.outputs:
            assert out.get("output_type") != "error", f"Notebook cell error: {out}"
            if "data" in out and "image/png" in out["data"]:
                embedded_pngs += 1
    assert embedded_pngs >= 4
