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
| 1. **Overrides** (truth) | Local `overrides.json` | Tokenizer mappings (always) and `openrouter_slug` pins; prices **only** where we pay something the catalog does not list (e.g. z.ai GLM direct), marked `negotiated` | Existing `llm-cost-estimator/data/pricing.json` becomes this |
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

**Schema you read:** `{ "fetched_at": "<ISO-8601 UTC>", "ttl_hours": 24, "freshness": "fresh", "needs_review": ["<model_id>", ...], "models": { "<model_id>": { "in": <$/1M>, "out": <$/1M>, "tokenizer": "...", "fallback" (optional), "source": "override"|"openrouter"|"litellm", "catalog" (optional), "drift" (optional), "review" (optional) } } }`. Prices are USD per 1M tokens.

The envelope keys are fixed:

<!-- contract:begin envelope -->
Cache envelope keys: `fetched_at`, `freshness`, `models`, `needs_review`, `ttl_hours`.
<!-- contract:end envelope -->

**`freshness` is about age, not correctness.** It reports when the data was last fetched, not whether a price is right. That is what `needs_review` is for. Check both.

**Deciding whether to use a price:**

<!-- contract:begin trust-rule -->
- `baseline: false` → the model is tracked by the SOT; use this price.
- `source` explains provenance only — `override` is an attested rate,
  `openrouter`/`litellm` is the live catalog price. **`source` does not gate trust.**
- `baseline: true` → discovery data, not a tracked model; informational only.
- `degraded: true` → usable but stale or in `needs_review`.
<!-- contract:end trust-rule -->

**Judge staleness** from `freshness` (`fresh` / `stale`), or recompute from `fetched_at` + `ttl_hours`. A cache is stale when `now - fetched_at >= ttl_hours`; missing/unparseable `fetched_at` is treated as stale.

**Auto-refresh rule:** if the cache is missing or stale, run `python fetch_pricing.py [--force] [--ttl-hours H]` then re-read.

<!-- contract:begin exit-codes -->
| freshness | degraded | exit |
|---|---|---|
| `fresh` | no | `0` |
| `fresh` | yes | `1` |
| `stale` | no | `1` |
| `stale` | yes | `1` |
| `no-data` | no | `2` |
| `no-data` | yes | `2` |

