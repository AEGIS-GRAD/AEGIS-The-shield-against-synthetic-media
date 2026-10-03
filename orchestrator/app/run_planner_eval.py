"""
Planner evaluation runner — v1
================================
Runs the v1 LLM planning prompt against the 19-sample test set and produces
the evaluation_notes.md deliverable required by the task.

For each sample this script:
  1. Runs the deterministic eligibility filter (eligibility.py) against the
     REAL capability manifests in capability_manifests/*.json
  2. Builds the v1 prompt (prompt_builder.py)
  3. Calls the LLM (same OpenRouter pattern as the Month 1 spike notebook)
  4. Validates the returned plan against: valid JSON, schema shape,
     eligibility safety (no excluded/invented detector ids), and budget
     compliance
  5. Writes one row per sample to evaluation_notes.md, plus a summary table
     against the 9 success criteria in orchestrator_design.md section 7

Usage:
    export OPENROUTER_API_KEY=sk-...
    python run_planner_eval.py
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

from eligibility import filter_detectors
from prompt_builder import build_planning_prompt, PROMPT_VERSION
from eval_samples import SAMPLES

# ---- paths: adjust if your repo layout differs ----
REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # orchestrator/app/<this file> -> up 3 levels to repo root
MANIFESTS_DIR = REPO_ROOT / "capability_manifests"
OUTPUT_PATH = REPO_ROOT / "eval" / "reports" / "planner_v1_evaluation_notes.md"

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Same model list as the Month 1 spike notebook — first one that answers wins.
MODELS = [
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "inclusionai/ling-3.0-flash-fin:free",
]


def load_manifests() -> list[dict]:
    manifests = []
    for path in MANIFESTS_DIR.glob("*.json"):
        with open(path, "r", encoding="utf-8") as f:
            manifests.append(json.load(f))
    if not manifests:
        print(f"ERROR: no manifest JSON files found in {MANIFESTS_DIR}", file=sys.stderr)
        sys.exit(1)
    return manifests


def call_llm(prompt: str) -> tuple[dict | None, str, float]:
    """Returns (parsed_plan_or_None, model_used_or_error, latency_s)."""
    if not OPENROUTER_API_KEY:
        return None, "NO_API_KEY_SET", 0.0

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    for model_name in MODELS:
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        t0 = time.time()
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=15)
            latency = time.time() - t0
            if resp.status_code != 200:
                continue
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return json.loads(raw), model_name, latency
        except Exception as e:
            continue
    return None, "ALL_MODELS_FAILED", time.time() - t0


REQUIRED_PLAN_KEYS = {"plan_version", "stages", "skipped", "coverage_warnings", "estimated_latency_s", "rationale"}


def validate_plan(plan: dict | None, eligible_ids: set[str], budget_s: float) -> list[str]:
    """Returns a list of validation problems. Empty list = fully valid."""
    problems = []
    if plan is None:
        return ["plan is None (LLM call failed or returned unparseable output)"]

    missing_keys = REQUIRED_PLAN_KEYS - plan.keys()
    if missing_keys:
        problems.append(f"missing schema keys: {missing_keys}")

    used_ids = set()
    for stage in plan.get("stages", []):
        for det_id in stage.get("run", []):
            used_ids.add(det_id)

    invented_or_ineligible = used_ids - eligible_ids
    if invented_or_ineligible:
        problems.append(f"used ineligible/invented detector ids: {invented_or_ineligible}")

    est = plan.get("estimated_latency_s")
    if est is not None and est > budget_s:
        problems.append(f"estimated_latency_s ({est}) exceeds budget ({budget_s})")

    return problems


def main():
    manifests = load_manifests()
    print(f"Loaded {len(manifests)} capability manifests: {[m['detector_name'] for m in manifests]}")

    rows = []
    for idx, (input_summary, risk_profile, budget_s, note) in enumerate(SAMPLES, 1):
        eligible, excluded = filter_detectors(manifests, input_summary)
        eligible_ids = {m["detector_name"] for m in eligible}

        prompt = build_planning_prompt(eligible, excluded, input_summary, risk_profile, budget_s)
        plan, model_or_error, latency_s = call_llm(prompt)
        problems = validate_plan(plan, eligible_ids, budget_s)

        status = "PASS" if not problems else "FAIL"
        print(f"[{idx:2}/{len(SAMPLES)}] {status:4} | {note[:60]:60} | model={model_or_error} | {latency_s:.1f}s")

        rows.append({
            "idx": idx,
            "note": note,
            "eligible_ids": sorted(eligible_ids),
            "excluded": excluded,
            "model": model_or_error,
            "latency_s": round(latency_s, 2),
            "plan": plan,
            "problems": problems,
            "status": status,
        })

    write_report(rows)
    print(f"\nWrote evaluation notes to {OUTPUT_PATH}")


def write_report(rows: list[dict]):
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    passed = sum(1 for r in rows if r["status"] == "PASS")
    total = len(rows)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("# Planner v1 — Evaluation Notes\n\n")
        f.write(f"Prompt version: `{PROMPT_VERSION}`\n\n")
        f.write(f"**{passed}/{total} samples passed validation** "
                f"(valid JSON, schema-conformant, no ineligible detector used, within budget).\n\n")
        f.write("---\n\n")

        for r in rows:
            f.write(f"## Sample {r['idx']}: {r['note']}\n\n")
            f.write(f"- Eligible detectors: `{r['eligible_ids']}`\n")
            f.write(f"- Excluded: `{r['excluded']}`\n")
            f.write(f"- Model used: `{r['model']}` (latency: {r['latency_s']}s)\n")
            f.write(f"- Validation: **{r['status']}**")
            if r["problems"]:
                f.write(f" — {'; '.join(r['problems'])}")
            f.write("\n\n")
            f.write("```json\n")
            f.write(json.dumps(r["plan"], indent=2) if r["plan"] else "null")
            f.write("\n```\n\n")
            f.write("**Reviewer notes:** _(fill in after reading — was this a good decision?)_\n\n")
            f.write("---\n\n")


if __name__ == "__main__":
    main()
