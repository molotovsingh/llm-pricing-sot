<!--
Sync Impact Report
===================
Version change: 1.0.0 → 2.0.0 (MAJOR — two principles redefined)
Modified principles:
  - II Single Source of Truth — merge precedence corrected to
    overrides > OpenRouter catalog > LiteLLM. v1.0.0 ranked LiteLLM above
    OpenRouter, which spec 002 ("demote LiteLLM to fallback cross-check")
    superseded without the constitution being amended; the README build-status
    line and the code disagreed with it too. Also adds the attestation rule:
    a hand-typed price is trusted only when attested.
  - III File + CLI Contract — exit 1 redefined from "stale" to the broader
    "served but degraded" (stale cache OR entries needing review), so a
    consumer cannot use an unverified price while seeing a success code.
  - IV On-Demand with TTL-Gated Cache — clarifies that only the load-bearing
    source failing forces the stale path.
Added sections: none
Removed sections: none
Templates requiring updates:
  - .specify/templates/plan-template.md — Constitution Check gates still valid ✅
  - .specify/templates/spec-template.md — no constitution references ✅
  - .specify/templates/tasks-template.md — no constitution references ✅
Follow-up TODOs:
  - Ratification of this amendment is the maintainer's call; it was drafted to
    stop the constitution from contradicting shipped behaviour, not to decide
    policy.
-->

# LLM Pricing SOT Constitution

## Core Principles

### I. Stdlib-Only Python (NON-NEGOTIABLE)

The pipeline MUST run on Python 3.9+ using only the standard library
(`urllib.request`, `json`, `argparse`, `unittest`). No third-party
dependencies in `fetch_pricing.py` or its tests. Rationale: the tool must run
anywhere an agent runs, with zero install step.

### II. Single Source of Truth

`overrides.json` is the truth layer: it carries the tokenizer/fallback mapping
(no external source publishes one) and, where applicable, what we actually pay.
Merge precedence MUST be overrides > OpenRouter catalog > LiteLLM; LiteLLM is a
demoted fallback/cross-check, since it is community-maintained and carries stale
rows. A model with no resolvable tokenizer MUST NOT be emitted with a guessed
tokenizer. Discovery-sourced pricing MUST be labeled with its source and marked
`baseline: true` so consumers never confuse it with truth.

A hand-typed price is NOT automatically truth. It MUST be trusted only when the
entry attests to it (`negotiated` + `note` + `verified_at`); otherwise the
pipeline MUST discard it in favour of the catalog price and report the entry.
Attestations MUST expire, or the attestation flag becomes a permanent mute
button and hand-maintained prices rot exactly as before. An override that can be
priced by neither route MUST be reported, never silently dropped.

### III. File + CLI Contract (No Server)

Consumers interact via a JSON file (`cache/pricing.json`) and the
`fetch_pricing.py` CLI. Machine output goes to stdout (JSON), human notes to
stderr. Exit codes MUST be deterministic:

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

Degraded covers a stale cache *and* entries the pipeline could not verify — a
consumer MUST NOT be able to use an unverified price while seeing a success code.
Degradation MUST be reported on the cache-hit path too, or it goes silent for the
length of the TTL window. No HTTP API, daemon, MCP server, or long-running
process is permitted.

### IV. On-Demand with TTL-Gated Cache

No cron or background refresh. A fresh cache MUST be served with zero network
I/O. A stale or missing cache triggers fetch → merge → emit. When the
load-bearing source (the OpenRouter catalog, which slug resolution and price
inheritance both read) is unreachable, the tool MUST serve stale cache with a
staleness flag (never block), or exit `2` when nothing usable exists. A demoted
source failing MUST NOT discard an otherwise healthy refresh.

### V. Hermetic, Deterministic Testing

The default test suite MUST never touch the network (source fetchers are
injectable; tests substitute fakes). Emitted entries MUST pass validation
(non-negative `in`/`out`, `tokenizer` present). Tests MUST assert exit codes
and merge precedence deterministically.

## Data & Schema Constraints

The cache envelope MUST carry exactly these keys:

<!-- contract:begin envelope -->
Cache envelope keys: `fetched_at`, `freshness`, `models`, `needs_review`, `ttl_hours`.
<!-- contract:end envelope -->

`fetched_at` is ISO-8601 UTC. `freshness` reports age only and
MUST NOT be read as a correctness signal; `needs_review` carries the ids a human
must look at. Prices MUST be USD per 1M tokens. Cache writes MUST be atomic
(temp file + rename), since multiple agents read these files concurrently.
Generated cache files MUST be gitignored (regenerated on demand). The repo MUST
NOT store secrets or PII; pricing and tokenizer mappings are the only data.

## Development Workflow

Changes MUST be small, additive, and validated before being marked done: run
the repo test suite (`python -m unittest` in the pipeline repo; the venv
python in `llm-cost-estimator`). The pipeline/consumer contract
(`--pricing-dir` / `LLM_PRICING_SOT_DIR`) MUST stay in sync across repos.
Feature work follows the spec-kit flow documented in `AGENTS.md`.

## Governance

This constitution supersedes ad-hoc practices. Amendments MUST be explicit,
documented, and version-bumped: MAJOR for principle removals or
redefinitions, MINOR for new principles or materially expanded guidance,
PATCH for clarifications. Every change MUST verify compliance against all
principles before merging. Runtime development guidance lives in `AGENTS.md`.

**Version**: 2.0.0 | **Ratified**: 2026-08-29 | **Last Amended**: 2026-08-31
