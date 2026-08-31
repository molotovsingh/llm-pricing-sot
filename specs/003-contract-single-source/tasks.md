---
description: "Task list for single-sourcing the pipeline contract"
---

# Tasks: Single-sourced pipeline contract

**Input**: Design documents from `/specs/003-contract-single-source/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/contract-block.md, quickstart.md

**Tests**: This feature's deliverable *is* a test module, so "test tasks" are not optional
scaffolding — they are the implementation. Separately, spec acceptance scenarios US1-2,
US1-3 and US2-1 require proving the checker **fails** on drift, so the self-verification
tasks (T010, T011, T016–T019) are acceptance criteria, not extra coverage.

**Organization**: Grouped by user story. After Phase 2, the three stories are genuinely
independent — each governs a different document set.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3
- Exact file paths included

## Path Conventions

Single stdlib CLI plus its documentation set; there is no `src/` tree. New code lives in
`tests/test_contract_drift.py`. Governed documents are edited in place.

> **Note on `[P]`**: most implementation tasks edit the *same* file
> (`tests/test_contract_drift.py`), so they are **not** parallelisable despite being
> logically independent. `[P]` is therefore marked almost exclusively on document-editing
> tasks, which touch distinct `.md` files. This is a real constraint of a single-module
> feature, not an oversight.

---

## Phase 1: Setup

**Purpose**: Create the module and confirm it is picked up by the existing runner.

- [ ] T001 Create `tests/test_contract_drift.py` with module docstring, stdlib imports (`json`, `re`, `unittest`, `pathlib`), a `REPO_ROOT` anchored to the file's parent, and one passing placeholder test; confirm `python -m unittest discover -s tests` collects it

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The fact-derivation and block-comparison machinery every story uses.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T002 Define the `FACTS` and `GOVERNED` registries in `tests/test_contract_drift.py` per `data-model.md`: `FACTS` maps fact id → (derive, render) callables; `GOVERNED` maps repo-relative path → (role, required fact ids). Seed `GOVERNED` empty — stories populate it
- [ ] T003 Implement `extract_block(text, fact_id)` in `tests/test_contract_drift.py` parsing `<!-- contract:begin <id> -->` / `<!-- contract:end <id> -->` per `contracts/contract-block.md`; return the body, or `None` when absent; raise on an unterminated or duplicated block
- [ ] T004 Implement `normalize(body)` in `tests/test_contract_drift.py` collapsing line endings and stripping per-line trailing whitespace — and nothing else, so a reworded block still fails
- [ ] T005 Implement the `exit-codes` fact in `tests/test_contract_drift.py`: derive by enumerating `fetch_pricing._exit_for(freshness, degraded)` over `{fresh,stale,no-data} × {False,True}`; render the canonical table exactly as specified in `contracts/contract-block.md`. The derivation MUST NOT read any document (`data-model.md` invariant)
- [ ] T006 Implement the `trust-rule` fact in `tests/test_contract_drift.py`: render the canonical decision procedure, and verify it operationally by asserting that for every model in `cache/pricing.json` the procedure's verdict matches the `degraded` flag `query_main` returns for that model; skip cleanly with a clear message when no cache is present so a fresh clone does not fail
- [ ] T007 Implement the assertion harness in `tests/test_contract_drift.py`: iterate `GOVERNED` live entries, compare each required block to its canonical rendering, and on mismatch fail with a message naming the path, the fact id, and the correct block verbatim (`contracts/contract-block.md` "Failure output is the fix")

**Checkpoint**: Machinery complete and self-consistent; `GOVERNED` still empty so the suite passes. Stories can now proceed in parallel.

---

## Phase 3: User Story 1 - An agent is never told a rule the code contradicts (Priority: P1) 🎯 MVP

**Goal**: The document agents actually load cannot disagree with shipped behaviour.

**Independent Test**: Desync `SKILL.md`'s exit-code block and confirm the suite fails naming that file; reword prose outside the markers and confirm it still passes.

- [ ] T008 [US1] Insert `exit-codes` and `trust-rule` contract blocks into `skills/llm-pricing/SKILL.md`, replacing the hand-written exit-code list and trust rule with marked blocks; keep the surrounding prose (the "Reading the answer" narrative) outside the markers
- [ ] T009 [US1] Register `skills/llm-pricing/SKILL.md` as `live` requiring `exit-codes` and `trust-rule` in the `GOVERNED` registry in `tests/test_contract_drift.py`
- [ ] T010 [US1] Add a self-test in `tests/test_contract_drift.py` that copies `SKILL.md` to a temp dir, corrupts one block, runs the comparison against the copy, and asserts it fails naming the file and fact id (spec acceptance US1-2)
- [ ] T011 [US1] Add a self-test in `tests/test_contract_drift.py` that rewrites prose *outside* the markers in a temp copy and asserts the comparison still passes (spec acceptance US1-3)
- [ ] T012 [US1] Add a test in `tests/test_contract_drift.py` asserting `~/.pi/agent/skills/llm-pricing` resolves to `skills/llm-pricing` in this repo, so the governed file is the one agents load; skip with a clear message when the symlink is absent (not every checkout has the agent harness installed)

**Checkpoint**: The highest-risk reader is governed. This alone is a shippable MVP — it closes the only drift that has caused demonstrated harm.

---

## Phase 4: User Story 2 - Drift is reported, not discovered by accident (Priority: P2)

**Goal**: One failure lists every live document that disagrees, and the check cannot be silently evaded.

**Independent Test**: Desync each governed spec document in turn and confirm each is named; confirm a clean tree passes; confirm historical artifacts are untouched.

- [ ] T013 [P] [US2] Replace the exit-code prose in `specs/001-pricing-query/contracts/query-cli.md` with an `exit-codes` contract block, keeping the per-action prose outside the markers
- [ ] T014 [P] [US2] Replace the exit-code and trust-rule prose in `specs/001-pricing-query/quickstart.md` with `exit-codes` and `trust-rule` contract blocks
- [ ] T015 [P] [US2] Replace the exit-code prose in `specs/002-pricing-endpoints/contracts/cheapest-query.md` with an `exit-codes` contract block
- [ ] T016 [US2] Register the three documents above in `GOVERNED` in `tests/test_contract_drift.py`, then add a test asserting that a live entry missing a required block **fails** — deleting a block must not be a way to opt out (`data-model.md` Registry validation)
- [ ] T017 [US2] Add a test in `tests/test_contract_drift.py` asserting that a registered live document absent from disk **fails**, so a rename cannot silently drop coverage
- [ ] T018 [US2] Add the unregistered-marker guard in `tests/test_contract_drift.py`: walk all `*.md` under the repo (excluding `.git`), and fail when a `contract:begin` marker appears in a file not in `GOVERNED` (`research.md` §R3)
- [ ] T019 [US2] Add a test in `tests/test_contract_drift.py` asserting an unknown `<fact-id>` in any block **fails** rather than being skipped, so a typo cannot silently disable a check
- [ ] T020 [US2] Add a test in `tests/test_contract_drift.py` asserting the historical artifacts `specs/001-pricing-query/research.md` and `specs/00*/spec.md` pass unchanged while still containing superseded rules (spec acceptance US2-3)

**Checkpoint**: All live spec documents governed, all four evasion routes closed.

---

## Phase 5: User Story 3 - Human-facing contract docs stay correct (Priority: P3)

**Goal**: `README.md` and the constitution stay correct without separate effort.

**Independent Test**: Desync the README's envelope block and confirm the suite names it.

- [ ] T021 [US3] Implement the `envelope` fact in `tests/test_contract_drift.py`: derive from `sorted(fetch_pricing.build_cache(...).keys())`, render the canonical ordered key list per `contracts/contract-block.md`
- [ ] T022 [P] [US3] Insert `exit-codes`, `envelope` and `trust-rule` contract blocks into `README.md`, replacing the hand-written schema and exit-code statements in the "Consuming the cache" section; register it in `GOVERNED`
- [ ] T023 [P] [US3] Insert `exit-codes` and `envelope` contract blocks into `.specify/memory/constitution.md` Principle III and the Data & Schema Constraints section; register it in `GOVERNED`. Keep the normative prose ("a consumer MUST NOT…") outside the markers — it is a principle, not a fact
- [ ] T024 [US3] Change the Constitution Check gate in `.specify/templates/plan-template.md` to **reference** constitution Principles I–V rather than restate their content, per `quickstart.md` ("the cheapest restatement is the one that does not exist"); this removes the tenth restatement instead of governing it

**Checkpoint**: Every live document is either governed by a block or references the source instead of restating it.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T025 Verify SC-004 in `tests/test_contract_drift.py`: measure suite runtime before and after; confirm the added time is under one second and that no test performs network I/O
- [ ] T026 Verify SC-003 at `HEAD`: run `python -m unittest discover -s tests` on a clean tree and confirm zero live documents disagree; have `tests/test_contract_drift.py` report the governed-document count so coverage is visible in the run output
- [ ] T027 [P] Document the convention in `AGENTS.md`: how to add a governed document, that new documents should reference rather than restate, and that historical records are exempt by registry entry
- [ ] T028 Execute `specs/003-contract-single-source/quickstart.md` end to end: change an exit-code rule in `fetch_pricing.py`, confirm the suite fails naming every governed document, paste the printed blocks, confirm green, then revert the rule change

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001)**: no dependencies
- **Foundational (T002–T007)**: depends on T001 — **blocks all user stories**
- **US1 (T008–T012)**, **US2 (T013–T020)**, **US3 (T021–T024)**: each depends only on Foundational; independent of one another
- **Polish (T025–T028)**: depends on the stories you choose to ship; T028 needs at least one governed document

### Within Foundational

T002 → T003 → T004 (registry, then extraction, then normalisation) → T005, T006 (facts) → T007 (harness consumes all of the above). Strictly sequential: one file, each layer builds on the last.

### User Story Dependencies

- **US1 (P1)**: after Foundational. No dependency on US2/US3.
- **US2 (P2)**: after Foundational. Reuses the `exit-codes` and `trust-rule` facts built in Phase 2 — *not* from US1 — which is why the stories stay independent.
- **US3 (P3)**: after Foundational. Adds the `envelope` fact, used by no other story.

### Parallel Opportunities

Genuinely parallel (distinct files):

- T013, T014, T015 — three different spec documents
- T022, T023 — README and constitution
- T027 — `AGENTS.md`, independent of the rest of Polish

Not parallel despite appearing so: everything in Phase 2 and all `tests/test_contract_drift.py` tasks share one file.

Across stories: with more than one person, US1 / US2 / US3 can run concurrently after Phase 2, since each edits a disjoint document set. Only the shared `GOVERNED` registry is a merge point — expect a trivial conflict there.

---

## Parallel Example: User Story 2

```bash
# Three document edits, three different files, no shared state:
Task: "Add exit-codes block to specs/001-pricing-query/contracts/query-cli.md"
Task: "Add exit-codes + trust-rule blocks to specs/001-pricing-query/quickstart.md"
Task: "Add exit-codes block to specs/002-pricing-endpoints/contracts/cheapest-query.md"

