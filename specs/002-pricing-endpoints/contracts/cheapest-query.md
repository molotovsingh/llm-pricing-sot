# Contract: Cheapest Query (Endpoints Upgrade)

Surface: `python fetch_pricing.py query cheapest <model> [--offline]`
(existing surface; answer shape extended).

Rules unchanged: one JSON object to stdout; notes to stderr. Exit codes follow the
canonical statement in `.specify/memory/constitution.md` (Principle III):
`0` clean / `1` served but degraded (stale, or the authoritative entry is in
`needs_review`) / `2` no data.

## Answer shape — endpoints path (OpenRouter-routed models)

```json
{
  "model": "kimi-k3",
  "slug": "moonshotai/kimi-k3",
  "provider": "Makora",
  "provider_tag": "makora",
  "quantization": "unknown",
  "in": 2.55,
  "out": 12.75,
  "in_cache_read": 0.25,
  "source": "openrouter-endpoints",
  "baseline": true,
  "authoritative": {"in": 3.0, "out": 15.0},
  "ranked_by": "blended-3:1",
  "variants": 17,
  "freshness": "fresh",
  "degraded": false
}
```

`authoritative` carries the override/cache price when present (what we
actually pay); `variants` is the number of provider endpoints considered.
`ranked_by` names the input:output blend used to order providers — ranking on
input price alone would let a host with cheap input and expensive output win.
`degraded` is true when the authoritative entry needs review.

## Answer shape — fallback path (no OpenRouter endpoints)

Same as the previous contract (provider variant scan), with
`source` = `litellm` or `openrouter`, `baseline: true`, and a
`fallback: true` marker to distinguish the demoted path.

## Behavior

- Slug resolution: catalog exact match → overrides `openrouter_slug` → catalog
  last-segment match → none. A **declared** `openrouter_slug` is authoritative: if
  the pin no longer resolves the result is none, never a last-segment guess, since
  prices are inherited from the resolved row.
- Endpoint snapshots TTL-gated (24h) at `cache/endpoints/<slug>.json`.
- `--offline`: snapshot served as-is (stale → exit 1); no snapshot → fallback
  scan on the cached discovery sidecar → else `found: false` exit 2.
- Endpoints fetch failure: served from snapshot if present, else fallback scan.