`0` clean · `1` served but degraded (stale **or** the answer's entry is in `needs_review`) · `2` no usable data.
<!-- contract:end exit-codes -->

- **Hermes agents** — read the cache file; if `freshness: stale`, run the script (auto-refresh) then re-read. Do not necessarily re-fetch every turn.
- **Pi** — same file via its bash/read tools; same staleness rule. No Pi-specific integration needed.
- **llm-cost-estimator** — reads `models` from the cache (not its own `data/pricing.json`) and auto-refreshes when stale/missing, honoring the exit codes above; its validation (non-negative in/out, tokenizer present) stays the final gate. Point it at the repo with `LLM_PRICING_SOT_DIR` or `--pricing-dir`.

## File contract (realized)

```
llm-pricing-sot/
├── README.md                 # this file
├── overrides.json            # layer 1 — hand-maintained, highest precedence
├── fetch_pricing.py          # stdlib-only pipeline: fetch → merge → emit (T-001..T-008 done)
├── cache/
│   ├── pricing.json          # merged output: {fetched_at, freshness, ttl_hours, models: {...}}
│   ├── discovery.json        # raw layers: {fetched_at, ttl_hours, litellm, openrouter}
│   └── endpoints/            # per-slug endpoint snapshots for `query cheapest`
├── tests/                    # 58 tests: merge precedence, TTL, stale-fallback, queries
├── specs/                    # SDD spec for the pipeline (T-001..T-008)
└── .specify/                 # spec-kit workspace
```

**CLI surface (implemented):**

```
fetch_pricing.py [--force] [--ttl-hours H]      # refresh if stale, emit cache; exit 0 clean / 1 degraded / 2 no cache
fetch_pricing.py query price <model>            # authoritative price (override if present)
fetch_pricing.py query cheapest <model>         # cheapest OpenRouter endpoint + authoritative override
fetch_pricing.py query list                    # all models in cache
fetch_pricing.py query fresh                   # freshness metadata
fetch_pricing.py query review                  # the review queue; exit 1 while non-empty
```

`query review` is the work list for `needs_review`. It shows the price you declared
against the one now being served, so each row is a decision — attest the declared price,
or delete `in`/`out` and keep inheriting:

```
model              you declared     now serving  reason
gpt-5.2                 0.4/1.6       1.75/14.0  unattested-price-ignored
gpt-5.6-sol            5.0/30.0        2.0/10.0  unattested-price-ignored
```

The table goes to stderr; stdout stays machine-readable JSON like every other query.

`--ttl-hours` applies to queries too (`fetch_pricing.py --ttl-hours 1 query price <model>`),
so a cost-critical run can demand a tighter freshness window than the 24h default. It gates
what *that* caller sees and is never stamped into the shared envelope — persisting it would
change every other consumer's refresh cadence.

**Every query answer carries `degraded`.** It is true when the answer is stale *or* its
entry is in `needs_review`, and it drives the exit code. Age and trust are independent:
a perfectly fresh cache can serve a degraded answer, so `freshness: fresh` with
`degraded: true` is normal and means "recent, but a human needs to look at this one".

**How `cheapest` ranks.** Which host is cheapest depends on your input:output token mix, so
providers are ranked on blended cost at `CHEAPEST_IO_RATIO` (3 input : 1 output) rather
than on input price alone — otherwise a host with cheap input and expensive output wins a
comparison it should lose. The assumption is named in the answer as `ranked_by`, and an
endpoint missing either price never wins. Ties resolve to the first provider in catalog
order, as the spec requires.

Merged model entry shape (as emitted — matches llm-cost-estimator's expectations; `fallback` only present for HF-tokenizer models):

```json
{
  "gpt-5.2": {
    "in": 0.40, "out": 1.60,
    "tokenizer": "tiktoken:o200k_base",
    "source": "override",
    "catalog": {"slug": "openai/gpt-5.2", "source": "openrouter", "in": 1.75, "out": 14.00},
    "drift": {"in": 0.7714, "out": 0.8857}
  }
}
```

### The overrides layer: hand-maintain tokenizers, not prices

Only an override can supply a `tokenizer` — no pricing source publishes one. But a
hand-typed **price** is exactly the drift this repo exists to eliminate, so the price is
optional, and that choice is the contract:

| Override shape | Meaning | `source` |
| :-- | :-- | :-- |
| `tokenizer` only | inherit the live catalog price; only the tokenizer is hand-held | `openrouter` / `litellm` |
| `tokenizer` + `in`/`out` | **not trusted** — price discarded, catalog used, entry flagged | `openrouter` / `litellm` |
| … + `negotiated: true` + `note` + `verified_at` | attested: a rate we actually pay that the catalog does not list | `override` |

**An unattested price is discarded**, not merely flagged: the catalog price is used instead
and the entry is reported under `needs_review`. This is what stops a stale transcription
from surviving a refresh — a hand-typed number has to be claimed by a human to count.
The only exception is an entry with no catalog row at all: nothing can replace it, so the
price stands and is flagged `unverifiable-price`.

`openrouter_slug` pins slug resolution and is required for price-inheriting entries — a
mis-resolved slug now yields a wrong *price*, not just a wrong comparison.

Each override is linked to its catalog row (`openrouter_slug` if declared, else exact id,
else last-segment match; LiteLLM exact id as fallback) and that row is attached as
`catalog`, *alongside* the authoritative price and never merged into it. (The field is
`catalog`, not `baseline`: the query surface already uses a boolean `baseline` flag for
discovery-sourced answers.)

For an *attested* entry, `drift` records the gap from catalog — a normalized divergence in
`[0, 1]` (`|catalog - ours| / max(catalog, ours)`, symmetric so it stays finite and
JSON-safe when either side is zero) above `DRIFT_TOLERANCE` (5%). Here drift is
informational, not an alarm: an attested rate is *expected* to differ. A widening gap is
still worth a look — it can mean the vendor repriced.

### Attestations expire

`verified_at` older than `ATTESTATION_MAX_AGE_DAYS` (90) is reported as
`attestation-expired`. Without expiry, `negotiated: true` would be a permanent mute button
and attested prices would rot exactly as before. An expired attestation **keeps** its
price — reverting to catalog would silently change the number you believe you pay — and
asks a human to re-confirm instead.

### The review queue

`review` reasons:

| reason | meaning |
| :-- | :-- |
| `unattested-price-ignored` | hand-typed price discarded; catalog price used |
| `attestation-expired` | price kept, `verified_at` needs re-confirming |
| `unverifiable-price` | price kept; no catalog row to check it against |
| `dropped-unpriceable` | **absent from `models`** — no own price and no catalog match |

`dropped-unpriceable` is the one that costs you a model rather than a number: it means a
price-less override's slug no longer resolves (OpenRouter renames and retires slugs), so
nothing could be inherited. Fix the `openrouter_slug`, or give the entry an attested price.

Flagged ids roll up top-level as `needs_review`, print to stderr, and **degrade the exit
code to 1** — on the cache-hit path too, so a flag cannot go quiet for the length of the
TTL window. Clear one by attesting the price or deleting `in`/`out` so the entry inherits.

All of these fields are additive: consumers that ignore them are unaffected.

Per-provider alternatives are **not** inlined into cache entries — they live in `cache/endpoints/<slug>.json` and are surfaced by `query cheapest`, which returns the authoritative override alongside the cheapest endpoint (provider, price, quantization, variant count).

## Build status — DONE

- ✅ `fetch_pricing.py` — fetch (OpenRouter models + `/endpoints`, LiteLLM), merge (attested overrides > OpenRouter catalog > LiteLLM), emit cache with freshness + review metadata, stale-fallback when the catalog is unreachable
- ✅ `overrides.json` — seeded from `~/llm/llm-cost-estimator/data/pricing.json`; carries optional `openrouter_slug` where the short alias can't be resolved from the catalog
- ✅ Attested-price enforcement — unattested hand-typed prices are discarded for the live catalog price; attestations expire after 90 days; anything reviewable degrades the exit code
- ✅ Tests — 120 passing: merge precedence, TTL logic, stale-fallback, query surface, catalog linkage, attestation + review queue, atomic writes, cheapest ranking, pin authority, degraded exit codes, shipped-data shape
- ✅ Cache — `cache/pricing.json` + `discovery.json` + `endpoints/` emitting per the contract
- 🔜 Consumer wiring — llm-cost-estimator integration via `LLM_PRICING_SOT_DIR` / `--pricing-dir` documented but not yet shipped in the estimator

### Source outages are not equal

The OpenRouter catalog is **load-bearing**: slug resolution and price inheritance both read
it, so if it is unreachable the run serves the stale cache rather than emitting a thin one.
LiteLLM is a demoted fallback — if it is down the refresh proceeds, reusing the last known
LiteLLM layer from `discovery.json` instead of discarding an otherwise healthy fetch.

All cache writes go through a temp file plus `os.replace`, so a concurrent reader (Hermes,
Pi and the estimator share these files) sees either the old file or the new one, never a
partial write.

## Open questions

- **The 4 unattested prices.** `gpt-5.2`, `gpt-5.6-sol`, `gpt-5.6-luna` and `deepseek-v4-pro`
  carry hand-typed prices with no attestation, so the catalog price is being used instead
  and they sit in `needs_review`. Each needs a decision: attest it (`negotiated` + `note` +
  `verified_at`) or delete `in`/`out` and let it inherit permanently.
- **`glm-5.2`'s `verified_at` (2026-08-16) was derived from git history**, not from anyone
  confirming the rate. It should be re-confirmed against the z.ai plan.
- `ATTESTATION_MAX_AGE_DAYS` is 90 — a guess. Tighten it if rates are renegotiated more often.
- Whether models outside the overrides list should be priceable at all. `discovery.json`
  already holds ~3,200 of them; the emitted cache deliberately does not (`tokenizer` gate,
  ratified in `specs/001-pricing-query/data-model.md`). Changing that is a spec-level decision.
