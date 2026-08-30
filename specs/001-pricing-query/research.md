# Phase 0 Research: Pricing Query

All open items resolved. Decisions below.

## R1. Variant matching for `cheapest`

- **Decision**: Normalize both sides (lowercase; strip provider prefix at the last
  `/`; unify version dashes `gemini-3-7` → `gemini-3.7` via regex
  `-(\d+)-(\d+)(?=$|[-.])`), then suffix-match: `norm(entry).endswith(norm(query))`.
  `:batch` suffixes are preserved so batch prices never match interactive prices.
- **Rationale**: LiteLLM/OpenRouter spell the same model many ways
  (`databricks/databricks-gemini-3-1-pro`, `deepinfra/google/gemini-3.7-flash`,
  `gemini-3-7-flash`). A conservative suffix match recognizes provider-hosted
  variants without matching unrelated families (spec assumption: tolerates
  formatting, not renames).
- **Alternatives considered**: exact-id only (misses nearly all provider variants —
  kills the feature); full fuzzy/token similarity (dependency + false positives —
  rejected).

## R2. Discovery sidecar (`cache/discovery.json`)

- **Decision**: Persist the normalized OpenRouter + LiteLLM layers with
  `fetched_at`/`ttl_hours` in a sidecar, TTL-gated with the same default (24h).
  Written on a successful pipeline refresh (optional `discovery_path` param on
  `run()`, default off so the plain pipeline is unchanged) and by the query's
  own `ensure_discovery` when a fallback needs fresh layers.
- **Rationale**: Without it, every uncached-model or cheapest query would re-fetch
  two sources (seconds, rate-limit exposure). One fetch serves many queries.
- **Alternatives considered**: re-fetch per query (slow, violates SC-001);
  fold discovery into the merged cache (breaks the tokenizer-drop contract and
  the baseline/truth distinction).

## R3. Auto-refresh semantics

- **Decision**: `query` first checks the merged cache; stale/missing cache and not
  `--offline` → run the existing `run()` (fetch both sources, merge, emit cache,
  write sidecar). Discovery fallback (uncached model / cheapest) uses the sidecar;
  if it is stale/missing and not `--offline` → fetch discovery layers once and
  persist. `--offline` performs zero network in every path.
- **Rationale**: cache-first preserves "what we actually pay" as the primary
  answer; discovery answers are always labeled `baseline: true`. Offline is a
  hard guarantee, not a hint.
- **Alternatives considered**: refresh discovery on every query (network-heavy);
  never refresh (stale answers forever).

## R4. CLI shape and backward compatibility

- **Decision**: argparse subparsers: bare `fetch_pricing.py [--force] [--ttl-hours]`
  unchanged; new `fetch_pricing.py query <action> [model] [--offline]`. `query`
  answers print one JSON object to stdout; notes/errors to stderr; exit codes
  `0` fresh / `1` stale / `2` no data (not-found uses `2` with `found: false`).
- **Rationale**: existing consumers (llm-cost-estimator) call the bare command and
  depend on its exit codes — must not break. One entrypoint keeps the SOT logic
  in one place.
- **Alternatives considered**: separate script (duplicates core, two contracts);
  new flags on the bare command (muddies pipeline vs query semantics).

## R5. Agent discovery (skill)

- **Decision**: A Pi skill `llm-pricing` at `~/.pi/agent/skills/llm-pricing/SKILL.md`
  with a triggering `description` (pricing/cost keywords) and a body documenting
  the repo path, the four queries, `--offline`, exit codes, and the baseline
  labeling. Pi's skills system loads descriptions into the system prompt at
  startup; full instructions load on demand (progressive disclosure).
- **Rationale**: Pi has no built-in MCP; skills are its native discovery
  mechanism. A repo-local copy (`skills/llm-pricing/SKILL.md`) is versioned; the
  live file lives in the global skills dir so it works from any project.
- **Alternatives considered**: MCP server (Pi doesn't natively consume it;
  adds a daemon — constitution violation); README-only (no discovery);
  project-local `.pi/skills/` (only loads inside this repo — wrong scope).

## R6. Agent context

- **Decision**: Run `.specify/scripts/bash/update-agent-context.sh generic` after
  Phase 1 so agent-specific context files pick up the new technology surface.
- **Rationale**: keeps the harness's project context in sync with the plan.
- **Alternatives considered**: manual edits (error-prone).