# Then, sequentially (all touch tests/test_contract_drift.py):
Task: "Register the three documents and assert a missing block fails"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. T001 (Setup)
2. T002–T007 (Foundational — the bulk of the work)
3. T008–T012 (US1)
4. **STOP and VALIDATE**: corrupt a block in `SKILL.md`, confirm the suite names it; revert
5. Ship — the reader that caused demonstrated harm is now governed

Note the shape: Foundational is large and US1 is thin. That is honest for this feature — the substrate is shared, and the per-story slices are small. Do not be tempted to skip Phase 2 by inlining it into US1; US2 and US3 both need it.

### Incremental Delivery

1. Setup + Foundational → machinery ready, `GOVERNED` empty, suite green
2. + US1 → the agent-facing document is safe (MVP)
3. + US2 → all live spec documents governed, evasion routes closed
4. + US3 → human-facing documents governed; the tenth restatement deleted rather than governed

Each increment leaves the suite green and adds coverage without touching runtime code.

---

## Notes

- **No runtime code changes.** `fetch_pricing.py` is read by the checker and never modified. If a task seems to require editing it, the design has drifted — stop and revisit `research.md` §R1.
- The derivations must never read a governed document (`data-model.md` invariant). Violating this re-admits the "all documents agree and all are wrong" failure the feature exists to prevent.
- Commit after each task or logical group; the suite should be green at every commit.
- Constitution gates re-checked in `plan.md`: stdlib-only, no network in tests, no new CLI surface. Every task above stays inside them.
