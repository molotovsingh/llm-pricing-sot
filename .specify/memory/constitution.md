<!--
Sync Impact Report
===================
Version change: (none) → 1.0.0 (initial ratification)
Modified principles: none (first fill of all sections)
Added sections: Core Principles (I–V), Data & Schema Constraints, Development
  Workflow, Governance
Removed sections: none
Templates requiring updates:
  - .specify/templates/plan-template.md — Constitution Check gates filled ✅
  - .specify/templates/spec-template.md — no constitution references; no change ✅
  - .specify/templates/tasks-template.md — no constitution references; no change ✅
  - .specify/templates/commands/ — directory not present; N/A ✅
Follow-up TODOs: none (all placeholders resolved)
-->

# LLM Pricing SOT Constitution

## Core Principles

### I. Stdlib-Only Python (NON-NEGOTIABLE)

The pipeline MUST run on Python 3.9+ using only the standard library
(`urllib.request`, `json`, `argparse`, `unittest`). No third-party
dependencies in `fetch_pricing.py` or its tests. Rationale: the tool must run
anywhere an agent runs, with zero install step.

### II. Single Source of Truth

`overrides.json` is the truth layer: it carries what we actually pay and the
tokenizer/fallback mapping. Merge precedence MUST be overrides > LiteLLM >
OpenRouter. A model with no resolvable tokenizer MUST NOT be emitted with a
guessed tokenizer. Discovery-sourced pricing MUST be labeled with its source
and marked `baseline: true` so consumers never confuse it with truth.

### III. File + CLI Contract (No Server)

Consumers interact via a JSON file (`cache/pricing.json`) and the
`fetch_pricing.py` CLI. Machine output goes to stdout (JSON), human notes to
stderr. Exit codes MUST be deterministic: `0` fresh, `1` stale, `2` no usable
data. No HTTP API, daemon, MCP server, or long-running process is permitted.

### IV. On-Demand with TTL-Gated Cache

No cron or background refresh. A fresh cache MUST be served with zero network
I/O. A stale or missing cache triggers fetch → merge → emit. On network
failure the tool MUST serve stale cache with a staleness flag (never block),
or exit `2` when nothing usable exists.

### V. Hermetic, Deterministic Testing

The default test suite MUST never touch the network (source fetchers are
injectable; tests substitute fakes). Emitted entries MUST pass validation
(non-negative `in`/`out`, `tokenizer` present). Tests MUST assert exit codes
and merge precedence deterministically.

## Data & Schema Constraints

The cache envelope MUST be `{fetched_at, ttl_hours, freshness, models}` with
`fetched_at` in ISO-8601 UTC. Prices MUST be USD per 1M tokens. Generated
cache files MUST be gitignored (regenerated on demand). The repo MUST NOT
store secrets or PII; pricing and tokenizer mappings are the only data.

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

**Version**: 1.0.0 | **Ratified**: 2026-08-29 | **Last Amended**: 2026-08-29
