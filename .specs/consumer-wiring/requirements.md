# Consumer Wiring Requirements

Spec: `consumer-wiring`  
Status: requirements-approved  
Created: 2026-08-29  
Brainstorm: `./brainstorm.md`

## Overview

The pricing pipeline already emits `cache/pricing.json`. This spec wires the three consumers to it so they stop using stale/hand-maintained pricing. It documents a shared read/refresh contract, changes `llm-cost-estimator` to read the merged cache (auto-refreshing via `fetch_pricing.py` when stale/missing), and adds stale-aware read instructions for Hermes and Pi. The cache stays repo-local (`cache/pricing.json`), and the whole approach is file-based — no HTTP API or daemon.

## Scope

### In Scope

- A documented read/refresh contract (cache location, freshness fields, auto-refresh rule, exit-code handling).
- Change `llm-cost-estimator` to read `models` from `cache/pricing.json` and invoke `fetch_pricing.py` when the cache is stale/missing.
- Configurable path to the pricing-cache repo (so the consumer doesn't hard-code a repo location).
- Hermes and Pi stale-aware read instructions.
- Repo-local cache path (`cache/pricing.json`).

### Out of Scope

- Any HTTP API / FastAPI service / daemon.
- A shared `~/.hermes/data/` path (rejected in favor of repo-local).
- Changing what the pipeline emits or its merge/TTL logic (that's the approved `llm-pricing-pipeline` spec).
- Porting the pipeline core into the consumer; the consumer shells out to the existing script.

## User Stories

- As a **`llm-cost-estimator` user**, I want the estimator to use fresh pricing from the single source of truth and refresh it when stale, so my cost estimates reflect reality without me maintaining a second table.
- As a **Hermes agent**, I want a documented way to read current pricing and detect staleness, so I can trust the cost I compute.
- As a **Pi agent**, I want the same read path, so I don't re-fetch pricing myself.
- As a **maintainer**, I want a single documented contract that all three consumers follow, so they stay in sync with the pipeline.

## Functional Requirements

Use stable IDs and testable EARS-style statements.

- **FR-001**: THE system SHALL document a read/refresh contract specifying the cache location (`cache/pricing.json`), its freshness fields (`fetched_at`, `ttl_hours`, `freshness`), and the auto-refresh rule.
- **FR-002**: THE `llm-cost-estimator` SHALL read model pricing from the `models` map of `cache/pricing.json`, not from its `data/pricing.json`.
- **FR-003**: IF the cache is missing or its `freshness` is `stale`, THE `llm-cost-estimator` SHALL invoke `fetch_pricing.py` and then re-read the cache.
- **FR-004**: THE `llm-cost-estimator` SHALL interpret `fetch_pricing.py` exit codes as: `0` fresh (proceed), `1` stale (warn but proceed), `2` no usable cache (handle as failure).
- **FR-005**: THE location of the pricing-cache repo (used to find the cache and to run the script) SHALL be configurable via an environment variable or CLI flag, with a documented default.
- **FR-006**: THE Hermes/Pi read instructions SHALL document how to read the cache, how to judge staleness from `freshness`/`fetched_at`, and MAY specify when to trigger a refresh.
- **FR-007**: IF the cache is absent and a refresh fails, THE `llm-cost-estimator` SHALL fail with a clear error rather than silently proceeding with missing pricing.
- **FR-008**: THE cache read SHALL expose staleness to the consumer (via `freshness` and `fetched_at`, not just prices).

## Non-Functional Requirements

- **NFR-001**: THE wiring SHALL introduce no HTTP API, server, or daemon (file + subprocess only).
- **NFR-002**: THE wiring SHALL NOT modify the pipeline CLI contract or add third-party deps to the pipeline (it stays stdlib-only).
- **NFR-003**: Consumer staleness judgment SHALL be deterministic and based solely on `freshness`/`fetched_at`/`ttl_hours`.
- **NFR-004**: THE wiring for `llm-cost-estimator` SHALL fail loudly (clear message, non-zero exit) on an unrecoverable read/refresh error rather than returning wrong pricing.

## Acceptance Criteria

- [ ] **FR-002**: With a configured path, `llm-cost-estimator` loads prices from `cache/pricing.json`'s `models`, and no longer reads `data/pricing.json`.
- [ ] **FR-003**: With a stale/missing cache, invoking `llm-cost-estimator` triggers `fetch_pricing.py` and then reports fresh pricing.
- [ ] **FR-004**: `llm-cost-estimator` distinguishes exit code `0` (proceed), `1` (warn), and `2` (failure) and behaves accordingly.
- [ ] **FR-005**: Setting the cache-repo path env var changes where the consumer reads/runs; a documented default applies when unset.
- [ ] **FR-006**: Hermes/Pi read instructions are present and stale-aware.
- [ ] **FR-007**: If the cache is missing and the refresh returns exit code `2`, `llm-cost-estimator` fails with a clear error (no silent missing-pricing run).
- [ ] **NFR-001**: No API/server is introduced (verified by the absence of any server process/endpoint in the design).

## Edge Cases

- Cache file missing entirely → trigger refresh (FR-003); if refresh fails → clear error (FR-007).
- Cache `freshness: stale` → trigger refresh; if refresh returns `1` (still stale) → warn but proceed.
- Cache corrupt/unparseable → treat as missing (trigger refresh).
- Refresh subprocess fails to start (script not found / non-Python) → clear failure, no silent fallback.
- Cache-repo path not configured → use documented default; if the default is wrong → clear error.
- Model in cache missing a `tokenizer` → `llm-cost-estimator`'s existing validation rejects it (defensive; expected not to occur because the pipeline drops un-tokenized models).
- Two consumers refresh simultaneously → the pipeline regenerates the cache idempotently; no corruption (same file write).

## Dependencies and Constraints

- `llm-cost-estimator` repo at `~/llm-cost-estimator` — `load_pricing()` in `estimate_llm_cost.py` (currently defaults to `HERE/data/pricing.json`); its existing validation requires a `tokenizer` and finite non-negative `in`/`out`.
- Pipeline repo at `~/llm/llm-pricing-sot` — `fetch_pricing.py` (CLI) and `cache/pricing.json` (merged output).
- `fetch_pricing.py` exit codes: `0` fresh / `1` stale / `2` no usable cache.
- Consumers read cache via a configured path to the pipeline repo (env var or CLI flag); no hard-coded repo location.
- Python 3.9+; subprocess invocation of `virtualenv`/`python` assumed available to the consumer.

## Resolved Decisions (formerly Open Questions)

These were open at brainstorm; resolved here with explicit defaults so design has a fixed contract. They are assumptions, not requirement IDs — if design reveals a conflict, the decision reverts to an open question before design approval.

- **Cache-repo path config — env var `LLM_PRICING_SOT_DIR`.** Consumers reference the pipeline repo through this env var, which overrides a documented default (the known pipeline repo path). In `llm-cost-estimator`, a `--pricing-dir` CLI flag may also override it. Unset + wrong default → clear error (FR-007).
- **Hermes/Pi read instructions live in this repo's `README.md`.** A dedicated `### Consuming the cache` section documents the read path, staleness fields, and the auto-refresh rule — discoverable near the top of the SOT repo. (A separate skill file is deferred; a README section is sufficient for this spec.)
- **Staleness floor — the cache's default TTL (24h) is sufficient for all consumers in this spec.** No per-consumer shorter floor is required by default; a cost-critical floor (e.g. The Brief) is a possible later, non-blocking change.
