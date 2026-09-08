# Data Model: Cost per unit of work at a named deployment

**Feature**: `005-cost-per-unit` · **Date**: 2026-09-08

## Unit

What one unit of a price buys. A closed vocabulary, defined once as `UNITS` in
`fetch_pricing.py` and derived into governed documents by the contract gate.

| unit | price fields | meaning |
|---|---|---|
| `per_1m_tokens` | `in`, `out` | USD per one million input / output tokens (existing) |
| `per_page` | `price` | USD per page processed |
| `per_run` | `price` | USD per request / invocation |
| `per_gpu_hour` | `usd_per_hour` | USD per hour of a named GPU |
| `per_month` | `price` | USD per month, flat; cost per unit of work needs a volume |

Validation is per unit: the unit's fields must be present and non-negative numbers;
fields of other units must be absent. An unknown unit fails validation.

## Deployment (`deployments.json`, truth layer)

A model at a host, or on own hardware, priced in its native unit and attested. Keyed
`<model>@<host>`. Two forms:

**Quoted** — the price is declared:

```json
"kimi-k3@together": {
  "model": "kimi-k3", "host": "together", "unit": "per_1m_tokens",
  "in": 3.0, "out": 15.0,
  "note": "Together serverless list price, together.ai/pricing", "verified_at": "2026-09-08"
}
```

**Derived** — the price is computed from a GPU rate and a measurement:

```json
"deepseek-ocr@self-host": {
  "model": "deepseek-ai/DeepSeek-OCR", "host": "self-host", "unit": "per_page",
  "derive": {"gpu": "l40s@runpod", "seconds_per_unit": 15, "bench_run": "<id>"},
  "note": "...", "verified_at": "2026-09-08"
}
```

| field | required | notes |
|---|---|---|
| `model` | yes | tracked id from `overrides.json`, or any id (self-host models need no tokenizer) |
| `host` | yes | canonical host name; `self-host` for own infrastructure |
| `unit` | yes | from `UNITS` |
| price fields | quoted only | per the unit; absent on derived entries |
| `derive` | derived only | `gpu` (key into `gpu_rates.json`), `seconds_per_unit` (>0), `bench_run` (string id) |
| `note` | yes (attestation) | where the number came from |
| `verified_at` | yes (attestation) | ISO date; expires after `ATTESTATION_MAX_AGE_DAYS` |
| `negotiated` | no | `true` when the rate is not the host's public one |

**Emitted shape** (under `pricing.json.deployments[id]`): the declared fields, plus
`source: "deployment"`, `baseline: false`, the resolved price fields, and:

- `catalog` — for a `per_1m_tokens` deployment at a host present in the per-host
  catalog: `{host, in, out, source: "openrouter-endpoints"|"hf-router"}`.
- `drift` — normalised gap from `catalog` above `DRIFT_TOLERANCE`, informational.
- `rate` — for derived entries: `{key, usd_per_hour, provider}` actually used.
- `review` — a reason from the table below when a human must look.
- `attestation` — `valid` | `expired` | `missing`.

## GPU rate (`gpu_rates.json`, attested input)

```json
"l40s@runpod": {
  "gpu": "L40S", "provider": "runpod", "tier": "secure-cloud",
  "usd_per_hour": 1.09,
  "note": "runpod.io/pricing, Secure Cloud on-demand", "verified_at": "2026-09-08"
}
```

Keyed `<gpu>@<provider>` — never averaged across providers; the user pays one of them.
Attested and expiring exactly like a price. Emitted only through the deployments that
use it (`rate`), not as its own envelope key.

## Host row (catalog, verifier)

One `(host, sku)` price for a model, from either catalog. Never truth.

```json
{"host": "baseten", "in": 1.4, "out": 4.4, "unit": "per_1m_tokens",
 "source": "openrouter-endpoints", "quantization": "fp8", "context_length": 1048576,
 "status": "live", "baseline": true}
```

Sources: `openrouter-endpoints` (from `cache/endpoints/<slug>.json`, provider name
canonicalised) and `hf-router` (from `discovery.json.hf_router[hf_id][host]`). A host
listed without a price (Featherless, `pricing: null`) is retained with no price fields
and is never ranked as cheapest per token.

## Host canonicalisation

`canonical_host(name)`: lowercase → strip non-alphanumerics → alias table:

| forms seen | canonical |
|---|---|
| `BaseTen`, `baseten` | `baseten` |
| `Fireworks`, `fireworks-ai` | `fireworks` |
| `Featherless`, `featherless-ai` | `featherless` |
| `Z.AI`, `zai-org`, `z-ai` | `zai` |
| `Moonshot AI`, `moonshotai` | `moonshot` |
| `DeepInfra`, `deepinfra` | `deepinfra` |
| `Together`, `together` | `together` |

Unknown names are kept distinct after normalisation. No fuzzy matching (R7).

## `discovery.json` delta

Gains one layer, additive:

```json
"hf_router": {
  "moonshotai/Kimi-K3": {
    "together":  {"in": 3.0, "out": 15.0, "context_length": 1048576, "status": "live"},
    "baseten":   {"in": 3.0, "out": 15.0, "context_length": 1048576, "status": "live"},
    "featherless": {"status": "live"}
  }
}
```

`_load_discovery` tolerates the layer's absence (older files), so a stale sidecar
written before this feature still loads.

## `overrides.json` delta

One optional field per entry: `"hf_id": "moonshotai/Kimi-K3"`. Without it, the model
has no HF router rows. Shape test extended: when present, `hf_id` is `org/name`.

## Envelope delta (`cache/pricing.json`)

Additive, exactly one new key:

```
fetched_at, freshness, models, needs_review, ttl_hours   (existing)
deployments                                              (new: {id: emitted deployment})
```

`models[*]` gain `unit: "per_1m_tokens"`; `in`/`out`/`tokenizer`/`source`/`catalog`/
`drift`/`review` are unchanged. `needs_review` rolls up deployment ids alongside model
ids. The `envelope` contract fact picks the new key up from `build_cache` automatically
and regenerates every governed block.

## Review reasons (additions)

| reason | applies to | meaning |
|---|---|---|
| `unattested-deployment` | deployment | no `note` / unparseable `verified_at`; catalog price served if one exists at that host, else declared price kept |
| `attestation-expired` | deployment, GPU rate | `verified_at` older than `ATTESTATION_MAX_AGE_DAYS`; price kept |
| `gpu-rate-missing` | derived deployment | `derive.gpu` not in `gpu_rates.json`; no price emitted |
| `gpu-rate-expired` | derived deployment | the rate it uses has an expired attestation; price kept |
| `bench-missing` | derived deployment | `derive.seconds_per_unit` absent or ≤ 0; no price emitted |
| `gpu-rate-unattested` | derived deployment | the rate it uses has no `note` / parseable `verified_at`; price kept, a human must claim the rate |
| `invalid-deployment` | deployment | shape failed validation (missing `model`/`host`/`unit`, unknown unit, both or neither of price fields and `derive`); emitted with no price so it is reported, never silently dropped |

Existing reasons (`unattested-price-ignored`, `attestation-expired`,
`unverifiable-price`, `dropped-unpriceable`) are unchanged for `models`.
