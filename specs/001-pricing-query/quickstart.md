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

<!-- contract:begin trust-rule -->
- `baseline: false` → the model is tracked by the SOT; use this price.
- `source` explains provenance only — `override` is an attested rate,
  `openrouter`/`litellm` is the live catalog price. **`source` does not gate trust.**
- `baseline: true` → discovery data, not a tracked model; informational only.
- `degraded: true` → usable but stale or in `needs_review`.
<!-- contract:end trust-rule -->

Most tracked models read `openrouter` by design — hand-typed prices are avoided
because they rot.

Exit codes:

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
