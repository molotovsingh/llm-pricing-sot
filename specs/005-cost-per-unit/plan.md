# Implementation Plan: Cost per unit of work at a named deployment

**Branch**: `005-cost-per-unit` | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-cost-per-unit/spec.md`

## Summary

The catalog answers "what does the cheapest host charge per token"; the user needs "what
does *this* workload cost on *the deployment I'd actually use*" — including hosts the
catalog does not route and self-hosted models no catalog prices. The approach: **give
every price a unit; add a curated, attested `deployments.json` as the truth for cost;
derive self-host prices from an attested GPU-rate table and a benchmark measurement;
add Hugging Face's router as a second per-host catalog; and expose per-host queries.**
The catalog is demoted from source of truth to verifier, and the existing trust model —
attest, cross-check, expire, report — is generalised rather than replaced.

Two load-bearing choices, recorded in `research.md`:

- **Units are a governed vocabulary, not a free string** (R3). Defined once in code,
  derived into documents by the contract gate, rejected at validation otherwise.
- **Self-host cost is derived from attested inputs, never fetched** (R5). A GPU rate is a
  price and gets the attestation treatment; seconds-per-unit is a measurement the user's
  bench produces and this repo only records, with the run id as its attestation.

## Technical Context

**Language/Version**: Python 3.9+ (stdlib only — `urllib.request`, `json`, `argparse`, `unittest`, `re`)
**Primary Dependencies**: None. Adding any would violate constitution Principle I.
**Storage**: Files — two new truth files (`deployments.json`, `gpu_rates.json`), one new
discovery layer (`discovery.json.hf_router`), one new envelope key (`pricing.json.deployments`).
**Testing**: `python -m unittest discover -s tests` (156 tests, hermetic, 0.08 s)
**Target Platform**: Any machine running an agent harness; clone and run
**Project Type**: Single-file CLI + data files + documentation set
**Performance Goals**: Offline query cold-start unchanged (≈34 ms; the autoresearch
ruler); suite grows < 1 s (SC-005). HF fetch is one GET of ~100 KB, on the refresh path only.
**Constraints**: No network in tests (Principle V); additive envelope (R6); HF is
demoted — its failure never discards a refresh (Principle IV).
**Scale/Scope**: 5 units; ~5 seeded deployments; ~10 GPU rates; 139 HF router models ×
14 providers; 3 new query surfaces (`hosts`, `deployments`, `--host`).

## Constitution Check

*GATE: checked before Phase 0; re-checked after Phase 1 design.*

- [x] **Principle I — Stdlib-Only Python**: no new dependency. The HF fetcher is
  `urllib` behind the same injectable `fetcher` seam as every other source.
- [x] **Principle II — Single Source of Truth**: **amended, not violated** (R8). The
  truth layer becomes two files; merge precedence for `models` is untouched
  (overrides > OpenRouter catalog > LiteLLM). Deployments never merge into `models`;
  they are a parallel truth with their own catalog cross-check. Attestation rules are
  applied to deployments and GPU rates verbatim. Tokenizer gate unchanged for
  per-token entries; not applied to non-token units, which have no tokenizer by nature.
- [x] **Principle III — File + CLI Contract**: stdout/stderr split kept; every new action
  maps through `_exit_for` unchanged; a flagged deployment degrades to exit 1 exactly
  as a flagged override does.
- [x] **Principle IV — On-Demand with TTL-Gated Cache**: fresh cache = zero network is
  preserved; HF joins LiteLLM under the demoted-source rule.
- [x] **Principle V — Hermetic, Deterministic Testing**: HF payload is a fixture; all new
  actions assert exit codes; the shipped `deployments.json` and `gpu_rates.json` get
  the same shape tests `overrides.json` has.

**Post-Phase-1 re-check**: PASS with the amendment. The constitution is versioned
3.0.0 in the same change so it never describes a repo that does not exist.

## Project Structure

### Documentation (this feature)

```text
specs/005-cost-per-unit/
├── plan.md              # This file
├── research.md          # Phase 0 — R1..R8, what was found on 2026-09-08 and why
├── data-model.md        # Phase 1 — Unit, Deployment, GPU rate, Host row, envelope delta
├── quickstart.md        # Phase 1 — record a deployment; ask for a price at a host
├── contracts/
│   └── deployments-and-hosts.md   # Phase 1 — file shapes, query shapes, review reasons
└── tasks.md             # Phase 2 — T001..T0NN
```

### Source Code (repository root)

```text
fetch_pricing.py               # UNITS, deployments + gpu_rates loading/derivation/verification,
                               # fetch_hf_router + normaliser, host canonicalisation,
                               # _query_hosts / _query_deployments / --host on price & cheapest
overrides.json                 # unchanged shape; optional `hf_id` per entry
deployments.json               # NEW truth file — what we actually run, any unit, attested
gpu_rates.json                 # NEW attested table — <gpu>@<provider> → usd_per_hour
cache/
├── pricing.json               # envelope + `deployments`; models[*] + `unit`
├── discovery.json             # + `hf_router` layer
└── endpoints/                 # unchanged
tests/
├── test_fetch_pricing.py      # + units, deployments, derivation, HF normaliser, hosts, --host
└── test_contract_drift.py     # + `units` fact; envelope fact picks up `deployments` automatically

# Governed documents (blocks regenerated by `python tests/test_contract_drift.py --fix`)
README.md                      # + deployments / hosts / units sections; stale HF note corrected
skills/llm-pricing/SKILL.md    # + how to ask for a price at a host, deployments, units
.specify/memory/constitution.md  # amended to 3.0.0
specs/001-pricing-query/contracts/query-cli.md
specs/001-pricing-query/quickstart.md
specs/002-pricing-endpoints/contracts/cheapest-query.md
```

**Structure Decision**: No new module. `fetch_pricing.py` stays one file (the
clone-and-run property and the offline cold-start budget both depend on it); the query
surface was decomposed into named handlers in `374f234` precisely so new actions slot in
as functions rather than branches. New truth files sit beside `overrides.json` because
they *are* the same kind of thing — hand-held, attested, expiring — and the shipped-data
tests treat them identically.

## Sequencing

Small, additive, each step green and committed:

1. **Units + envelope + constitution** — `UNITS`, per-unit validation, `unit` on every
   model entry, empty `deployments` key, `units` contract fact, `--fix`, constitution
   3.0.0. Proves nothing breaks before anything new is priced.
2. **Deployments + GPU rates** — loaders, validators, derivation, attestation, catalog
   cross-check for per-token deployments, `query deployments`, seeded files, shipped-data
   tests.
3. **HF router** — fetch, normalise, persist as demoted layer; `hf_id` mapping; fixture
   tests including the failure path.
4. **Per-host queries** — host canonicalisation, merged host rows from both catalogs,
   `query hosts`, `--host` on `price` and `cheapest`; deployment-wins-at-host rule.
5. **Docs + acceptance** — README/SKILL, `--fix`, `checks.sh` smoke for the new actions,
   estimator end-to-end via `uv run`, cold-start ruler unchanged.

## Complexity Tracking

> No constitution violations; one amendment, justified in `research.md` §R8.

One judgment worth recording. It would be simpler to overload `in`/`out` for every unit
and let `unit` say what they mean. Rejected: the estimator and every governed document
read `in`/`out` as per-1M-token USD, and a per-page price in `in` would be silently
multiplied by a token count. Non-token units get their own field names (`price`,
`usd_per_hour`) so a consumer that does not know the unit cannot accidentally use the
number. The cheap change is the safe one here.
