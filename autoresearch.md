# Autoresearch: reduce offline-query cold-start of fetch_pricing.py

## Objective

Cut the cold-start wall time of the agent-facing offline pricing query
`python3 fetch_pricing.py query price gpt-4o --offline` (baseline median ~47ms)
without touching any contract semantics. Dominant mechanism (profiled
2026-09 with `python -X importtime`, cold): module import tree ~23ms, of
which `urllib.request` ≈ 14.0ms and `tempfile` ≈ 6.3ms — both used at
exactly two call sites (`_default_fetcher` network fetch, `_write_json_atomic`
cache write) that the offline read path never executes. Interpreter floor is
~14.6ms and NOT addressable.

## Metrics

- **Primary**: `cold_start_ms` (ms, lower is better) — median of 15 cold
  subprocess reps after 3 warmup reps, measured inside `autoresearch.sh`.
- **Target**: ≤ 32ms (expected win ~15ms from deferring the two imports;
  prototype measured 31.8ms in /tmp). Stop honestly when hit.
- **Secondary (workload pins, must stay constant)**: `models=9` (cache model
  count), `sha_ok=1` (query output sha256 equals golden
  `4f3eb525c95c5287a6579c12b1f495c0c06ab939180fc272ea5bc0607eea8b4a`).
  Faster-but-smaller-workload = broken, not faster.
- **Noise**: baseline block-median spread was 4.1ms (stdev 1.97ms) in
  discovery. Wins are judged **medians-only** (gate label: borderline 3.7×
  spread / 7.6× stdev) — never a single lucky run.

## How to Run

`bash autoresearch.sh` — syncs `cache/` from the primary checkout (it is
gitignored, so absent in this worktree), syntax-checks, warms up 3×, then
emits `METRIC cold_start_ms=... p90_ms=... min_ms=... spread_ms=... models=... sha_ok=...`.

## Files in Scope

- `fetch_pricing.py` — the only code file experiments may modify.
- `autoresearch.sh`, `autoresearch.checks.sh`, `autoresearch.md`, `autoresearch.ideas.md` — instruments.

## Off Limits

- Contract semantics and their in-file sources: exit codes (FR-008), cache
  envelope schema, trust rule. `tests/test_contract_drift.py` enforces these
  against this very file — any drift fails checks.
- `_normalize_*` / merge logic, TTL/freshness behavior, query output shape.
- `tests/`, `specs/`, `README.md`, `skills/`, `overrides.json`, `agent_review/`.
- The instruments: `autoresearch.sh` may NOT be edited mid-session (moving
  ruler measures nothing). If instrumentation is genuinely wrong, stop and
  say so.

## Constraints

- No new dependencies; stdlib only.
- Full unittest suite green (`autoresearch.checks.sh` runs it automatically).
- Query output sha256 must equal the golden value above.
- Workload data (`cache/`) is copied verbatim from the primary checkout each
  run; never regenerate it inside experiments.

## Environment parity (annotate every log)

Measurements run in the worktree `autoresearch/<id>/` (its `.git` is a file).
No repo traversal is on the query path (`_load_discovery` reads one JSON
file), so unlike the drift-scan session there is no worktree-hides-cost trap
here; the import win is filesystem-location independent. Machine: macOS,
python3 = Homebrew 3.14.7.

## What's Been Tried

Discovery (2026-09, pre-session):

- Cold-start decomposition: 46.7ms median = 14.6 floor + ~19 imports + ~2 logic.
- Import tree: urllib.request 14.0ms, tempfile 6.3ms of 23.0ms total (importtime, cold).
- Prototype (deferred both imports to call sites in a /tmp copy): 31.8ms
  median, blocks 31.6–33.8 — no overlap with baseline distribution
  (46.2–50.3). Offline queries answered correctly.
- Warm query logic is ~1.9ms (`_load_discovery` JSON decode 1.28ms +
  argparse 0.54ms) — immaterial, not a target.
- Rejected: test-suite speed (no leverage, no CI); refresh/network path
  (network-judged, verifiability 0).