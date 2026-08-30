# Implementation Plan: Pricing Endpoints Upgrade

**Branch**: `002-pricing-endpoints` | **Date**: 2026-08-30 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-pricing-endpoints/spec.md`

## Summary

Replace the heuristic cheapest-host variant scan with OpenRouter's per-provider
`/endpoints` API as the primary source (provider name, quantization, cache-read
price), demote LiteLLM to fallback/cross-check for vendor-direct models, capture
input-cache-read/write prices in the OpenRouter discovery baseline, and update
README/skill documentation (including the MCP role-split note). Everything stays
on the existing stdlib-only CLI + TTL-gated JSON cache architecture.

## Technical Context

**Language/Version**: Python 3.9+ (stdlib only)
**Primary Dependencies**: none (stdlib: `argparse`, `json`, `urllib.request`, `unittest`)
**Storage**: JSON files (`cache/pricing.json`, `cache/discovery.json`, new `cache/endpoints/`)
**Testing**: `unittest`, hermetic (fake fetchers, no network)
**Target Platform**: any shell where Python 3.9+ runs (macOS/Linux)
**Project Type**: CLI
**Performance Goals**: cached cheapest queries answer in well under 2s; first query per model
bounds network work to one endpoints call
**Constraints**: `--offline` guarantees zero network; JSON to stdout; exit codes 0/1/2; no new
dependencies; OpenRouter MCP never used by the pipeline
**Scale/Scope**: on-demand endpoints calls for queried models only (not the whole catalog);
endpoint snapshots cached per slug

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] Stdlib-only: endpoints fetches use `urllib.request`; no third-party deps
- [x] File + CLI contract: same `query` surface; JSON to stdout; exit codes 0/1/2
- [x] SOT precedence honored: endpoints data is baseline (never authoritative); LiteLLM demoted
      to fallback, never mixed into the truth layer
- [x] On-demand TTL gate: endpoints fetched per query, cached under the same 24h TTL; `--offline`
      serves cache only
- [x] Hermetic tests: fake endpoint fetchers; zero network in the suite

## Project Structure

### Documentation (this feature)

```text
specs/002-pricing-endpoints/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (endpoints query contract delta)
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
fetch_pricing.py            # endpoints fetcher + slug resolution + cheapest rewrite
tests/test_fetch_pricing.py # hermetic tests (fake endpoints fetcher)
cache/endpoints/            # generated (gitignored): per-slug endpoint snapshots
skills/llm-pricing/SKILL.md # MCP role-split note (repo copy + live install)
README.md                   # sources table role update
```

**Structure Decision**: Same single-project CLI. Endpoint snapshots live under
`cache/endpoints/<slug>.json` (gitignored, regenerated). No new modules.

## Complexity Tracking

No violations — no entry required.

## Post-Design Constitution Re-check

*GATE: re-checked after Phase 1 design — all five gates still pass.*

- [x] Stdlib-only — endpoints fetches use `urllib.request`; no new deps
- [x] File + CLI contract — same query surface; JSON to stdout; exit codes 0/1/2
- [x] SOT precedence — endpoints data is baseline only; LiteLLM demoted to fallback, never mixed into truth
- [x] On-demand TTL gate — per-model endpoint snapshots under the 24h TTL; `--offline` serves cache only
- [x] Hermetic tests — fake endpoint fetchers; zero network in the suite

Note: `update-agent-context.sh` remains broken on macOS bash 3.2 (empty `args[@]`
under `set -u` in `common.sh` `run_hook`); skipped as before — this feature adds no
new technology to register.
