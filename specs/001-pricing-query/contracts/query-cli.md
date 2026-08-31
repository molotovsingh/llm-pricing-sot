# Contract: Pricing Query CLI

Surface: `python fetch_pricing.py [--ttl-hours H] query <action> [model] [--offline]`

Rules: one JSON object to stdout per invocation; human notes/errors to stderr.

**Exit codes** — derived from the code and kept in step automatically
(`specs/003-contract-single-source/`). "No data" includes "not found".

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

Degraded is **age or trust**, and the two are independent: a stale cache, *or* an
answer whose entry is in `needs_review`. Every answer carries a `degraded` boolean
so a caller need not infer it from the exit code. `freshness` reports age only —
a fresh cache can still be degraded.

## `query price <model>`

Answer the model's price. Cache-first (tracked, `baseline: false`);
discovery-fallback (`baseline: true`, no `tokenizer`); `found: false` if unknown.
A tracked entry carries `source` (where the price came from), and optionally
`catalog`, `drift` and `review`.

Exit: `0` clean; `1` stale answer, or the entry carries `review`; `2` not found.

## `query cheapest <model>`

Cheapest provider-hosted variant of the model — OpenRouter per-provider endpoints
first, discovery variant scan as fallback — plus the authoritative price for
context when present. Variant matching per `research.md` R1.

Providers are ranked on blended cost at `CHEAPEST_IO_RATIO` input:output tokens,
named in the answer as `ranked_by`; an endpoint missing either price never wins.
Ties resolve to the first provider in catalog order.

Exit: `0` clean; `1` stale, or the authoritative entry carries `review`;
`2` no variants found.

## `query list`

All known models: tracked entries first (`baseline: false`) then discovery
entries (`baseline: true`).

Exit: `0` clean; `1` stale, or the cache has a non-empty `needs_review`;
`2` no data at all.

## `query fresh`

Freshness status only. `{freshness, fetched_at, ttl_hours, needs_review}` where
`needs_review` is the queue length.

Exit: `0` clean; `1` stale, or the queue is non-empty; `2` no cache.

## `query review`

The work list behind `needs_review`. One row per flagged entry: the price
declared in `overrides.json` against the price now being served, plus the
`reason` (`unattested-price-ignored`, `attestation-expired`, `unverifiable-price`,
`dropped-unpriceable`). A human-readable table goes to stderr; stdout stays JSON.

Clear a row by attesting the declared price (`negotiated` + `note` +
`verified_at`) or deleting `in`/`out` so the entry inherits the catalog price.

Exit: `0` empty queue; `1` non-empty; `2` no cache.

## `--offline`

Guarantee: zero network for every action. Serve cached/stale data as-is; unknown
models and empty states report honestly.

## `--ttl-hours H`

Tightens the freshness window for **this invocation only**. It gates whether the
caller sees the cache as stale; it is never stamped into the shared envelope,
because that would change every other consumer's refresh cadence.

## Auto-refresh (default, without `--offline`)

Stale/missing cache → full pipeline refresh. Stale/missing discovery sidecar →
discovery fetch. Both TTL-gated (24h default).
