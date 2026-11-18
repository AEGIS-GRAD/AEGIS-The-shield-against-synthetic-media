"""
AEGIS Adversarial Robustness Harness v1 (Week 10 Cyber Task 2)
==============================================================

Applies perturbations at several strengths and measures how detector scores and
decisions move. Reusable from the CLI against in-process detectors or any running
AEGIS ``/detect`` endpoint.

    # Image detector (Community Forensics), 200 labelled images
    python -m eval.robustness.harness image --manifest eval/data/robustness/image_manifest.json

    # Text detector (desklib), MAGE human vs GPT-4, plus real GPT-4 paraphrases
    python -m eval.robustness.harness text --mage-dir eval/data/robustness/text --n 60

    # Any running detector over HTTP (e.g. the docker stack)
    python -m eval.robustness.harness image --manifest ... --http http://localhost:8006 --token $INTERNAL_API_KEY

Outputs (``eval/reports/robustness/``): ``<detector>_scores.csv`` (one row per
sample x condition), ``<detector>_matrix.{csv,json}``, and the combined
``robustness_matrix_v1.md`` (rebuilt from every ``*_matrix.json`` present).

Metrics per condition (threshold 0.5 on P(synthetic), the services' decision point):
detection rate on synthetic samples, false-positive rate on real samples, ROC AUC
(threshold-free), and **evasion rate** = share of synthetic samples detected when
clean that are missed after the perturbation (the attacker's success metric).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import zlib
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from eval.robustness.perturbations import IMAGE_PERTURBATIONS, TEXT_PERTURBATIONS  # noqa: E402

THRESHOLD = 0.5
OUT_DIR = REPO / "eval" / "reports" / "robustness"


def auc(pos: Sequence[float], neg: Sequence[float]) -> Optional[float]:
    if not pos or not neg:
        return None
    p, n = np.asarray(pos)[:, None], np.asarray(neg)[None, :]
    return float((p > n).mean() + 0.5 * (p == n).mean())


def conditions(table: Dict[str, Tuple[Callable, Sequence[float]]], only: Optional[List[str]] = None):
    yield ("clean", 0.0, None)
    for name, (fn, strengths) in table.items():
        if only and name not in only:
            continue
        for s in strengths:
            yield (name, s, fn)


def _order_key(m: Dict) -> Tuple[int, int]:
    """clean first, then each family in table order, weakest -> strongest strength."""
    from eval.robustness.perturbations import IMAGE_PERTURBATIONS as IMG, TEXT_PERTURBATIONS as TXT

    families = ["clean"] + list(IMG) + list(TXT) + ["gpt4_paraphrase"]
    fam = families.index(m["perturbation"]) if m["perturbation"] in families else len(families)
    strengths = list((IMG.get(m["perturbation"]) or TXT.get(m["perturbation"]) or (None, ()))[1])
    pos = strengths.index(m["strength"]) if m["strength"] in strengths else 0
    return fam, pos


def summarise(rows: List[Dict], detector: str, model_version: str, extra: Dict) -> Dict:
    by_cond: Dict[Tuple[str, float], List[Dict]] = {}
    for r in rows:
        by_cond.setdefault((r["perturbation"], r["strength"]), []).append(r)
    clean = {r["sample_id"]: r["score"] for r in by_cond.get(("clean", 0.0), [])}
    matrix = []
    for (pert, strength), rs in by_cond.items():
        fake = [r for r in rs if r["label"] == 1]
        real = [r for r in rs if r["label"] == 0]
        fake_s, real_s = [r["score"] for r in fake], [r["score"] for r in real]
        detected_clean = [r for r in fake if clean.get(r["sample_id"], 0) >= THRESHOLD]
        evaded = [r for r in detected_clean if r["score"] < THRESHOLD]
        shift = [r["score"] - clean[r["sample_id"]] for r in rs if r["sample_id"] in clean]
        matrix.append({
            "detector": detector, "perturbation": pert, "strength": strength,
            "n_synthetic": len(fake), "n_real": len(real),
            "detection_rate": round(float(np.mean([s >= THRESHOLD for s in fake_s])), 4) if fake_s else None,
            "false_positive_rate": round(float(np.mean([s >= THRESHOLD for s in real_s])), 4) if real_s else None,
            "auc": round(auc(fake_s, real_s), 4) if auc(fake_s, real_s) is not None else None,
            "evasion_rate": round(len(evaded) / len(detected_clean), 4) if detected_clean else None,
            "mean_score_synthetic": round(float(np.mean(fake_s)), 4) if fake_s else None,
            "mean_score_real": round(float(np.mean(real_s)), 4) if real_s else None,
            "mean_abs_score_shift": round(float(np.mean(np.abs(shift))), 4) if shift else None,
        })
    matrix.sort(key=_order_key)
    return {"detector": detector, "model_version": model_version, "threshold": THRESHOLD,
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "matrix": matrix, **extra}


def write_outputs(detector: str, rows: List[Dict], summary: Dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"{detector}_scores.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(out_dir / f"{detector}_matrix.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary["matrix"][0].keys()))
        w.writeheader()
        w.writerows(summary["matrix"])
    (out_dir / f"{detector}_matrix.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    build_report(out_dir)


# ─────────────────────────────────────────────────────────────────────────────
# Image
# ─────────────────────────────────────────────────────────────────────────────
def run_image(args) -> None:
    from PIL import Image

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    rng = random.Random(args.seed)
    if args.limit and len(manifest) > args.limit:
        manifest = rng.sample(manifest, args.limit)
    if args.http:
        from eval.robustness.adapters import HttpDetectorAdapter

        det = HttpDetectorAdapter(args.http, "image", token=args.token)
    else:
        from eval.robustness.adapters import ImageCommForAdapter

        det = ImageCommForAdapter()
    images = []
    for i, m in enumerate(manifest):
        img = Image.open(REPO / m["path"]).convert("RGB")
        if max(img.size) > args.max_side:  # cap work for huge web images; same cap for every condition
            img.thumbnail((args.max_side, args.max_side))
        images.append((f"img{i:04d}", int(m["label"]), img))

    rows = []
    t0 = time.time()
    for pert, strength, fn in conditions(IMAGE_PERTURBATIONS, args.only):
        batch = [fn(img, strength, seed=zlib.crc32(sid.encode()) % 10_000) if fn else img for sid, _, img in images]
        scores = det.score_many(batch)
        for (sid, label, _), s in zip(images, scores):
            rows.append({"sample_id": sid, "label": label, "perturbation": pert, "strength": strength, "score": round(s, 5)})
        print(f"[image] {pert:7s} {strength:>6}  det={np.mean([s >= THRESHOLD for (_, l, _), s in zip(images, scores) if l == 1]):.2f}  "
              f"fpr={np.mean([s >= THRESHOLD for (_, l, _), s in zip(images, scores) if l == 0]):.2f}  ({time.time() - t0:.0f}s)", flush=True)
    summary = summarise(rows, "detector_image", det.model_version, {
        "dataset": "Hemg/AI-Generated-vs-Real-Images-Datasets (seeded sample, see eval/DATA.md)",
        "n_samples": len(images), "max_side": args.max_side})
    write_outputs("detector_image", rows, summary, Path(args.out))


# ─────────────────────────────────────────────────────────────────────────────
# Text
# ─────────────────────────────────────────────────────────────────────────────
def load_mage(mage_dir: Path, n: int, seed: int) -> List[Tuple[str, int, str, str]]:
    """Returns (sample_id, aegis_label, text, kind) with kind in {human, gpt4, gpt4_para}.

    MAGE convention: label "1" = human, "0" = machine; AEGIS: 1 = synthetic.
    """
    csv.field_size_limit(10 ** 8)
    rng = random.Random(seed)

    def read(name):
        with open(mage_dir / name, encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))

    ood = read("test_ood_set_gpt.csv")
    para = read("test_ood_set_gpt_para.csv")
    words = lambda t: len(t.split())  # noqa: E731
    keep = lambda t: 80 <= words(t) <= 450  # noqa: E731  (above the service's 40-word gate, one or two chunks)
    human = [r for r in ood if r["label"] == "1" and keep(r["text"])]
    gpt = [r for r in ood if r["label"] == "0" and keep(r["text"])]
    gpt_para = [r for r in para if r["label"] == "0" and r["src"].endswith("gpt4_para") and keep(r["text"])] or \
               [r for r in para if r["label"] == "0" and "para" in r["src"] and keep(r["text"])]
    out = []
    for kind, pool, label in (("human", human, 0), ("gpt4", gpt, 1), ("gpt4_para", gpt_para, 1)):
        for i, r in enumerate(rng.sample(pool, min(n, len(pool)))):
            out.append((f"{kind}{i:03d}", label, r["text"], kind))
    return out


def run_text(args) -> None:
    samples = load_mage(Path(args.mage_dir), args.n, args.seed)
    if args.http:
        from eval.robustness.adapters import HttpDetectorAdapter

        det = HttpDetectorAdapter(args.http, "text", token=args.token)
    else:
        from eval.robustness.adapters import TextDesklibAdapter

        det = TextDesklibAdapter()
    base = [(sid, lab, txt) for sid, lab, txt, kind in samples if kind != "gpt4_para"]
    rows = []
    t0 = time.time()
    for pert, strength, fn in conditions(TEXT_PERTURBATIONS, args.only):
        texts = [fn(t, strength, seed=zlib.crc32(sid.encode()) % 10_000) if fn else t for sid, _, t in base]
        scores = det.score_many(texts)
        for (sid, label, _), s in zip(base, scores):
            rows.append({"sample_id": sid, "label": label, "perturbation": pert, "strength": strength, "score": round(s, 5)})
        print(f"[text] {pert:10s} {strength:>5}  det={np.mean([s >= THRESHOLD for (_, l, _), s in zip(base, scores) if l == 1]):.2f}  "
              f"fpr={np.mean([s >= THRESHOLD for (_, l, _), s in zip(base, scores) if l == 0]):.2f}  ({time.time() - t0:.0f}s)", flush=True)
    # Natural paraphrase: GPT-4 rewrites of GPT-4 text (MAGE), scored clean, compared with the human set.
    para = [(sid, lab, txt) for sid, lab, txt, kind in samples if kind == "gpt4_para"]
    if para:
        scores = det.score_many([t for _, _, t in para])
        human_clean = [r for r in rows if r["perturbation"] == "clean" and r["label"] == 0]
        for (sid, label, _), s in zip(para, scores):
            rows.append({"sample_id": sid, "label": 1, "perturbation": "gpt4_paraphrase", "strength": 1.0, "score": round(s, 5)})
        for r in human_clean:
            rows.append(dict(r, perturbation="gpt4_paraphrase", strength=1.0))
        print(f"[text] gpt4_paraphrase  det={np.mean([s >= THRESHOLD for s in scores]):.2f}  ({time.time() - t0:.0f}s)", flush=True)
    summary = summarise(rows, "detector_text", det.model_version, {
        "dataset": "yaful/MAGE test_ood_set_gpt + test_ood_set_gpt_para (seeded sample, see eval/DATA.md)",
        "n_samples": len(samples),
        "note": "gpt4_paraphrase = independent GPT-4 paraphrases (not paired with the clean GPT-4 samples), "
                "so its evasion_rate is not defined; compare detection rates.",
    })
    write_outputs("detector_text", rows, summary, Path(args.out))


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────
def _fmt(v, pct=True):
    if v is None:
        return "—"
    return f"{v:.0%}" if pct else f"{v:.3f}"


def build_report(out_dir: Path) -> Path:
    sections = []
    for path in sorted(out_dir.glob("*_matrix.json")):
        s = json.loads(path.read_text(encoding="utf-8"))
        s["matrix"].sort(key=_order_key)
        lines = ["| Perturbation | Strength | Detection rate | FPR | AUC | Evasion rate | Mean P(syn) synthetic / real |",
                 "|---|:-:|:-:|:-:|:-:|:-:|:-:|"]
        for m in s["matrix"]:
            lines.append(f"| {m['perturbation']} | {m['strength']:g} | {_fmt(m['detection_rate'])} | {_fmt(m['false_positive_rate'])} | "
                         f"{_fmt(m['auc'], False)} | {_fmt(m['evasion_rate'])} | {_fmt(m['mean_score_synthetic'], False)} / {_fmt(m['mean_score_real'], False)} |")
        sections.append(f"## {s['detector']} — `{s['model_version']}`\n\nDataset: {s.get('dataset')} · samples: {s.get('n_samples')} "
                        f"· generated {s['generated_utc'][:16]} UTC\n\n" + "\n".join(lines) + (f"\n\n_{s['note']}_" if s.get("note") else ""))
    md = (f"# AEGIS Robustness Matrix v1 — detection rate vs perturbation strength\n\n"
          f"**Task:** Week 10 Cybersecurity Task 2 (joint AI/security) · **Harness:** `python -m eval.robustness.harness`\n"
          f"Decision threshold P(synthetic) ≥ {THRESHOLD}. Evasion rate = synthetic samples detected when clean but missed after "
          f"the perturbation. Strengths deliberately avoid the fine-tuning augmentations and the team's existing "
          f"`jpeg75`/`jpeg50`/`resize0.5` eval variants (see `eval/robustness/perturbations.py`).\n\n" + "\n\n".join(sections) + "\n")
    report = out_dir / "robustness_matrix_v1.md"
    report.write_text(md, encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="modality", required=True)
    for name in ("image", "text"):
        p = sub.add_parser(name)
        p.add_argument("--out", default=str(OUT_DIR))
        p.add_argument("--seed", type=int, default=1116)
        p.add_argument("--only", nargs="*", help="restrict to these perturbation families")
        p.add_argument("--http", help="score through a running detector's /detect instead of in-process")
        p.add_argument("--token", default=None)
    sub.choices["image"].add_argument("--manifest", default=str(REPO / "eval" / "data" / "robustness" / "image_manifest.json"))
    sub.choices["image"].add_argument("--limit", type=int, default=200)
    sub.choices["image"].add_argument("--max-side", type=int, default=1024)
    sub.choices["text"].add_argument("--mage-dir", default=str(REPO / "eval" / "data" / "robustness" / "text"))
    sub.choices["text"].add_argument("--n", type=int, default=60, help="samples per class (human / gpt4 / gpt4_para)")
    sub.add_parser("report").add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()
    if args.modality == "image":
        run_image(args)
    elif args.modality == "text":
        run_text(args)
    print(f"Report -> {build_report(Path(args.out))}")


if __name__ == "__main__":
    main()
