---
name: llm-pricing
description: Get current LLM pricing (USD per 1M tokens) from the single source of truth at
  ~/llm/llm-pricing-sot. Use when you need a model's price, the cheapest provider host, the
  model list, or pricing freshness; to refresh pricing data; or to judge whether prices are
  authoritative (overrides) vs baseline (OpenRouter/LiteLLM discovery).
---

# LLM Pricing

Single source of truth repo: `~/llm/llm-pricing-sot` (stdlib-only Python, no install).

## Queries (auto-refresh when data is stale)

```bash
python ~/llm/llm-pricing-sot/fetch_pricing.py query price <model>
python ~/llm/llm-pricing-sot/fetch_pricing.py query cheapest <model>
python ~/llm/llm-pricing-sot/fetch_pricing.py query list
python ~/llm/llm-pricing-sot/fetch_pricing.py query fresh
```

Append `--offline` to any query to guarantee zero network (serves cached/stale data
or reports "not found").

## Refresh (network)

```bash
python ~/llm/llm-pricing-sot/fetch_pricing.py            # refresh when stale; unchanged pipeline command
python ~/llm/llm-pricing-sot/fetch_pricing.py --force    # force a full refresh
```

## Contract

- Answers are one JSON object on stdout; human notes on stderr.
- Exit codes: `0` fresh, `1` stale, `2` no data / not found.
- `"baseline": false` (usually `"source": "override"`) = what we actually pay — authoritative.
- `"baseline": true` = discovery pricing from OpenRouter/LiteLLM — baseline only, NOT what we pay.
- Prices are USD per 1M tokens.

## Cost estimate for a call

```bash
~/llm/llm-cost-estimator/estimate_llm_cost.py --pricing-dir ~/llm/llm-pricing-sot <file> [--max-tokens N] [--models m1,m2]
```

## OpenRouter account lookups (interactive only)

For interactive OpenRouter account state — credits balance, exact cost of a specific
`generation` id, provider latency/data-policy for a model — use OpenRouter's official
MCP server. Do NOT use it for the unattended pricing fetcher: it needs OAuth consent,
a 7-day expiring key, and a spend cap; the local pipeline uses plain REST instead.
