# Implementation Plan: Single-sourced pipeline contract

**Branch**: `003-contract-single-source` | **Date**: 2026-08-31 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-contract-single-source/spec.md`

## Summary

Three normative facts — exit-code meanings, cache envelope schema, and the trust rule —
are restated across ten locations with no authoritative source, so a behaviour change
silently leaves some readers wrong. The approach: **derive the facts from the running code**,
embed them as a marked, machine-comparable block in each governed document, and **assert
agreement in the existing test suite** rather than generating documents. Prose stays
hand-written; only the marked blocks are governed. A failure names the file and prints the
correct block, so fixing drift is mechanical.

Anchoring to code rather than to a canonical document is the load-bearing choice: it also
catches the case where every document agrees with each other and all of them are wrong.

## Technical Context

**Language/Version**: Python 3.9+ (stdlib only — `unittest`, `json`, `re`, `pathlib`)
**Primary Dependencies**: None. Adding any would violate constitution Principle I.
**Storage**: Files — markdown documents plus `fetch_pricing.py` as the fact source. No database.
**Testing**: `python -m unittest discover -s tests` (existing suite, 120 tests, hermetic)
**Target Platform**: Any machine running an agent harness; no install step (`clone and run`)
**Project Type**: Single-file CLI + its documentation set
**Performance Goals**: The drift check adds < 1s to the suite (SC-004); it is pure file I/O and string comparison over ~6 documents
**Constraints**: No network in tests (Principle V); no build step or codegen pipeline; documents must remain human-editable and human-readable
**Scale/Scope**: 3 normative fact groups × 6 governed documents; 2 historical artifacts explicitly exempt

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **Stdlib-only**: the checker is a `unittest` test using `re`/`json`/`pathlib`. No new dependency.
- [x] **File + CLI contract**: no server/daemon added. The pipeline's stdout/stderr split and exit codes are untouched — this feature *documents* them, it does not change them.
- [x] **SOT precedence honored**: not affected. (See note below — the template's own gate text is stale.)
- [x] **On-demand TTL gate preserved**: not affected; the checker reads files only and performs zero network I/O.
- [x] **Hermetic tests**: the checker is pure file I/O over repo-local paths, deterministic, no network.

> **Gate text defect found while filling this section.** The gate above, as shipped in
> `.specify/templates/plan-template.md`, reads *"overrides > LiteLLM > OpenRouter"*. The
> constitution was amended to **overrides > OpenRouter catalog > LiteLLM** in `234dc5f`
> (v2.0.0, Principle II), so the template has been stating a superseded rule to every
> feature planned since. This is a tenth instance of the exact problem this feature
> addresses, discovered by using the template. Corrected as part of this work and recorded
> in `research.md` §R4; the template is added to the governed set.

**Post-Phase-1 re-check**: PASS. The design adds one test module and marked blocks inside
existing documents. No new dependency, no runtime behaviour change, no network.

## Project Structure

### Documentation (this feature)

```text
specs/003-contract-single-source/
├── plan.md              # This file
├── research.md          # Phase 0 — the three clarifications, resolved
├── data-model.md        # Phase 1 — normative fact, contract block, governed registry
├── quickstart.md        # Phase 1 — how to change a contract rule, and what fails if you don't
├── contracts/
│   └── contract-block.md  # Phase 1 — block syntax, fact set, checker failure output
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

This repo is a single stdlib CLI plus its documentation set; there is no `src/` tree. The
feature touches one new test module and adds marked blocks to existing documents.

```text
fetch_pricing.py                       # unchanged — the source of the facts, read by the checker
tests/
├── test_fetch_pricing.py              # unchanged (120 tests)
└── test_contract_drift.py             # NEW — derives facts from code, asserts each governed block

# Governed documents (gain a marked block; prose untouched)
README.md
skills/llm-pricing/SKILL.md
.specify/memory/constitution.md
.specify/templates/plan-template.md
specs/001-pricing-query/contracts/query-cli.md
specs/001-pricing-query/quickstart.md
specs/002-pricing-endpoints/contracts/cheapest-query.md

# Explicitly exempt (historical records — must NOT be updated)
specs/001-pricing-query/research.md
specs/00*/spec.md
```

**Structure Decision**: No new package or module layout. The checker lives beside the
existing suite as `tests/test_contract_drift.py` so it runs under the same
`python -m unittest discover -s tests` invocation the constitution's Development Workflow
already mandates — no new command for a maintainer to remember, and CI coverage is automatic.

## Complexity Tracking

> No constitution violations. Table intentionally empty.

The one judgment worth recording is a deliberate *non*-choice: generating documents from a
template engine was rejected (see `research.md` §R2) because it would add a build step to a
repo whose stated property is clone-and-run, and would make hand-written prose partly
machine-owned for a benefit — preventing rather than detecting drift — that the assert
approach substantially delivers at a fraction of the cost.
