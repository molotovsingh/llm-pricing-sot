---
name: llm-pricing
description: Get current LLM pricing (USD per 1M tokens) from the single source of truth at
  ~/llm/llm-pricing-sot. Use when you need a model's price, the cheapest provider host, the
  model list, or pricing freshness; to refresh pricing data; to work the review queue; or to
  judge whether a price is tracked by the SOT or merely discovered baseline.
---

# LLM Pricing

Single source of truth repo: `~/llm/llm-pricing-sot` (stdlib-only Python, no install).

## Queries (auto-refresh when data is stale)

```bash
python ~/llm/llm-pricing-sot/fetch_pricing.py query price <model>
python ~/llm/llm-pricing-sot/fetch_pricing.py query cheapest <model>
python ~/llm/llm-pricing-sot/fetch_pricing.py query list
python ~/llm/llm-pricing-sot/fetch_pricing.py query fresh
python ~/llm/llm-pricing-sot/fetch_pricing.py query review   # entries a human must resolve
```

Append `--offline` to any query to guarantee zero network (serves cached/stale data
or reports "not found"). Prefix `--ttl-hours N` to demand a tighter freshness window
than the 7-day default, e.g. `--ttl-hours 1 query price gpt-5.2`.

## Refresh (network)

```bash
python ~/llm/llm-pricing-sot/fetch_pricing.py            # refresh when stale
python ~/llm/llm-pricing-sot/fetch_pricing.py --force    # force a full refresh
```

## Reading the answer

Prices are USD per 1M tokens. One JSON object on stdout; human notes on stderr.

**Is this a price I can use?** Read `baseline`, not `source`:

<!-- contract:begin trust-rule -->
- `baseline: false` → the model is tracked by the SOT; use this price.
- `source` explains provenance only — `override` is an attested rate,
  `openrouter`/`litellm` is the live catalog price. **`source` does not gate trust.**
- `baseline: true` → discovery data, not a tracked model; informational only.
- `degraded: true` → usable but stale or in `needs_review`.
<!-- contract:end trust-rule -->

An `override` is deliberately different from public pricing (a `note` says why) and
`drift` reports the gap. Most tracked models read `source: openrouter` by design —
hand-typed prices are avoided because they rot. A `source` other than `override`
does **not** mean the answer is unreliable.

**Fields you may see:** `catalog` (the market row the price was checked against),
`drift` (normalized gap from it), `review` (a human must look at this entry),
`ranked_by` on `cheapest` (the input:output blend used to order providers).

## Exit codes

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

Exit 1 is not only staleness — do not report it as "stale data" without checking.
The answer is usable; say it is degraded rather than presenting it as certain. Run
`query review` to see which entries need attention and why.

## Cost estimate for a call

```bash
~/llm/llm-cost-estimator/estimate_llm_cost.py --pricing-dir ~/llm/llm-pricing-sot <file> [--max-tokens N] [--models m1,m2]
```

## OpenRouter account lookups (interactive only)

For interactive OpenRouter account state — credits balance, exact cost of a specific
`generation` id, provider latency/data-policy for a model — use OpenRouter's official
MCP server. Do NOT use it for the unattended pricing fetcher: it needs OAuth consent,
a 7-day expiring key, and a spend cap; the local pipeline uses plain REST instead.
