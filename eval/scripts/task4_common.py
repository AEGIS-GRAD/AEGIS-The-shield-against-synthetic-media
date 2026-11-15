import csv, hashlib, random
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]

def cfg():
    return yaml.safe_load((ROOT / "eval/config/data_paths.yaml").read_text())["task4"]

def sha256(p, n=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(n):
            h.update(b)
    return h.hexdigest()

def write_csv(path, rows, fields):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def read_csv(path):
    with open(ROOT / path) as f:
        return list(csv.DictReader(f))

def rng(seed):
    return random.Random(seed)
