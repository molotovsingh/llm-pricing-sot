# Contract: Pricing Query CLI

Surface: `python fetch_pricing.py query <action> [model] [--offline]`

Rules: one JSON object to stdout per invocation; human notes/errors to stderr;
exit codes `0` fresh / `1` stale / `2` no data (includes "not found").

## `query price <model>`

Answer the model's price. Cache-first (authoritative, `baseline: false`);
discovery-fallback (`baseline: true`, no `tokenizer`); `found: false` if unknown.

Exit: `0` fresh answer; `1` stale answer served; `2` not found / no data.

## `query cheapest <model>`

Cheapest provider-hosted variant of the model (discovery layers), plus the
authoritative price for context when present. Variant matching per
`research.md` R1.

Exit: `0` fresh; `1` stale; `2` no variants found.

## `query list`

All known models: authoritative entries first (`baseline: false`) then discovery
entries (`baseline: true`).

Exit: `0` fresh; `1` stale; `2` no data at all.

## `query fresh`

Freshness status only. `{freshness, fetched_at, ttl_hours}`.

Exit: `0` fresh; `1` stale; `2` no cache.

## `--offline`

Guarantee: zero network for every action. Serve cached/stale data as-is; unknown
models and empty states report honestly.

## Auto-refresh (default, without `--offline`)

Stale/missing cache → full pipeline refresh. Stale/missing discovery sidecar →
discovery fetch. Both TTL-gated (24h default).
