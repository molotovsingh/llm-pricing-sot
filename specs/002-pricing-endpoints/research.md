# Phase 0 Research: Pricing Endpoints Upgrade

All open items resolved (verified live where noted).

## R1. OpenRouter `/endpoints` as primary cheapest source

- **Decision**: `query cheapest <model>` fetches
  `GET /api/v1/models/{author}/{slug}/endpoints` (public, no auth — verified live
  for `moonshotai/kimi-k3`: 17 endpoints) and picks the cheapest by
  `pricing.prompt` then `pricing.completion`. The answer carries `provider_name`,
  `quantization`, `in`/`out` (converted per-token → USD/1M), and
  `input_cache_read` when present. Data is baseline (`baseline: true`), never
  authoritative.
- **Rationale**: replaces the fuzzy variant suffix-match with the router's own
  per-provider table — provider name and quantization included, no heuristic.
- **Alternatives considered**: keep LiteLLM variant scan (stays as fallback —
  R3); prefetch all endpoints (≈396 calls — rejected, on-demand only).

## R2. Slug resolution

- **Decision**: resolve model id → OpenRouter slug in order: (1) exact id match
  in the models catalog; (2) overrides-declared slug (new optional
  `openrouter_slug` field in an override entry); (3) none → fallback path (R3).
- **Rationale**: our model ids (e.g. `kimi-k3`) are not always OpenRouter ids
  (`moonshotai/kimi-k3`); the catalog exact-match covers most, the override
  field covers the rest deterministically.
- **Alternatives considered**: string guessing by prefix (fragile — rejected).

## R3. LiteLLM demotion to fallback/cross-check

- **Decision**: LiteLLM (and the OpenRouter catalog discovery layer) remain the
  fallback when no endpoints exist (vendor-direct pricing, e.g. z.ai GLM), using
  the existing variant scan. LiteLLM is removed from the primary cheapest path.
- **Rationale**: endpoints cover OpenRouter-routed models; LiteLLM still covers
  vendor-direct prices OpenRouter does not list.
- **Alternatives considered**: drop LiteLLM entirely (loses z.ai/GLM direct
  rates — rejected); keep LiteLLM primary (less precise — rejected).

## R4. Endpoint snapshot caching

- **Decision**: cache each response at `cache/endpoints/<slug>.json` with
  `fetched_at`/`ttl_hours` (24h), same freshness rule. Online + stale/missing →
  fetch; offline → serve snapshot as-is (or fallback/not-found).
- **Rationale**: repeat queries within the window need zero network (SC-002).
- **Alternatives considered**: in-memory only (lost between runs — rejected);
  unbounded prefetch (wasteful — rejected).

## R5. Richer baseline fields

- **Decision**: `_normalize_openrouter` additionally captures
  `input_cache_read`/`input_cache_write` (per-token → USD/1M) and sets
  `"has_pricing_overrides": true` when the model's pricing block contains
  `overrides`. Fields are additive only.
- **Rationale**: stores cache pricing for future cached-token cost work; zero
  behavior change now (extra keys ignored by the estimator).
- **Alternatives considered**: ignore cache pricing (loses data — rejected);
  change the authoritative schema (out of scope — rejected).

## R6. MCP role split

- **Decision**: the pipeline never calls OpenRouter MCP. The `llm-pricing` skill
  gains a short note: "For interactive OpenRouter account lookups (credits,
  exact per-generation cost, provider latency), use OpenRouter's official MCP —
  not this local pipeline." Plain REST remains the only pipeline path.
- **Rationale**: MCP = OAuth + 7-day expiring key + spend cap → wrong dependency
  for an unattended fetcher; right tool for interactive agent-time lookups.
- **Alternatives considered**: integrate MCP into the pipeline (violates
  constitution Principle III — no daemon/server — rejected).

## R7. README roles

- **Decision**: sources table updated — OpenRouter endpoints = cheapest-host
  layer (per-provider, quantization); LiteLLM = fallback/cross-check
  (vendor-direct); OpenRouter models catalog = baseline + slug resolution.
- **Rationale**: keeps the documented mental model honest after the demotion.
- **Alternatives considered**: leave README unchanged (stale — rejected).
