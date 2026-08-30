# Data Model: Pricing Query

## Entities

### Pricing Entry (authoritative)

A model the SOT actually prices. Lives in `cache/pricing.json` `models` map
(merged: overrides > LiteLLM > OpenRouter).

| Field | Type | Notes |
|---|---|---|
| `in` | number ≥ 0 | USD per 1M input tokens |
| `out` | number ≥ 0 | USD per 1M output tokens |
| `tokenizer` | string | required (validator drops entries without it) |
| `fallback` | string? | optional fallback tokenizer spec |
| `source` | `override`\|`litellm`\|`openrouter` | highest-precedence contributing layer |
| `alternatives` | array? | maintainer-supplied provider alternatives |

Uniqueness: `model_id` key. Validation: non-negative `in`/`out`, `tokenizer` present.

### Discovery Entry (baseline)

A model/price discovered from OpenRouter or LiteLLM. Lives in the discovery
sidecar layers; never carries a tokenizer (sources provide none).

| Field | Type | Notes |
|---|---|---|
| `in` | number? | USD per 1M input tokens |
| `out` | number? | USD per 1M output tokens |
| `source` | `litellm`\|`openrouter` | origin layer |

Always surfaced to callers with `baseline: true`.

### Cache Snapshot

Envelope of `cache/pricing.json`: `{fetched_at (ISO-8601 UTC), ttl_hours,
freshness ("fresh"|"stale"), models: {model_id → Pricing Entry}}`.

Freshness rule: fresh iff `now − fetched_at < ttl_hours` (boundary = stale).
Missing/unparseable `fetched_at` = stale; missing file = no-data.

### Discovery Snapshot

Envelope of `cache/discovery.json`: `{fetched_at, ttl_hours,
openrouter: {id → Discovery Entry}, litellm: {id → Discovery Entry}}`.
Same freshness rule; same TTL gate as the cache.

### Query Answers

`price`:
```json
{"model": "kimi-k3", "in": 3.0, "out": 15.0, "tokenizer": "hf:...",
 "source": "override", "baseline": false, "freshness": "fresh"}
```
Discovery fallback answers set `baseline: true`, omit `tokenizer`.
Not found: `{"model": "x", "found": false, "freshness": "fresh"}` (exit 2).

`cheapest`:
```json
{"model": "gemini-3.7-flash", "provider": "deepinfra/google/gemini-3.7-flash",
 "in": 0.75, "out": 3.75, "source": "litellm", "baseline": true,
 "authoritative": null, "variants": 3, "freshness": "fresh"}
```
`authoritative` carries the cache entry (what we actually pay) when present.

`list`: `{"freshness": "fresh", "models": [{"model", "in", "out", "source", "baseline"}, ...]}`

`fresh`: `{"freshness": "fresh"|"stale"|"no-data", "fetched_at": ..., "ttl_hours": 24}`

## State Transitions

- Query with fresh cache → answer from cache (exit 0), zero network.
- Query with stale/missing cache, online → `run()` refresh → cache + sidecar
  written → answer (exit 0 fresh / 1 stale / 2 none).
- Query offline → cache/sidecar served as-is; stale answers exit 1; unknown model
  or no data exit 2.
- Discovery fallback with stale/missing sidecar, online → discovery fetch →
  sidecar written → answer.
