# Quickstart: Pricing Endpoints Upgrade

```bash
# Cheapest host — now from OpenRouter's per-provider endpoints (primary):
python ~/llm/llm-pricing-sot/fetch_pricing.py query cheapest kimi-k3
#   -> provider (e.g. Makora), price, quantization, cache-read price

# Vendor-direct models (no OpenRouter endpoints) fall back to LiteLLM:
python ~/llm/llm-pricing-sot/fetch_pricing.py query cheapest glm-5.2

# Offline: serve endpoint snapshots from cache, never fetch:
python ~/llm/llm-pricing-sot/fetch_pricing.py query cheapest kimi-k3 --offline
```

Interpretation:
- `"source": "openrouter-endpoints"` → per-provider data from OpenRouter
  (baseline, not what we pay).
- `"fallback": true` → LiteLLM/discovery variant scan (vendor-direct coverage).
- `"authoritative"` → the override price (what we actually pay) for context.

Notes:
- Endpoint responses are cached per model (`cache/endpoints/`) under the 24h TTL.
- The OpenRouter MCP is for interactive account lookups only (credits,
  per-generation cost) — the pipeline never uses it.
