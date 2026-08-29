# LLM Pricing Pipeline Requirements

Spec: `llm-pricing-pipeline`  
Status: requirements-approved  
Created: 2026-08-29  
Brainstorm: `./brainstorm.md`

## Overview

A single source of truth for LLM pricing. `fetch_pricing.py` fetches pricing on demand from two external sources (OpenRouter models API, LiteLLM raw JSON), merges them with a local hand-maintained truth layer (`overrides.json`) by strict precedence, and emits a merged cache file (`cache/pricing.json`) carrying freshness metadata. Any agent can read current pricing at decision time without re-fetching; on network failure the pipeline serves stale cache rather than blocking. Consumer wiring (Hermes, Pi, `llm-cost-estimator` read paths) is explicitly a later spec.

## Scope

### In Scope

- `fetch_pricing.py` — on-demand fetch → merge → emit CLI, with a TTL gate, stale-fallback, and tiered exit codes.
- `overrides.json` — layer-1 truth (highest precedence); seeded from `~/llm-cost-estimator/data/pricing.json`.
- `cache/pricing.json` — the emitted merged output schema with freshness metadata.
- Hermetic tests — merge precedence, TTL logic, stale-fallback path, and schema validation (mock source fetches; never hit the network).
- Stdlib-only Python 3.9+ with a minimal CLI.

### Out of Scope

- Wiring consumers to the merged cache (`llm-cost-estimator`, Hermes/Pi read paths) — a later spec.
- Hugging Face as a pricing source (HF is excluded from the automated path; manual reference only).
- Cron / keep-warm scheduling, UI, and any shared `~/.hermes/data/` path decision (revisit at consumer-wiring).
- Authentication into OpenRouter / LiteLLM (both sources are public, no-auth).

## User Stories

- As a **Hermes agent**, I want to read current, trustworthy pricing at decision time, so that cost estimates reflect reality.
- As a **Pi agent**, I want to read `cache/pricing.json` directly (or run the script when staleness matters), so that I don't re-fetch pricing myself.
- As a **human maintainer**, I want a hand-maintained overrides layer that always wins, so that negotiated/vendor-specific prices and tokenizer/fallback mappings stay correct.
- As an **engineer**, I want the pipeline to serve stale data on network failure rather than erroring, so that consumers still get a usable answer offline.
- As a **testing/CI engineer**, I want hermetic tests against mocked sources, so that the suite runs deterministically without network access.

## Functional Requirements

Use stable IDs and testable EARS-style statements.

- **FR-001**: WHEN `fetch_pricing.py` is invoked, THE system SHALL load `overrides.json` and emit `cache/pricing.json` containing a `models` map resolved by precedence overrides > LiteLLM > OpenRouter.
- **FR-002**: IF the existing cache is fresher than the configured TTL, THE system SHALL return the cached models with zero network calls.
- **FR-003**: IF the existing cache is stale or missing, THE system SHALL fetch the OpenRouter models API and the LiteLLM raw JSON, then merge and write the cache.
- **FR-004**: IF a source fetch fails AND a stale cache exists, THE system SHALL serve the stale cache and mark it stale, exiting with code 1.
- **FR-005**: IF a source fetch fails AND no usable cache exists, THE system SHALL emit no usable pricing and exit with code 2.
- **FR-006**: THE system SHALL write freshness metadata (`fetched_at`, `ttl_hours`) into the emitted JSON so consumers can judge staleness without extra calls.
- **FR-007**: THE system SHALL apply merge precedence overrides > LiteLLM > OpenRouter, where a matching model ID in a higher-precedence layer SHALL override price and tokenizer fields from lower layers.
- **FR-008**: THE system SHALL expose an explicit freshness state (`fresh` vs `stale`) in the emitted output.
- **FR-009**: THE system SHALL treat each `overrides.json` entry as the source of truth for tokenizer/fallback mapping AND price for that model ID.
- **FR-010**: THE system SHALL accept an optional `--force` flag to bypass the TTL gate and an optional `--ttl-hours` value; when absent it SHALL use the default TTL of 24 hours.

## Non-Functional Requirements

