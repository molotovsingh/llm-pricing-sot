# Data Model: Pricing Endpoints Upgrade

## Entities

### Provider Endpoint (baseline)

One provider's hosted copy of an OpenRouter-routed model, from
`GET /api/v1/models/{author}/{slug}/endpoints`.

| Field | Type | Notes |
|---|---|---|
| `provider_name` | string | e.g. Makora, DeepInfra |
| `tag` | string | provider tag (e.g. `makora`) |
| `quantization` | string | e.g. `bf16`, `fp4`, `unknown` |
| `context_length` | int? | token context window |
| `in` | number ≥ 0 | USD per 1M input tokens (from `pricing.prompt`) |
| `out` | number ≥ 0 | USD per 1M output tokens (from `pricing.completion`) |
| `in_cache_read` | number? | USD per 1M cached-input tokens (from `pricing.input_cache_read`) |
| `status` | int? | endpoint status code |

### Endpoint Snapshot

`cache/endpoints/<slug>.json` — the TTL-gated cache of one model's endpoints
response: `{fetched_at, ttl_hours, slug, endpoints: [Provider Endpoint]}`.
Freshness rule identical to the other caches (24h default; boundary = stale).

### Slug Mapping

`model_id → OpenRouter {author}/{slug}`. Resolution order:
1. exact `id` match in the OpenRouter models catalog;
2. `openrouter_slug` field on the override entry (maintainer-declared);
3. none → no endpoints path (fallback scan).

### Discovery Entry (baseline) — extended

The OpenRouter discovery layer entry now optionally carries:
`in_cache_read`, `in_cache_write` (USD/1M), `has_pricing_overrides` (bool).
Additive only; authoritative entries unchanged.

### Cheapest Answer (extended)

`query cheapest` output now includes `provider_name`, `quantization`,
`in_cache_read` (when present), and `source: "openrouter-endpoints"` when the
endpoints path produced it, or `source: "litellm"|"openrouter"` with
`baseline: true` on the fallback path.

## State Transitions

- Online + snapshot fresh → serve snapshot (zero network).
- Online + snapshot stale/missing → fetch endpoints → write snapshot → serve.
- Offline → serve snapshot as-is; stale snapshot answers exit 1.
- No slug / no endpoints / fetch failure → LiteLLM+OpenRouter variant scan
  fallback; nothing found → `found: false`, exit 2.
