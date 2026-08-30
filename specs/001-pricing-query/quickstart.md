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
- `"baseline": false` / `"source": "override"` → what we actually pay (truth).
- `"baseline": true` → discovery pricing (OpenRouter/LiteLLM) — baseline only.
- Exit codes: `0` fresh, `1` stale, `2` no data.
