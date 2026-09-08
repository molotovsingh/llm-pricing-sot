<!--
Sync Impact Report
===================
Version change: 2.0.0 → 3.0.0 (MAJOR — two principles redefined, one data constraint replaced)
Modified principles:
  - II Single Source of Truth — the truth layer becomes two files. `overrides.json`
    keeps the tokenizer mapping and attested per-token rates; `deployments.json`
    records what we actually run — a model at a host or on our own hardware — priced
    in its native unit and attested, with self-hosted prices derived from an attested
    `gpu_rates.json` and a benchmark measurement. The catalog is demoted from source
    of truth to verifier: it cross-checks deployments where a per-token equivalent
    exists. Merge precedence for `models` is unchanged.
  - IV On-Demand with TTL-Gated Cache — the Hugging Face router joins LiteLLM as a
    demoted source: its failure reuses the last known layer and never discards an
    otherwise healthy refresh.
Modified sections:
  - Data & Schema Constraints — "Prices MUST be USD per 1M tokens" is replaced by a
    governed unit vocabulary: every price carries a `unit`; per-token prices remain
    USD per 1M tokens. The envelope gains exactly one key, `deployments`.
Added sections: none
Removed sections: none
Templates requiring updates:
  - .specify/templates/plan-template.md — gates reference principles by name; still valid ✅
  - .specify/templates/spec-template.md — no constitution references ✅
  - .specify/templates/tasks-template.md — no constitution references ✅
Follow-up TODOs:
  - Seeded `deployments.json` and `gpu_rates.json` entries carry public-page provenance
    dated 2026-09-08; the maintainer should replace them with the hosts and rates
    actually used, and the derived OCR entry's `seconds_per_unit` with a bench run.
Rationale: specs/005-cost-per-unit/research.md §R1–R8. The per-token catalog was
verified exact for proprietary and hosted open-weight models and structurally unable
to price specialist and self-hosted models, which are sold per page, per run, per
GPU-hour, flat, or not at all.
-->

# LLM Pricing SOT Constitution

## Core Principles

### I. Stdlib-Only Python (NON-NEGOTIABLE)

The pipeline MUST run on Python 3.9+ using only the standard library
(`urllib.request`, `json`, `argparse`, `unittest`). No third-party
dependencies in `fetch_pricing.py` or its tests. Rationale: the tool must run
anywhere an agent runs, with zero install step.

### II. Single Source of Truth

The truth layer is two hand-held, attested, expiring files:

- `overrides.json` carries the tokenizer/fallback mapping (no external source
  publishes one), catalog pins (`openrouter_slug`, `hf_id`), and — only where we pay
  a rate the catalog does not list — an attested per-token price.
- `deployments.json` carries **what we actually run**: a model at a named host, or on
  our own hardware, priced in its native unit. A self-hosted deployment declares no
  price; it names a GPU rate from `gpu_rates.json` and a measured `seconds_per_unit`
  with the benchmark run that produced it, and the pipeline derives the price.

The catalog is a **verifier, not the truth**. For `models`, merge precedence MUST be
overrides > OpenRouter catalog > LiteLLM; LiteLLM and the Hugging Face router are
demoted sources, community- or aggregator-maintained and known to lag. A model with no
resolvable tokenizer MUST NOT be emitted in `models` with a guessed tokenizer;
non-token deployments have no tokenizer by nature and are emitted only under
`deployments`. Catalog-sourced pricing MUST be labeled with its source and marked
`baseline: true` so consumers never confuse it with truth.

A hand-typed price is NOT automatically truth. It MUST be trusted only when the entry
attests to it (`note` + `verified_at`; `negotiated` where the rate is not public);
otherwise the pipeline MUST discard it in favour of a catalog price where one exists
at that host, keep it and report it otherwise. Attestations — on overrides,
deployments and GPU rates alike — MUST expire, or the attestation flag becomes a
permanent mute button and hand-maintained prices rot exactly as before. A derived
price MUST name every input it used and MUST NOT be emitted when an input is missing.
An entry that can be priced by no route MUST be reported, never silently dropped.

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
source failing — LiteLLM or the Hugging Face router — MUST NOT discard an
otherwise healthy refresh; its last known layer is reused and the reuse is reported.

### V. Hermetic, Deterministic Testing

The default test suite MUST never touch the network (source fetchers are
injectable; tests substitute fakes). Emitted entries MUST pass validation
(per-unit price fields present and non-negative; `tokenizer` present on
per-token model entries). Tests MUST assert exit codes and merge precedence
deterministically, and MUST pin the clock wherever attestation expiry is exercised.

## Data & Schema Constraints

The cache envelope MUST carry exactly these keys:

<!-- contract:begin envelope -->
Cache envelope keys: `deployments`, `fetched_at`, `freshness`, `models`, `needs_review`, `truth_hash`, `ttl_hours`.
<!-- contract:end envelope -->

Every price MUST carry a `unit` from this vocabulary, and a unit's price fields
MUST NOT be reused for another unit — a per-page price never appears in `in`/`out`:

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

`fetched_at` is ISO-8601 UTC. `freshness` reports age only and
MUST NOT be read as a correctness signal; `needs_review` carries the ids — model or
deployment — a human must look at. Cache writes MUST be atomic (temp file + rename),
since multiple agents read these files concurrently. Generated cache files MUST be
gitignored (regenerated on demand). The repo MUST NOT store secrets or PII; pricing,
tokenizer mappings, deployments and GPU rates are the only data.

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

**Version**: 3.0.0 | **Ratified**: 2026-08-29 | **Last Amended**: 2026-09-08
