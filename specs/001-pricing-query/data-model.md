# Data Model: Pricing Query

## Entities

### Pricing Entry (authoritative)

A model the SOT actually prices. Lives in `cache/pricing.json` `models` map
(merged: overrides > OpenRouter catalog > LiteLLM).

| Field | Type | Notes |
|---|---|---|
| `in` | number ≥ 0 | USD per 1M input tokens |
| `out` | number ≥ 0 | USD per 1M output tokens |
| `tokenizer` | string | required (validator drops entries without it) |
| `fallback` | string? | optional fallback tokenizer spec |
| `source` | `override`\|`litellm`\|`openrouter` | where the *price* came from; `override` only for an attested price |
| `catalog` | object? | the resolved catalog row: `{slug, source, in?, out?}` |
| `drift` | object? | normalized divergence of an attested price from `catalog`, per field |
| `review` | string? | why a human must look: see review reasons below |
| `alternatives` | array? | maintainer-supplied provider alternatives |

Uniqueness: `model_id` key. Validation: non-negative `in`/`out`, `tokenizer`
present, non-negative `catalog` prices where given.

**Price provenance.** An override supplies the tokenizer always, the price only
when it is a rate the catalog does not list — and then only with an attestation
(`negotiated: true` + `note` + `verified_at`). An unattested price is discarded
for the catalog price. Attestations older than `ATTESTATION_MAX_AGE_DAYS` (90)
are reported, not silently trusted.

Review reasons: `unattested-price-ignored`, `attestation-expired`,
`unverifiable-price` (no catalog row to check against), `dropped-unpriceable`
(entry absent from `models` — no own price and no catalog match).

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
freshness ("fresh"|"stale"), needs_review: [model_id], models: {model_id →
Pricing Entry}}`.

Freshness rule: fresh iff `now − fetched_at < ttl_hours` (boundary = stale).
Missing/unparseable `fetched_at` = stale; missing file = no-data. `freshness`
reports age only — a price can be wrong in a cache that reads `fresh`, which is
what `needs_review` is for. Writes are atomic (temp file + rename).

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
 "authoritative": null, "ranked_by": "blended-3:1", "variants": 3,
 "freshness": "fresh"}
```
`authoritative` carries the cache entry (what we actually pay) when present.
`ranked_by` names the input:output blend used to order providers — ranking on
input price alone would let a host with cheap input and expensive output win.

`list`: `{"freshness": "fresh", "models": [{"model", "in", "out", "source", "baseline"}, ...]}`

`fresh`: `{"freshness": "fresh"|"stale"|"no-data", "fetched_at": ..., "ttl_hours": 24}`

`review`: `{"freshness": ..., "needs_review": [{"model", "reason", "declared_in",
"declared_out", "serving_in", "serving_out", "serving_source", "slug"}, ...]}`.
Exit 1 while the queue is non-empty. `declared_*` comes from `overrides.json` (the
price that was discarded); `serving_*` is what the cache actually returns.

## State Transitions

- Query with fresh cache → answer from cache (exit 0), zero network.
- Query with stale/missing cache, online → `run()` refresh → cache + sidecar
  written → answer (exit 0 clean / 1 degraded / 2 none). Degraded covers a stale
  cache and a non-empty `needs_review`, on the cache-hit path too.
- Query offline → cache/sidecar served as-is; stale answers exit 1; unknown model
  or no data exit 2.
- Discovery fallback with stale/missing sidecar, online → discovery fetch →
  sidecar written → answer.
