# LLM Pricing Pipeline Brainstorm

Spec: `llm-pricing-pipeline`  
Status: brainstorm-complete  
Created: 2026-08-29

## User Intent

## Brainstorm Summary

- **User intent:** Build the single source of truth for LLM pricing as a small, agent-readable Python pipeline that fetches pricing *on demand*, merges it with a local truth layer, and emits a cache file with freshness metadata — so any agent can read current pricing at decision time without re-fetching.
- **Target users/stakeholders:** Hermes agents, Pi (read the cache), `llm-cost-estimator` (final validation gate); humans who hand-maintain `overrides.json`.
- **Problem & desired outcome:** Hand-maintained price tables drift from reality. Outcome: running `fetch_pricing.py` yields `cache/pricing.json` with fresh prices + `fetched_at`/`source`/`ttl_hours` metadata, and never blocks on the network (serves stale + flag on failure).
- **In scope:** `fetch_pricing.py` (fetch → merge → emit, TTL gate, stale fallback, tiered exit codes), `overrides.json` (layer-1 seed), `cache/pricing.json` schema, hermetic tests (merge precedence, TTL, stale path, schema). Stdlib-only, minimal CLI. Consumer wiring is explicitly a LATER spec.
- **Out of scope:** Consumer wiring (llm-cost-estimator, Hermes/Pi read paths) — a later spec. Hugging Face source (HF excluded). No cron/keep-warm, no UI, no shared `~/.hermes/data/` path decision (revisit at consumer-wiring).
- **Constraints/risks:** OpenRouter price is baseline, not what we pay → overrides guard. LiteLLM is community-maintained → may have stale rows → overrides guard. OpenRouter/LiteLLM carry no tokenizer specs → tokenizer/fallback stays in overrides. External source schemas can drift → defensive parsing. Network failures → stale-fallback.
- **Proposed approach:** On-demand with TTL-gated cache. Merge precedence **overrides > LiteLLM > OpenRouter**. Emit cache + freshness metadata; stale flag on failure. Tiered exit codes: `0` fresh / `1` stale / `2` no usable cache.
- **Assumptions (decided):** Stdlib-only Python 3.9+ (`urllib.request` + `json` + `unittest`); repo-local `cache/pricing.json`; default TTL 24h (overridable via env/flag later); LiteLLM shares the same TTL gate as OpenRouter; `overrides.json` seeded from `~/llm-cost-estimator/data/pricing.json`.
- **Public API signature:** CLI `python fetch_pricing.py [--force] [--ttl-hours H]` (defaults baked in; flags nicer-to-have). On-disk contract: reads `overrides.json`, writes `cache/pricing.json` shaped `{fetched_at, ttl_hours, models:{<id>:{in,out,tokenizer,fallback,source,alternatives?}}}`. Exit codes 0 fresh / 1 stale / 2 no usable cache. Internal helpers: `load_overrides()`, `fetch_openrouter()`, `fetch_litellm()`, `merge(layers)`, `emit(cache_payload)`. No server/query API — CLI + file contract only.
- **Success criteria / acceptance tests:** (1) TTL exceeded → both sources fetched, cache written with fresh `fetched_at` and precedence-resolved models. (2) Within TTL → cache read with zero network calls. (3) Fetch fails + stale cache → served cache flagged stale, exit code 1. (4) Fetch fails + no cache → exit code 2, no partial output. (5) Overrides beat LiteLLM beat OpenRouter in merge. (6) Emitted JSON passes validator (non-negative in/out, tokenizer key present).
- **Remaining doubts:** (a) partial-override merge semantics (can a PRICE-only override inherit tokenizer from below?), (b) resilience to external schema drift, (c) tests stay hermetic (mock the two source fetches, never hit network).
- **Suggested spec slug:** `llm-pricing-pipeline`.

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
