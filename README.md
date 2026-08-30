# llm-pricing-sot

Single source of truth for LLM pricing, shared by Hermes, Pi, and `llm-cost-estimator`.

**Status: pipeline built; consumer wiring documented.** `fetch_pricing.py`, `overrides.json`, and `cache/pricing.json` exist; the stdlib-only CLI fetches on demand, merges by precedence (overrides > LiteLLM > OpenRouter), and emits a TTL-gated cache with freshness metadata. Consumers are wired per the contract below.

## Problem

LLM pricing is a dynamic parameter. Hand-maintained price tables (`llm-cost-estimator/data/pricing.json` today) drift from reality. We want one refresh mechanism that keeps prices fresh, readable by both agent harnesses (Hermes, Pi) at decision time.

## Decision: on-demand with TTL-gated cache (no cron)

Pricing changes weekly-to-monthly. Fetching on a timer re-fetches for zero diff ~99% of the time. Instead:

```
agent needs cost → run fetch_pricing.py
  ├─ cache fresh (< TTL, default 24h)?  → read cache (zero network, instant)
  ├─ stale or missing?                   → fetch sources → merge → write cache
  └─ network fails?                      → serve stale cache + "STALE" flag
```

Freshness metadata rides **inside** the JSON (`fetched_at`, `source`, `ttl_hours`) so any consumer can judge staleness without extra calls.

Optional later upgrade: a keep-warm cron that calls the *same script* daily (pre-heats for scheduled pipelines; nothing else changes).

## Sources — three layers, merge precedence top-down

| Layer | Source | Role | Verified (2026-08-30) |
| :-- | :-- | :-- | :-- |
| 1. **Overrides** (truth) | Local `overrides.json` | What we actually pay: z.ai GLM direct, vendor list rates, negotiated prices, tokenizer mappings, optional `openrouter_slug` mappings | Existing `llm-cost-estimator/data/pricing.json` becomes this |
| 2. **Cheapest host** (baseline) | OpenRouter `GET /api/v1/models/{author}/{slug}/endpoints` (public, no auth) | Per-provider endpoint pricing: provider name, quantization, cache-read price. Primary source for `query cheapest` on OpenRouter-routed models | ✅ 17 endpoints for `moonshotai/kimi-k3` (Makora, DeepInfra, Morph, ...) |
| 3. **Catalog baseline** (discovery) | OpenRouter `GET /api/v1/models` | Canonical per-model price incl. cache-read/write + conditional pricing flag; slug resolution for the endpoints API | ✅ 396 models, all with pricing blocks |
| 4. **Fallback / cross-check** | LiteLLM `model_prices_and_context_window.json` (GitHub raw) | Vendor-direct pricing OpenRouter does not list (z.ai GLM official rates); demoted fallback for `query cheapest` | ✅ 3,365 entries |

**Hugging Face is NOT in the automated path.** Empirically tested: hub API (`/api/models/{id}`) carries no pricing, router API is auth-walled, model-card frontmatter has no `inference_providers` block (checked Kimi-K3, DeepSeek-V3, Qwen3.5). HF's provider-price tables on the website come from an internal endpoint with no public contract. HF = manual reference only.

### Caveats

- OpenRouter price ≠ what we pay unless we route via OpenRouter. It is baseline, not truth.
- LiteLLM DB is community-maintained — expect occasional stale rows. It is a fallback/cross-check, never the primary cheapest source. Overrides guard every number that reaches the estimator.
- OpenRouter/LiteLLM give prices, not tokenizer specs. Tokenizer/fallback mapping stays in the overrides layer.
- The OpenRouter MCP server is for **interactive** agent-time lookups only (credits, exact per-generation cost, provider latency); the unattended fetcher uses plain REST. OAuth + 7-day key expiry + spend cap make MCP unsuitable for the pipeline.

## Consumers

- **Hermes agents** — read the cache file (or run the script when staleness matters).
- **Pi** — same file via its bash/read tools. No Pi-specific integration needed.
- **llm-cost-estimator** — consumes the emitted pricing.json; its validation (non-negative in/out, tokenizer key present) stays as the final gate.

### Consuming the cache (read/refresh contract)

Every consumer reads the **same file**: `<repo>/cache/pricing.json` (repo-local).

**Schema you read:** `{ "fetched_at": "<ISO-8601 UTC>", "ttl_hours": 24, "freshness": "fresh", "models": { "<model_id>": { "in": <$/1M>, "out": <$/1M>, "tokenizer": "...", "fallback": "...", "source": "override" } } }`. Prices are USD per 1M tokens.

**Judge staleness** from `freshness` (`fresh` / `stale`), or recompute from `fetched_at` + `ttl_hours`. A cache is stale when `now - fetched_at >= ttl_hours`; missing/unparseable `fetched_at` is treated as stale.

**Auto-refresh rule:** if the cache is missing or stale, run `python fetch_pricing.py [--force] [--ttl-hours H]` then re-read. Exit codes: `0` = fresh (proceed), `1` = stale still served (warn but proceed), `2` = no usable cache (treat as a failure).

- **Hermes agents** — read the cache file; if `freshness: stale`, run the script (auto-refresh) then re-read. Do not necessarily re-fetch every turn.
- **Pi** — same file via its bash/read tools; same staleness rule. No Pi-specific integration needed.
- **llm-cost-estimator** — reads `models` from the cache (not its own `data/pricing.json`) and auto-refreshes when stale/missing, honoring the exit codes above; its validation (non-negative in/out, tokenizer present) stays the final gate. Point it at the repo with `LLM_PRICING_SOT_DIR` or `--pricing-dir`.

## File contract (realized)

```
llm-pricing-sot/
├── README.md                 # this file
├── overrides.json            # layer 1 — hand-maintained, highest precedence
├── cache/
│   └── pricing.json          # merged output: {fetched_at, ttl_hours, models: {...}}
├── fetch_pricing.py          # TBD — fetch → merge → emit (not built yet)
└── tests/                    # TBD
```

Merged model entry shape (planned, matches llm-cost-estimator's expectations):

```json
{
  "kimi-k3": {
    "in": 3.00, "out": 15.00,
    "tokenizer": "hf:moonshotai/Kimi-K3",
    "fallback": "tiktoken:o200k_base",
    "source": "override",
    "alternatives": [{"provider": "databricks", "in": 0.80, "out": 3.20}]
  }
}
```

## Build order (when this repo graduates from design to code)

1. `fetch_pricing.py` — two GETs (OpenRouter models API, LiteLLM raw JSON), merge with precedence overrides > LiteLLM > OpenRouter, emit cache + freshness metadata, staleness flag on failure.
2. `overrides.json` — seed from `~/llm/llm-cost-estimator/data/pricing.json`.
3. Tests — merge precedence, TTL logic, stale-fallback path, schema validation (mirror llm-cost-estimator's pricing validation).
4. Wire consumers — point llm-cost-estimator at the merged cache; document the read path for Hermes/Pi agents.

## Open questions

- TTL default: 24h proposed. Cost-critical runs (e.g. The Brief) may want a shorter floor.
- LiteLLM pull cadence inside the TTL gate: same TTL or independent?
- Cache location: this repo's `cache/` vs `~/.hermes/data/` shared path. Decision needed before wiring consumers.
