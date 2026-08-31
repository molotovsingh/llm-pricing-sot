#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# Fast pre-check (<1s): syntax errors fail the run before any timing.
python3 -m py_compile fetch_pricing.py

# Workload data: cache/ is gitignored and absent in this worktree.
# Copy verbatim from the primary checkout — the workload must be identical
# every run (faster-but-smaller-workload = broken, not faster).
rsync -a --delete ~/llm/llm-pricing-sot/cache/ cache/

python3 - <<'PYEOF'
import hashlib, json, statistics, subprocess, sys, time

CMD = ["python3", "fetch_pricing.py", "query", "price", "gpt-4o", "--offline"]
GOLDEN = "4f3eb525c95c5287a6579c12b1f495c0c06ab939180fc272ea5bc0607eea8b4a"

# Workload integrity: exit code + output sha + pinned model count.
out = subprocess.run(CMD, capture_output=True, text=True)
if out.returncode != 0:
    print(f"CHECK query_exit_code={out.returncode} stderr={out.stderr[:200]}")
    sys.exit(1)
sha = hashlib.sha256(out.stdout.encode()).hexdigest()
models = len(json.load(open("cache/pricing.json"))["models"])

# Warmup (OS file caches) — never the baseline.
for _ in range(3):
    subprocess.run(CMD, capture_output=True)

ts = []
for _ in range(15):
    t0 = time.perf_counter()
    subprocess.run(CMD, capture_output=True)
    ts.append((time.perf_counter() - t0) * 1000)

med = statistics.median(ts)
p90 = sorted(ts)[int(len(ts) * 0.9) - 1]
print(f"METRIC cold_start_ms={med:.2f}")
print(f"METRIC p90_ms={p90:.2f}")
print(f"METRIC min_ms={min(ts):.2f}")
print(f"METRIC spread_ms={max(ts) - min(ts):.2f}")
print(f"METRIC models={models}")
print(f"METRIC sha_ok={1 if sha == GOLDEN else 0}")
if sha != GOLDEN or models != 9:
    print("WORKLOAD PIN BROKEN — output or workload changed")
    sys.exit(1)
PYEOF