# Implementation Plan: Pricing Query

**Branch**: `001-pricing-query` | **Date**: 2026-08-29 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-pricing-query/spec.md`

## Summary

Add a `query` subcommand tree to the existing `fetch_pricing.py` CLI that answers
typical pricing queries (price, cheapest host, list, freshness) as JSON on stdout,
with auto-refresh-on-stale, an `--offline` mode that guarantees zero network, and a
discovery sidecar (`cache/discovery.json`) so fallback/cheapest queries stay TTL-gated.
Ship a global agent skill (`llm-pricing`) so Pi/Hermes discover the tool.

## Technical Context

**Language/Version**: Python 3.9+ (stdlib only)
**Primary Dependencies**: none (stdlib: `argparse`, `json`, `urllib.request`, `unittest`)
**Storage**: JSON files on disk (`cache/pricing.json`, `cache/discovery.json`, `overrides.json`)
**Testing**: `unittest`, hermetic (fake fetchers, no network)
**Target Platform**: any shell where Python 3.9+ runs (macOS/Linux)
**Project Type**: CLI
**Performance Goals**: fresh-cache query answers in well under 2s (file reads; no network)
**Constraints**: `--offline` guarantees zero network; JSON to stdout, notes to stderr; deterministic exit codes 0/1/2; no new dependencies
**Scale/Scope**: ~9 authoritative models + ~3.4k discovery entries; single machine, agent + human users

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] Stdlib-only: no third-party deps in the pipeline (Python 3.9+; urllib/json/argparse/unittest)
- [x] File + CLI contract: no server/daemon/MCP; JSON to stdout, errors to stderr; exit codes 0/1/2 preserved
- [x] SOT precedence honored: overrides > LiteLLM > OpenRouter; no guessed tokenizers; discovery data labeled `baseline: true`
- [x] On-demand TTL gate preserved: fresh cache = zero network; stale-fallback on failure
- [x] Hermetic tests: suite never hits the network; deterministic exit codes asserted

## Project Structure

### Documentation (this feature)

```text
specs/001-pricing-query/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (query CLI contract)
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
fetch_pricing.py          # existing pipeline; extended with `query` subcommands
tests/
└── test_fetch_pricing.py # existing hermetic suite; extended with query tests
skills/
└── llm-pricing/
    └── SKILL.md          # versioned copy of the agent discovery skill
cache/                    # generated (gitignored): pricing.json + discovery.json
```

**Structure Decision**: Single-project CLI. The query surface extends the existing
module (same SOT core, same exit-code contract). The live agent skill installs to
`~/.pi/agent/skills/llm-pricing/` (global discovery); the repo keeps a copy under
`skills/llm-pricing/` for version control.

## Post-Design Constitution Re-check

*GATE: re-checked after Phase 1 design — all five gates still pass.*

- [x] Stdlib-only — the query surface adds no dependencies
- [x] File + CLI contract — queries print JSON to stdout; exit codes 0/1/2 preserved
- [x] SOT precedence — cache-first answers; discovery answers labeled `baseline: true`
- [x] On-demand TTL gate — auto-refresh only when stale; `--offline` guarantees zero network
- [x] Hermetic tests — query tests inject fake fetchers

## Complexity Tracking

No violations — no entry required.
