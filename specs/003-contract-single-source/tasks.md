---
description: "Task list for single-sourcing the pipeline contract"
---

# Tasks: Single-sourced pipeline contract

**Input**: Design documents from `/specs/003-contract-single-source/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/contract-block.md, quickstart.md

**Revision**: Regenerated after `/speckit-analyze`. Changes: a generator (T008–T009) added
per revised `research.md` §R2, so SC-001 is achievable; T006 forced offline to stop the
suite touching the network; T020's guard restated with the §R5 recognition rules, without
which it failed on this feature's own documents.

**Tests**: This feature's deliverable *is* a test module, so "test tasks" are not optional
scaffolding — they are the implementation. Spec acceptance scenarios US1-2, US1-3 and US2-1
require proving the checker **fails** on drift, so the self-verification tasks (T011, T012,
T018–T021) are acceptance criteria, not extra coverage.

**Organization**: Grouped by user story. After Phase 2 the three stories are independent —
each governs a different document set.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3
- Exact file paths included

## Path Conventions

Single stdlib CLI plus its documentation set; there is no `src/` tree. New code lives in
`tests/test_contract_drift.py`. Governed documents are edited in place.

> **Note on `[P]`**: most implementation tasks edit the *same* file
> (`tests/test_contract_drift.py`), so they are **not** parallelisable despite being
> logically independent. `[P]` is marked almost exclusively on document-editing tasks, which
> touch distinct `.md` files. This is a real constraint of a single-module feature.

---

## Phase 1: Setup

- [ ] T001 Create `tests/test_contract_drift.py` with module docstring, stdlib imports (`json`, `re`, `unittest`, `pathlib`, `argparse`), a `REPO_ROOT` anchored to the file's parent, and one passing placeholder test; confirm `python -m unittest discover -s tests` collects it

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The fact-derivation, block-comparison and block-writing machinery every story uses.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T002 Define the `FACTS` and `GOVERNED` registries in `tests/test_contract_drift.py` per `data-model.md`: `FACTS` maps fact id → (derive, render) callables; `GOVERNED` maps repo-relative path → (role, required fact ids), with historical entries expressed as the declared path rules `specs/*/research.md` and `specs/*/spec.md`. Seed the live set empty — stories populate it
- [ ] T003 Implement `find_blocks(text)` in `tests/test_contract_drift.py` recognising a real block only when the marker is at **column 0**, **outside any fenced code block**, and carries a **known fact id** (`research.md` §R5, `contracts/contract-block.md`); return `{fact_id: body}`; raise on an unterminated or duplicated block
- [ ] T004 Implement `normalize(body)` in `tests/test_contract_drift.py` collapsing line endings and stripping per-line trailing whitespace — and nothing else, so a reworded block still fails
- [ ] T005 Implement the `exit-codes` fact in `tests/test_contract_drift.py`: derive by enumerating `fetch_pricing._exit_for(freshness, degraded)` over `{fresh,stale,no-data} × {False,True}`; render the canonical table exactly as specified in `contracts/contract-block.md`. The derivation MUST NOT read any document (`data-model.md` invariant)
- [ ] T006 Implement the `trust-rule` fact in `tests/test_contract_drift.py`: render the canonical decision procedure, then verify it operationally by asserting that for every model in `cache/pricing.json` the procedure's verdict matches the `degraded` flag from `query_main` called with **`offline=True`** and an injected fetcher that raises — the suite must never reach the network (constitution Principle V). Assert at least one `needs_review` entry is exercised, else the strongest case (SC-005) goes untested; skip cleanly with a clear message when no cache is present
- [ ] T007 Implement the assertion gate in `tests/test_contract_drift.py`: iterate `GOVERNED` live entries, compare each required block to its canonical rendering, and on mismatch fail with a message naming the path, the fact id, and the correct block verbatim
- [ ] T008 Implement the generator in `tests/test_contract_drift.py` behind an `argparse` `--fix` entry point guarded by `if __name__ == "__main__"`: rewrite canonical blocks **in place between markers only**, in registered live documents only; report rather than insert a missing block; never write an unregistered file; never run during the test run (`contracts/contract-block.md` "Generator behaviour")
- [ ] T009 Add a test in `tests/test_contract_drift.py` asserting generator idempotence: run the writer over a temp copy of a governed document twice and assert the second run produces no diff, and that bytes outside the markers are byte-identical to the original

**Checkpoint**: Machinery complete; live `GOVERNED` still empty so the suite passes. Stories can now proceed in parallel.

---

## Phase 3: User Story 1 - An agent is never told a rule the code contradicts (Priority: P1) 🎯 MVP

**Goal**: The document agents actually load cannot disagree with shipped behaviour.

**Independent Test**: Desync `SKILL.md`'s exit-code block and confirm the suite fails naming that file; reword prose outside the markers and confirm it still passes.

- [ ] T010 [US1] Insert `exit-codes` and `trust-rule` contract blocks into `skills/llm-pricing/SKILL.md`, replacing the hand-written exit-code list and trust rule; keep the "Reading the answer" narrative outside the markers
- [ ] T011 [US1] Register `skills/llm-pricing/SKILL.md` as `live` requiring `exit-codes` and `trust-rule` in `GOVERNED` in `tests/test_contract_drift.py`
- [ ] T012 [US1] Add a self-test in `tests/test_contract_drift.py` that copies `SKILL.md` to a temp dir, corrupts one block, and asserts the gate fails naming the file and fact id (spec acceptance US1-2)
- [ ] T013 [US1] Add a self-test in `tests/test_contract_drift.py` that rewrites prose *outside* the markers in a temp copy and asserts the gate still passes (spec acceptance US1-3)
- [ ] T014 [US1] Add a test in `tests/test_contract_drift.py` asserting `~/.pi/agent/skills/llm-pricing` resolves to `skills/llm-pricing` in this repo, so the governed file is the one agents load. When the symlink is absent, skip **loudly** — print `symlink unverified` to stderr so a machine without the harness cannot look identical to a verified one

**Checkpoint**: The highest-risk reader is governed. Shippable MVP — closes the only drift with demonstrated harm.

---

## Phase 4: User Story 2 - Drift is reported, not discovered by accident (Priority: P2)

**Goal**: One failure lists every live document that disagrees, and the check cannot be silently evaded.

**Independent Test**: Desync each governed spec document in turn and confirm each is named; confirm a clean tree passes; confirm historical artifacts are untouched.

- [ ] T015 [P] [US2] Replace the exit-code prose in `specs/001-pricing-query/contracts/query-cli.md` with an `exit-codes` contract block, keeping per-action prose outside the markers
- [ ] T016 [P] [US2] Replace the exit-code and trust-rule prose in `specs/001-pricing-query/quickstart.md` with `exit-codes` and `trust-rule` contract blocks
- [ ] T017 [P] [US2] Replace the exit-code prose in `specs/002-pricing-endpoints/contracts/cheapest-query.md` with an `exit-codes` contract block
- [ ] T018 [US2] Register the three documents above in `GOVERNED` in `tests/test_contract_drift.py`, then add a test asserting a live entry missing a required block **fails** — deleting a block must not be a way to opt out
- [ ] T019 [US2] Add a test in `tests/test_contract_drift.py` asserting a registered live document absent from disk **fails**, so a rename cannot silently drop coverage
- [ ] T020 [US2] Add the unregistered-marker guard in `tests/test_contract_drift.py`: walk all `*.md` under the repo (excluding `.git`), apply the `find_blocks` recognition rules from T003, and fail when a **real** block appears in a file not in `GOVERNED`. Include a test asserting this feature's own `specs/003-contract-single-source/*.md` do **not** trip the guard despite containing marker literals in prose and code fences (`research.md` §R5)
- [ ] T021 [US2] Add a test in `tests/test_contract_drift.py` asserting an unknown fact id **inside a recognised block** fails, while an unknown id in an unrecognised marker is ignored — the two rules must not be confused
- [ ] T022 [US2] Add a test in `tests/test_contract_drift.py` asserting the historical path rules exempt `specs/001-pricing-query/research.md` and `specs/00*/spec.md`, which still contain superseded rules and must pass unchanged (spec acceptance US2-3)

**Checkpoint**: All live spec documents governed; all four evasion routes closed.

---

## Phase 5: User Story 3 - Human-facing contract docs stay correct (Priority: P3)

**Goal**: `README.md` and the constitution stay correct without separate effort.

**Independent Test**: Desync the README's envelope block and confirm the suite names it.

- [ ] T023 [US3] Implement the `envelope` fact in `tests/test_contract_drift.py`: derive from `sorted(fetch_pricing.build_cache(...).keys())`, render the canonical ordered key list per `contracts/contract-block.md`
- [ ] T024 [P] [US3] Insert `exit-codes`, `envelope` and `trust-rule` contract blocks into `README.md`, replacing the hand-written schema and exit-code statements in "Consuming the cache"; register it in `GOVERNED`
- [ ] T025 [P] [US3] Insert `exit-codes` and `envelope` contract blocks into `.specify/memory/constitution.md` Principle III and Data & Schema Constraints; register it in `GOVERNED`. Keep the normative prose ("a consumer MUST NOT…") outside the markers — it is a principle, not a fact
- [ ] T026 [US3] Change the Constitution Check gate in `.specify/templates/plan-template.md` to **reference** constitution Principles I–V rather than restate them (`research.md` §R4). The template is deliberately not added to `GOVERNED` — removing a restatement beats governing one

**Checkpoint**: Every live document is either governed by a block or references the source instead of restating it.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T027 Verify SC-004 and FR-005 in `tests/test_contract_drift.py`: measure suite runtime before and after and confirm the added time is under one second; assert the module imports only stdlib packages and performs no network I/O
- [ ] T028 Verify SC-003 at `HEAD`: run `python -m unittest discover -s tests` on a clean tree and confirm zero live documents disagree; have `tests/test_contract_drift.py` report the governed-document count so coverage is visible in the run output
- [ ] T029 [P] Document the convention in `AGENTS.md`: how to add a governed document, that new documents should reference rather than restate, that historical records are exempt by declared path rule, and how to run `--fix`
- [ ] T030 Execute `specs/003-contract-single-source/quickstart.md` end to end: change an exit-code rule in `fetch_pricing.py`, confirm the suite fails naming every governed document, run `python tests/test_contract_drift.py --fix`, confirm green, then revert the rule change and re-run `--fix`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001)**: no dependencies
- **Foundational (T002–T009)**: depends on T001 — **blocks all user stories**
- **US1 (T010–T014)**, **US2 (T015–T022)**, **US3 (T023–T026)**: each depends only on Foundational; independent of one another
- **Polish (T027–T030)**: depends on the stories shipped; T030 needs at least one governed document

### Within Foundational

T002 → T003 → T004 → T005, T006 → T007 → T008 → T009. Strictly sequential: one file, each layer builds on the last. T008 (generator) depends on T007's canonical rendering; T009 verifies T008.

### User Story Dependencies

- **US1 (P1)**: after Foundational. No dependency on US2/US3.
- **US2 (P2)**: after Foundational. Reuses the `exit-codes` and `trust-rule` facts from Phase 2 — *not* from US1 — which is what keeps the stories independent.
- **US3 (P3)**: after Foundational. Adds the `envelope` fact, used by no other story.

### Parallel Opportunities

Genuinely parallel (distinct files): T015, T016, T017 · T024, T025 · T029.

Not parallel despite appearing so: everything in Phase 2, and every `tests/test_contract_drift.py` task.

Across stories: with more than one person, US1 / US2 / US3 can run concurrently after Phase 2 — each edits a disjoint document set. The shared `GOVERNED` registry is the only merge point; expect a trivial conflict there.

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
2. T002–T009 (Foundational — the bulk of the work)
3. T010–T014 (US1)
4. **STOP and VALIDATE**: corrupt a block in `SKILL.md`, confirm the suite names it; run `--fix`; confirm green
5. Ship — the reader that caused demonstrated harm is now governed

Note the shape: Foundational is eight tasks and US1 is five. That is honest for this feature — the substrate is shared and the per-story slices are small. Do not inline Phase 2 into US1; US2 and US3 both need it.

### Incremental Delivery

1. Setup + Foundational → machinery ready, live registry empty, suite green
2. + US1 → the agent-facing document is safe (MVP)
3. + US2 → all live spec documents governed, evasion routes closed
4. + US3 → human-facing documents governed; the tenth restatement deleted rather than governed

Each increment leaves the suite green and adds coverage without touching runtime code.

---

## Notes

- **No runtime code changes.** `fetch_pricing.py` is read by the checker and never modified. If a task seems to require editing it, the design has drifted — revisit `research.md` §R1.
- Derivations must never read a governed document (`data-model.md` invariant); violating this re-admits the "all documents agree and all are wrong" failure.
- The generator must never run inside the test run — a gate that repairs itself hides the drift it exists to report.
- Commit after each task or logical group; the suite should be green at every commit.
