# Contract: deployments, hosts, and units

**Feature**: `005-cost-per-unit` · **Date**: 2026-09-08

Normative shapes for the two new truth files and the three new query surfaces. Exit
codes, the envelope key list, the trust rule and the unit vocabulary are **derived from
`fetch_pricing.py`** and kept in step by `tests/test_contract_drift.py`; this document
references them and restates nothing the gate governs.

## Units

<!-- contract:begin units -->
| unit | price fields | one unit buys |
|---|---|---|
| `per_1m_tokens` | `in`, `out` | one million input / output tokens |
| `per_page` | `price` | one page processed |
| `per_run` | `price` | one request / invocation |
| `per_gpu_hour` | `usd_per_hour` | one hour of the named GPU |
| `per_month` | `price` | one month, flat -- cost per unit of work needs a volume |

Per-token prices are USD per 1M tokens. A unit's fields are never reused for another unit, so a consumer that multiplies `in`/`out` by a token count cannot pick up a per-page price by mistake.
<!-- contract:end units -->

## `deployments.json`

Top-level object; keys are `<model>@<host>`; `_`-prefixed keys are documentation. Each
entry: `model`, `host`, `unit`, then **either** the unit's price fields **or** a
`derive` object (`gpu`, `seconds_per_unit`, `bench_run`), plus `note` and `verified_at`.
`negotiated: true` is optional and means the rate is not the host's public one.

## `gpu_rates.json`

Top-level object; keys are `<gpu>@<provider>`. Each entry: `gpu`, `provider`,
`usd_per_hour`, `note`, `verified_at`; `tier` optional.

## `query hosts <model>`

```
{"model": "<id>", "freshness": ..., "degraded": bool,
 "hosts": [ {host row}, ... ],          // both catalogs, canonical host names, cheapest first
 "deployments": [ {emitted deployment}, ... ]}   // any for this model, baseline: false
```

Exit: through `_exit_for` — `degraded` is true when any listed deployment is flagged.
`found: false` and exit 2 when no catalog row and no deployment exists.

## `query price <model> --host <host>`

Resolution order, first match wins:

1. `deployments["<model>@<host>"]` → served as-is (`baseline: false`, `source: deployment`).
2. Cheapest catalog row at that host → `baseline: true`, `source` naming the catalog.
3. `{"model", "host", "found": false}` → exit 2.

Host is canonicalised before matching. `degraded` is true when a served deployment
carries `review`.

## `query cheapest <model> --host <host>`

As `cheapest` today, with candidates restricted to the named host across both catalogs.
Rows without a per-token price are never candidates. `ranked_by` unchanged.

## `query deployments`

```
{"freshness": ..., "degraded": bool,
 "deployments": [ {emitted deployment, "id": "<model>@<host>"}, ... ]}
```

stderr carries a human table (`id`, unit, price, attestation, review). Exit 1 while
any deployment is flagged; 2 when no cache.

## Review reasons

See `data-model.md` — the table there is the reference; the pipeline's stderr and the
`review` field use those strings verbatim.
