"""Stage human-vs-LLM text eval set (long/short, clean/paraphrased). Needs ANTHROPIC_API_KEY.
  python eval/scripts/task4_stage_text.py
Human text: public news corpus. LLM text: freshly generated (unseen by the text detector).
"""
import json, re
from task4_common import ROOT, cfg

def words(t): return len(t.split())

def trim(text, lo, hi):
    out = []
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        if words(" ".join(out + [s])) > hi: break
        out.append(s)
    t = " ".join(out)
    return t if lo <= words(t) <= hi else None

def main():
    import anthropic
    from datasets import load_dataset
    from pathlib import Path
    C = cfg(); c = C["text"]; client = anthropic.Anthropic()
    root = Path(C["raw"]["human_text_root"])   # manual download, outside the repo
    files = sorted([*root.rglob("*.parquet"), *root.rglob("*.csv")])
    assert files, f"No parquet/csv under {root} - download the human corpus manually (see eval/DATA.md)."
    kind = "parquet" if files[0].suffix == ".parquet" else "csv"
    ds = load_dataset(kind, data_files=[str(f) for f in files], split="train").shuffle(seed=c["seed"])
    rows, n = [], c["n_per_cell"]
    def llm(prompt):
        r = client.messages.create(model=c["llm_model"], max_tokens=900, messages=[{"role": "user", "content": prompt}])
        return r.content[0].text.strip()
    it = iter(ds)
    for length, (lo, hi) in {"short": c["short_words"], "long": c["long_words"]}.items():
        got = 0
        while got < n:
            ex = next(it)
            h = trim(ex["article"].split(" -- ", 1)[-1], lo, hi)
            if not h: continue
            got += 1; k = f"{length}_{got:03d}"
            rows.append(dict(id=f"txt_human_{k}", text=h, label="human", length=length, variant="clean",
                             source="CNN/DailyMail (local copy)", generator="human", parent_id=""))
            g = llm(f"Write an original piece of about {(lo + hi) // 2} words in the style of a news/web article on this topic: "
                    f"{ex['highlights'].replace(chr(10), ' ')}\nOutput only the text.")
            rows.append(dict(id=f"txt_llm_{k}", text=g, label="llm", length=length, variant="clean",
                             source=c["llm_model"], generator=c["llm_model"], parent_id=""))
            p = llm("Paraphrase the following text thoroughly: change wording and sentence structure, keep meaning and length. "
                    f"Output only the text.\n\n{g}")
            rows.append(dict(id=f"txt_llmpara_{k}", text=p, label="llm", length=length, variant="paraphrased",
                             source=c["llm_model"], generator=c["llm_model"], parent_id=f"txt_llm_{k}"))
    out = ROOT / c["manifest"]; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    print(f"{len(rows)} text rows -> {out}")

if __name__ == "__main__":
    main()
