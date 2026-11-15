"""Check staged sets: size >=200, provenance, leakage vs fine-tuning data; writes eval/reports/task4_split_note.md.
  python eval/scripts/task4_validate_eval_sets.py     (exit 1 on failure)
"""
import collections, json, sys
from task4_common import ROOT, cfg, read_csv, sha256

def main():
    C = cfg(); errs = []; note = ["# Train / eval split note", ""]
    img = read_csv(C["image"]["manifest"])
    if len(img) < 200: errs.append(f"image set {len(img)} < 200")
    errs += [f"missing provenance: {r['id']}" for r in img if not r["source"] or not r["license"]]
    bal = collections.Counter(r["label"] for r in img if r["variant"] == "clean")
    gens = sorted({r["generator"] for r in img if r["label"] == "fake"})
    note.append(f"- Images: {len(img)} rows; clean per class {dict(bal)}; fake generators in eval (must be held out of fine-tuning): {gens}")
    ft = ROOT / C["image"]["finetune_dir"]
    if ft.exists():
        hashes = {sha256(p) for p in ft.rglob("*") if p.is_file()}
        leaks = [r["id"] for r in img if r["sha256"] in hashes]
        if leaks: errs.append(f"{len(leaks)} eval images also in fine-tune data, e.g. {leaks[:3]}")
        note.append(f"- Image leakage vs {C['image']['finetune_dir']}: {len(leaks)} exact duplicates")
    else:
        note.append("- Image leakage check: fine-tune dir not found - SKIPPED")
    txt = [json.loads(l) for l in (ROOT / C["text"]["manifest"]).read_text().splitlines() if l]
    if len(txt) < 200: errs.append(f"text set {len(txt)} < 200")
    ftt = ROOT / C["text"]["finetune_dir"]
    if ftt.exists():
        blob = "\n".join(p.read_text() for p in ftt.rglob("*.jsonl"))
        dup = [t["id"] for t in txt if t["text"][:80] in blob]
        if dup: errs.append(f"{len(dup)} text eval items overlap fine-tune text")
    note.append(f"- Text: {len(txt)} rows: {dict(collections.Counter((t['label'], t['length'], t['variant']) for t in txt))}")
    for k in ("audio_nonspeech", "audio_dubbed"):
        try: note.append(f"- {k}: {len(read_csv(C[k]['manifest']))} clips")
        except FileNotFoundError: errs.append(f"{k} manifest missing")
    rp = ROOT / C["report"]; rp.parent.mkdir(parents=True, exist_ok=True); rp.write_text("\n".join(note) + "\n")
    print("\n".join(note))
    if errs: print("\nFAIL:\n" + "\n".join(errs)); sys.exit(1)
    print("\nOK")

if __name__ == "__main__":
    main()
