# Quickstart: Pricing Query

```bash
# What does a model cost? (auto-refreshes if data is stale)
python ~/llm/llm-pricing-sot/fetch_pricing.py query price kimi-k3

# Where is a model cheapest? (provider variants, discovery pricing)
python ~/llm/llm-pricing-sot/fetch_pricing.py query cheapest gemini-3.7-flash

# What models do we know about?
python ~/llm/llm-pricing-sot/fetch_pricing.py query list

# How fresh is the data?
python ~/llm/llm-pricing-sot/fetch_pricing.py query fresh

# Never touch the network:
python ~/llm/llm-pricing-sot/fetch_pricing.py query price kimi-k3 --offline

# Force a full refresh (the plain pipeline command, unchanged):
python ~/llm/llm-pricing-sot/fetch_pricing.py --force
```

Interpretation:
- `"baseline": false` → a model the SOT tracks. Use this price. `source` says where
  it came from: `override` = an attested rate we pay; `openrouter`/`litellm` = the
  live catalog price, refreshed automatically. Most tracked models read
  `openrouter` by design — hand-typed prices are avoided because they rot.
- `"baseline": true` → discovery pricing (OpenRouter/LiteLLM) — not a tracked
  model; informational only.
- `"degraded": true` → the answer is usable but stale or in `needs_review`.
- Exit codes: `0` clean, `1` served but degraded, `2` no data. Canonical statement:
  `.specify/memory/constitution.md` Principle III.