- **NFR-001**: THE system SHALL run on stdlib-only Python 3.9+ with no third-party dependencies (`urllib.request`, `json`, `unittest`).
- **NFR-002**: THE system SHALL keep all source fetches injectable/mockable, and the default test suite SHALL not require network access.
- **NFR-003**: THE system SHALL complete a cache-hit run with no network I/O, and SHALL return exit code 0 for a freshly served cache.
- **NFR-004**: THE system SHALL return deterministic exit codes (0 fresh, 1 stale, 2 no usable cache) that agents can branch on.
- **NFR-005**: THE system SHALL keep emitted model entries schema-compatible with `llm-cost-estimator`'s pricing expectations: non-negative `in`/`out` values and a `tokenizer` key present.

## Acceptance Criteria

- [ ] **FR-001/FR-006**: Running the pipeline with a stale/missing cache fetches both sources and writes a cache with current `fetched_at`, `ttl_hours`, and precedence-resolved `models`.
- [ ] **FR-002/FR-003**: Running the pipeline within TTL returns cached models with zero network calls (verified by a mocked/patched fetcher that asserts no fetch).
- [ ] **FR-004**: With a failing source and an existing cache, the pipeline serves the cache, marks it stale, and exits 1.
- [ ] **FR-005**: With a failing source and no cache, the pipeline exits 2 and emits no usable pricing.
- [ ] **FR-007/FR-009**: For the same model ID present in multiple layers, overrides > LiteLLM > OpenRouter determines the resolved price/tokenizer.
- [ ] **NFR-005**: Each emitted model entry passes the validator: `in`/`out` are non-negative numbers and `tokenizer` is present.

## Edge Cases

- `overrides.json` is missing or empty → pipeline proceeds with the two external sources as the only layers.
- A source returns malformed / non-JSON / unexpected schema → treated as a source fetch failure (stale-fallback path, not a crash).
- A model ID exists in multiple layers → resolved strictly by precedence.
- Partial override (e.g. only `in` present) → omitted fields inherit from the next lower layer (see Resolved Decisions — deep merge).
- Model present in external sources but with no override-derived tokenizer → excluded from the emitted cache (no guessed tokenizer); add it to `overrides.json` to include it.
- Corrupt / truncated `cache/pricing.json` → treated as stale/missing (re-fetch), not crashed on.
- TTL boundary (cache exactly at TTL age) → defined as stale (must re-fetch).
- Network timeout / DNS failure on either source → individual source failure triggers stale-fallback; a single failing source must not mask an otherwise usable cache.
- Emitted schema fails validation (negative price, missing tokenizer) → emit a hard failure rather than a corrupt cache.

## Dependencies and Constraints

- OpenRouter `GET https://openrouter.ai/api/v1/models` — public, no-auth.
- LiteLLM `model_prices_and_context_window.json` — GitHub raw URL, community-maintained.
- Seed for `overrides.json` — `~/llm-cost-estimator/data/pricing.json`.
- Python 3.9+.
- No third-party packages; tests use `unittest`.

## Resolved Decisions (formerly Open Questions)

These were open at brainstorm; they are resolved here with explicit defaults so design has a fixed contract. They are assumptions, not requirement IDs — if design reveals a conflict, the decision reverts to an open question before design approval.

- **Partial-override merge semantics — deep merge (per-field, higher precedence wins).** An `overrides.json` entry may be partial (e.g. only `in`, or only `tokenizer`); fields it omits inherit from the next lower-precedence layer. This lets a maintainer override a single negotiated price without re-specifying a tokenizer, while any field explicitly set in overrides always wins.
- **Schema-drift defense — tolerant extraction + entry-level validation.** Source rows are read by known key lookups with fallbacks; a row that fails validation (non-negative `in`/`out`, `tokenizer` present) is skipped/flagged rather than crashing the whole source. Final emitted entries are validated before writing; a fully invalid result is a hard failure (exit 2), never a corrupt cache.
- **Keep-warm cron — out of scope for this spec.** The optional README keep-warm cron (which would call the same script daily to pre-heat) is deferred. This spec ships the on-demand TTL-gated path only; a cron wrapper, if added later, is a separate change.
- **Tokenizer source — overrides only; un-tokenized models are excluded (accepted).** OpenRouter/LiteLLM carry prices, not tokenizer specs. Only models whose `tokenizer` is resolvable from the overrides layer (honoring deep-merge inheritance) are emitted; a model with no resolvable `tokenizer` is omitted rather than emitted with a guessed tokenizer. This preserves cost accuracy and matches the README's "overrides guard every number that reaches the estimator." To include an external model, add its tokenizer to `overrides.json`.

