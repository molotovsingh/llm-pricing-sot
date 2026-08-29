# Consumer Wiring Brainstorm

Spec: `consumer-wiring`  
Status: brainstorm-complete  
Created: 2026-08-29

## User Intent

## Brainstorm Summary

- **User intent:** Make the pricing cache usable by wiring the three consumers to read it, so they stop relying on stale/hand-maintained pricing.
- **Target users/stakeholders:** `llm-cost-estimator` (reads the cache), Hermes agents, Pi (reads via bash/read tools), plus the human maintaining the pipeline/overrides.
- **Problem & desired outcome:** The pipeline emits `cache/pricing.json`, but nothing consumes it. Outcome: `llm-cost-estimator` reads the merged cache (auto-refreshing when stale), Hermes/Pi have documented read paths — all three use the same fresh pricing.
- **In scope:** documented read/refresh contract; change `llm-cost-estimator` to read `cache/pricing.json` and run `fetch_pricing.py` when stale/missing; Hermes/Pi read instructions; repo-local `cache/pricing.json`.
- **Out of scope:** any HTTP API / FastAPI / daemon; a shared `~/.hermes/data/` path (rejected — repo-local); changing what the pipeline emits (existing approved pipeline spec); re-scoping pipeline merge/TTL logic.
- **Constraints/risks:** repo-local cache → consumers must know the repo path (fragile if repo moves, accepted); auto-refresh means consumers may spawn a subprocess → needs a defined invocation + exit-code contract; `llm-cost-estimator` is a second repo; staleness judgment falls on the consumer (must read `freshness`/`fetched_at`).
- **Proposed approach:** keep the file contract; document a shared read/refresh convention; wire `llm-cost-estimator` (read cached `models`; if `freshness: stale`/missing, shell out to `fetch_pricing.py` then re-read); add Hermes/Pi read instructions (staleness-aware, auto-refresh allowed).
- **Assumptions:** `llm-cost-estimator` lives at `~/llm-cost-estimator` and reads `data/pricing.json`; consumers can shell out to the python script; default TTL 24h (from cache) is the refresh trigger; no stricter per-consumer staleness floor by default.
- **Public API signature / contract:** Read contract = consumers read `<repo>/cache/pricing.json` shaped `{fetched_at, ttl_hours, freshness, models:{<id>:{in,out,tokenizer,source,...}}}`. Refresh via `python fetch_pricing.py [--force] [--ttl-hours H]`, exit codes 0 fresh / 1 stale / 2 no cache. `llm-cost-estimator` wiring: load `models` from the cache; if unavailable/stale, run the script then re-read; fall back to last-known data if the cache is absent. Hermes/Pi: documented stale-aware read steps. No server/query API — file + subprocess contract only (N/A for a query API).
- **Success criteria / acceptance tests:** (1) `llm-cost-estimator` reads prices from `cache/pricing.json`, not `data/pricing.json`. (2) With a stale/missing cache, invoking `llm-cost-estimator` triggers `fetch_pricing.py` and then produces fresh prices. (3) `llm-cost-estimator` honors script exit codes (0 fresh, 1 stale-with-warning, 2 no-cache) and degrades gracefully. (4) Hermes/Pi read instructions are present and stale-aware. (5) No HTTP API/server introduced (file-based only).
- **Remaining doubts:** (a) exact `llm-cost-estimator` internals (price loading, tokenizer expectations) — inspect during requirements/design; (b) whether cost-critical runs need a shorter stale-floor; (c) whether Hermes/Pi docs ship as a README section or a separate file/skill.
- **Suggested spec slug:** `consumer-wiring`.

## Clarifying Questions Asked

- TODO: Record key questions asked one at a time and the user's answers.

## Proposed Approach

- TODO: Summarize the recommended direction before requirements are drafted.

## Assumptions

- TODO: List assumptions accepted during brainstorming.

## Remaining Doubts

- TODO: List unresolved questions, if any, and whether they block requirements.

## Decision

- [ ] User approved creating the spec skeleton and drafting requirements.
