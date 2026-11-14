"""
Build an interim text evaluation manifest from ungated public datasets (yaful/MAGE).

Interim substitute pending AI Task 4's curated synthetic-text benchmark. Uses the
same JSONL schema expected by `baseline.py --manifest` so Task 4's final text set
can drop in without changing evaluation code.

Note: In yaful/MAGE CSVs, `label == "1"` denotes human text and `label == "0"`
denotes machine-generated/paraphrased text. This builder converts those into
AEGIS canonical labels (`0 = human`, `1 = ai`) explicitly.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

HF_MAGE_BASE = "https://huggingface.co/datasets/yaful/MAGE/resolve/main"
OOD_GPT_CSV = f"{HF_MAGE_BASE}/test_ood_set_gpt.csv"
OOD_PARA_CSV = f"{HF_MAGE_BASE}/test_ood_set_gpt_para.csv"
TEST_CSV = f"{HF_MAGE_BASE}/test.csv"

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "eval" / "data" / "text" / "text_eval_manifest.jsonl"

_KNOWN_MAGE_PARSED_SUFFIXES = (
    "_human_para",
    "_gpt4_para",
    "_human",
    "_gpt4",
)


def _length_bucket(word_count: int) -> str:
    if word_count < 40:
        return "short_lt40"
    if word_count < 150:
        return "marginal_40_149"
    if word_count < 500:
        return "medium_150_499"
    return "long_500_plus"


def _parse_src(src: str, mage_label: str) -> Tuple[str, str, bool]:
    """Extract (domain, generator, paraphrased) from yaful/MAGE `src` metadata."""
    s = (src or "").strip()
    paraphrased = "para" in s.lower()
    if mage_label == "1":
        domain = s.replace("_human", "").strip("_") or "unknown"
        return domain, "human", False

    for suffix in ("_gpt4_para", "_gpt4"):
        if s.endswith(suffix):
            return s[: -len(suffix)] or "unknown", "gpt-4", paraphrased
    if s.endswith("_human_para"):
        return s[: -len("_human_para")] or "unknown", "gpt-paraphraser", True

    if "_machine_" in s:
        domain, rest = s.split("_machine_", 1)
        gen = re.sub(r"^(continuation|topical|specified)_", "", rest)
        return domain or "unknown", gen or "llm", paraphrased

    parts = s.split("_", 1)
    if len(parts) == 2:
        return parts[0], parts[1], paraphrased
    return s or "unknown", "llm", paraphrased


def _row_to_record(row: Dict[str, str], origin: str) -> Dict[str, object] | None:
    text = (row.get("text") or "").strip()
    raw_label = str(row.get("label") or "").strip()
    if not text or raw_label not in ("0", "1"):
        return None

    # MAGE convention: "1" = human, "0" = synthetic/paraphrased -> AEGIS: 0 = human, 1 = ai
    is_human = raw_label == "1"
    aegis_label = 0 if is_human else 1
    words = len(re.findall(r"\b\w+\b", text))
    domain, generator, paraphrased = _parse_src(row.get("src", ""), raw_label)
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return {
        "id": f"mage-{origin}-{digest}",
        "text": text,
        "label": aegis_label,
        "class_name": "human" if is_human else "ai",
        "generator": generator,
        "domain": domain,
        "paraphrased": paraphrased,
        "word_count": words,
        "length_bucket": _length_bucket(words),
        "source_dataset": f"yaful/MAGE:{origin} (interim pending Task 4)",
    }


def _fetch_csv_rows(url: str) -> List[Dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "AEGIS-Eval-Builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read().decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(data)))


def _stream_csv_rows(url: str, max_rows: int = 8000) -> Iterable[Dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "AEGIS-Eval-Builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        text_stream = io.TextIOWrapper(resp, encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.DictReader(text_stream)
        for i, row in enumerate(reader):
            yield row
            if i + 1 >= max_rows:
                break


def _sample_stratified(
    records: List[Dict[str, object]],
    target: int,
    rng: random.Random,
    key_fn,
) -> List[Dict[str, object]]:
    if len(records) <= target:
        return list(records)
    buckets: Dict[object, List[Dict[str, object]]] = defaultdict(list)
    for rec in records:
        buckets[key_fn(rec)].append(rec)
    for bucket in buckets.values():
        rng.shuffle(bucket)

    selected: List[Dict[str, object]] = []
    keys = sorted(buckets.keys(), key=str)
    while len(selected) < target and any(buckets.values()):
        for k in keys:
            if buckets[k] and len(selected) < target:
                selected.append(buckets[k].pop())
    return selected


def build_interim_manifest(
    output_path: Path = DEFAULT_OUT,
    human_target: int = 160,
    gpt4_target: int = 120,
    para_target: int = 80,
    mage_test_target: int = 80,
    seed: int = 42,
) -> Path:
    """Download balanced OOD/paraphrased/in-domain splits and write JSONL manifest."""
    rng = random.Random(seed)
    seen_ids = set()

    def _dedupe(items: Iterable[Dict[str, object] | None]) -> List[Dict[str, object]]:
        out = []
        for item in items:
            if item is None or item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            out.append(item)
        return out

    ood_rows = _fetch_csv_rows(OOD_GPT_CSV)
    ood_recs = _dedupe(_row_to_record(r, "ood_gpt") for r in ood_rows)
    ood_humans = [r for r in ood_recs if r["label"] == 0]
    ood_gpt4 = [r for r in ood_recs if r["label"] == 1]

    para_rows = _fetch_csv_rows(OOD_PARA_CSV)
    para_recs = _dedupe(_row_to_record(r, "ood_para") for r in para_rows)
    para_ai = [r for r in para_recs if r["label"] == 1]

    mage_pool = _dedupe(_row_to_record(r, "test") for r in _stream_csv_rows(TEST_CSV, max_rows=8000))
    mage_humans = [r for r in mage_pool if r["label"] == 0]
    mage_ai = [r for r in mage_pool if r["label"] == 1]

    selected_humans = _sample_stratified(
        ood_humans + mage_humans,
        human_target,
        rng,
        key_fn=lambda r: (r["domain"], r["length_bucket"]),
    )
    selected_gpt4 = _sample_stratified(
        ood_gpt4,
        gpt4_target,
        rng,
        key_fn=lambda r: (r["domain"], r["length_bucket"]),
    )
    selected_para = _sample_stratified(
        para_ai,
        para_target,
        rng,
        key_fn=lambda r: (r["generator"], r["length_bucket"]),
    )
    selected_mage_ai = _sample_stratified(
        mage_ai,
        mage_test_target,
        rng,
        key_fn=lambda r: (r["generator"], r["length_bucket"]),
    )

    combined = selected_humans + selected_gpt4 + selected_para + selected_mage_ai
    rng.shuffle(combined)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for rec in combined:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(
        f"Wrote {len(combined)} samples to {output_path} "
        f"(human={len(selected_humans)}, gpt4={len(selected_gpt4)}, "
        f"paraphrased={len(selected_para)}, mage_other_llm={len(selected_mage_ai)})"
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage interim AEGIS text evaluation dataset.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--human", type=int, default=160)
    parser.add_argument("--gpt4", type=int, default=120)
    parser.add_argument("--para", type=int, default=80)
    parser.add_argument("--mage-llm", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    build_interim_manifest(
        output_path=args.out,
        human_target=args.human,
        gpt4_target=args.gpt4,
        para_target=args.para,
        mage_test_target=args.mage_llm,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()

