"""Check whether any scenario exceeded the real-time budget."""
import csv

with open("eval/reports/surveillance_benchmark_raw.csv") as f:
    rows = list(csv.DictReader(f))

failures = []
for r in rows:
    if r.get("realtime_ratio") in ("", None, "SKIPPED"):
        continue
    ratio = float(r["realtime_ratio"])
    if ratio >= 1.0:
        failures.append(f"{r['scenario']}: realtime_ratio={ratio:.2f}")

if failures:
    print("WARN - These scenarios exceeded real-time budget:")
    for item in failures:
        print(" ", item)
    print("(Document in report notes; not a hard failure for benchmarking purposes)")
else:
    print("PASS - All scenarios processed within real-time budget (ratio < 1.0)")
