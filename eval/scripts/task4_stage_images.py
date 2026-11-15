"""Stage the image eval set: real vs generated (clean + JPEG/resize variants) + OpenFake Reddit split.
  python eval/scripts/task4_stage_images.py --list-generators
  python eval/scripts/task4_stage_images.py
"""
import argparse, collections
from pathlib import Path
from task4_common import ROOT, cfg, write_csv, sha256

FIELDS = ["sample_path", "modality", "true_label", "id", "path", "label", "generator", "variant", "parent_id", "source", "license", "subset", "sha256"]
LIC = "OpenFake - check per-subset terms (non-commercial subsets exist); see DATA.md"

def stream(c, root):
    """Local (manually downloaded) parquet snapshot; nothing is fetched from the network."""
    from datasets import load_dataset
    files = sorted(Path(root).rglob("*.parquet"))
    assert files, f"No parquet files under {root} - download the dataset manually first (see eval/DATA.md)."
    return load_dataset("parquet", data_files=[str(f) for f in files], split="train", streaming=True).shuffle(seed=c["seed"], buffer_size=2000)

def norm_label(v):
    return "real" if str(v).lower() in ("real", "0", "authentic") else "fake"

def save(img, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, "PNG")

def variants(img, base):
    img = img.convert("RGB"); out = {}
    for name in ("jpeg75", "jpeg50", "resize0.5"):
        p = base.with_name(f"{base.stem}__{name}" + (".jpg" if name.startswith("jpeg") else ".png"))
        if name == "resize0.5":
            img.resize((max(1, img.width // 2), max(1, img.height // 2))).save(p, "PNG")
        else:
            img.save(p, "JPEG", quality=int(name[4:]))
        out[name] = p
    return out

def main():
    C = cfg(); c = C["image"]; RAW = C["raw"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-generators", action="store_true")
    ap.add_argument("--max-scan", type=int, default=20000)
    a = ap.parse_args()
    F = c["fields"]
    if a.list_generators:
        cnt = collections.Counter()
        for i, r in enumerate(stream(c, RAW["openfake_root"])):
            if i >= a.max_scan: break
            cnt[(norm_label(r[F["label"]]), r.get(F["generator"]))] += 1
        for k, v in cnt.most_common(): print(v, k)
        print("\nPick whole generators for image.eval_generators; keep them OUT of fine-tuning.")
        return
    gens = c["eval_generators"]
    assert gens, "Set image.eval_generators first (run --list-generators)."
    out = ROOT / c["eval_dir"]; rows = []
    def add(r, i, subset):
        lab = norm_label(r[F["label"]]); gen = "real" if lab == "real" else str(r[F["generator"]])
        pid = f"img_{subset}_{lab}_{i:05d}"; p = out / subset / lab / f"{pid}.png"
        save(r[F["image"]], p)
        row = dict(sample_path=p.relative_to(ROOT).as_posix(), modality="image", true_label=lab, id=pid, path=p.relative_to(ROOT).as_posix(), label=lab, generator=gen, variant="clean", parent_id="",
                   source="OpenFake (local snapshot)", license=LIC, subset=subset, sha256=sha256(p))
        rows.append(row)
        return row, r[F["image"]], p
    per_gen = -(-c["n_per_class"] // len(gens)); quota = collections.Counter(); nreal = 0; parents = []
    for i, r in enumerate(stream(c, RAW["openfake_root"])):
        lab = norm_label(r[F["label"]]); g = str(r[F["generator"]])
        if lab == "real" and nreal < c["n_per_class"]:
            nreal += 1; parents.append(add(r, i, "main"))
        elif lab == "fake" and g in gens and quota[g] < per_gen:
            quota[g] += 1; parents.append(add(r, i, "main"))
        if nreal >= c["n_per_class"] and all(quota[x] >= per_gen for x in gens): break
    done = collections.Counter()
    for row, img, p in parents:
        if done[row["label"]] >= c["n_variants_per_class"]: continue
        done[row["label"]] += 1
        for name, vp in variants(img, p).items():
            rows.append(dict(row, id=f"{row['id']}__{name}", sample_path=vp.relative_to(ROOT).as_posix(), path=vp.relative_to(ROOT).as_posix(), variant=name,
                             parent_id=row["id"], sha256=sha256(vp)))
    k = collections.Counter()
    try:
        for j, r in enumerate(stream(c, RAW["openfake_reddit_root"])):
            lab = norm_label(r[F["label"]])
            if k[lab] < c["reddit_n_per_class"]:
                k[lab] += 1; add(r, j, "reddit")
            if all(k[x] >= c["reddit_n_per_class"] for x in ("real", "fake")): break
    except Exception as e:
        print("WARN: reddit split not staged:", e)
    write_csv(c["manifest"], rows, FIELDS)
    print(f"{len(rows)} image rows -> {c['manifest']}")

if __name__ == "__main__":
    main()
