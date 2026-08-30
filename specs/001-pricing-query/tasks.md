---

description: "Task list for feature implementation: Pricing Query"
---

# Tasks: Pricing Query

**Input**: Design documents from `/specs/001-pricing-query/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Hermetic tests are REQUIRED by the constitution (Principle V: the default
suite must never touch the network and must assert exit codes). Tests are written
alongside each story's implementation (not test-first; `tdd` is false).

**Organization**: Tasks are grouped by user story so each story can be implemented
and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Exact file paths in every description

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Baseline before changes.

- [x] T001 Confirm clean base: branch `001-pricing-query` checked out, `.specify/`
      initialized, existing suite green (`python -m unittest`) in `tests/`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Query plumbing that every story depends on. All in `fetch_pricing.py`.

- [x] T002 Add `import re` and `DISCOVERY_PATH` constant (next to `CACHE_PATH`) in `fetch_pricing.py`.
- [x] T003 Add discovery sidecar helpers `_emit_discovery` and `_load_discovery` in `fetch_pricing.py`.
- [x] T004 Add optional `discovery_path=None` param to `run()`; on successful refresh
      write the sidecar via `_emit_discovery` (plain pipeline behavior unchanged) in `fetch_pricing.py`.
- [x] T005 Add `query` subcommand to `parse_args` (action `price|cheapest|list|fresh`,
      optional `model`, `--offline`) preserving bare-invocation `--force`/`--ttl-hours`
      behavior, and wire `main()` to route `query` to `query_main` in `fetch_pricing.py`.
- [x] T006 Add variant-matching helpers `_normalize_model` and `_variant_matches`
      (lowercase, strip provider prefix, unify `gemini-3-7`→`gemini-3.7`, keep `:batch`
      distinct) in `fetch_pricing.py`.
- [x] T007 Add `_freshness_status` and `_exit_for` (0 fresh / 1 stale / 2 no-data) in `fetch_pricing.py`.
- [x] T008 Add `ensure_discovery` (TTL-gated discovery refresh; offline passes the
      existing sidecar through; write fresh sidecar on fetch) in `fetch_pricing.py`.

**Checkpoint**: Foundation ready — query plumbing exists but no action is wired yet.
Run `python -m unittest` to confirm no regressions.

---

## Phase 3: User Story 1 - Look up a model's price (Priority: P1) 🎯 MVP

**Goal**: `query price <model>` answers with price, source, freshness; auto-refresh
when stale; discovery fallback labeled `baseline: true`.

**Independent Test**: `python fetch_pricing.py query price kimi-k3` (cached) and
`query price gemini-3.7-flash` (fallback) each print one JSON object with correct
labeling and exit codes.

### Implementation for User Story 1

- [x] T009 [US1] Implement `query_main` orchestration in `fetch_pricing.py`: load cache,
      refresh when stale/missing unless `--offline`, compute freshness.
- [x] T010 [US1] Implement the `price` action in `query_main` (cache-first; discovery
      fallback with `baseline: true`; `found: false` + exit 2 when unknown) in `fetch_pricing.py`.
- [x] T011 [US1] Add unit tests for `price` (cached authoritative answer; discovery
      fallback labeled baseline; not-found exit 2; offline with stale cache exit 1)
      in `tests/test_fetch_pricing.py` using temp paths + fake fetchers.

**Checkpoint**: US1 functional — price lookup works end to end, hermetic tests pass.

---

## Phase 4: User Story 2 - Find the cheapest host (Priority: P2)

**Goal**: `query cheapest <model>` returns the cheapest provider variant plus the
authoritative price for context.

**Independent Test**: `python fetch_pricing.py query cheapest gemini-3.1-pro` returns
the cheapest provider among `databricks`, `deepinfra`, `google` variants.

### Implementation for User Story 2

- [x] T012 [US2] Implement the `cheapest` action in `query_main` (scan litellm +
      openrouter layers for variants via `_variant_matches`, min by `(in, out)`,
      include `authoritative` when cached) in `fetch_pricing.py`.
- [x] T013 [US2] Add unit tests for `cheapest` (provider variants incl. `databricks-gemini-3-1-pro`
      dash naming; tie handling; no-variants exit 2) in `tests/test_fetch_pricing.py`.

**Checkpoint**: US1 + US2 both work independently.

---

## Phase 5: User Story 3 - List models and check freshness (Priority: P2)

**Goal**: `query list` and `query fresh` report coverage and data age.

**Independent Test**: `python fetch_pricing.py query list --offline` lists
authoritative + baseline entries; `query fresh` reports fresh/stale/no-data.

### Implementation for User Story 3

- [x] T014 [US3] Implement the `list` action in `query_main` (authoritative entries
      first, discovery entries labeled `baseline: true`, no duplicates) in `fetch_pricing.py`.
- [x] T015 [US3] Implement the `fresh` action in `query_main` (`{freshness, fetched_at,
      ttl_hours}` with exit 0/1/2) in `fetch_pricing.py`.
- [x] T016 [US3] Add unit tests for `list` and `fresh` (labeling, staleness, no-data)
      in `tests/test_fetch_pricing.py`.

**Checkpoint**: US1 + US2 + US3 functional.

---

## Phase 6: User Story 4 - Query without network (Priority: P3)

**Goal**: `--offline` guarantees zero network on every action.

**Independent Test**: With fetchers replaced by raising fakes, every offline query
completes (cache hit / stale / not-found) and no fetcher is called.

### Implementation for User Story 4

- [x] T017 [US4] Verify and tighten offline short-circuits in `query_main`/`ensure_discovery`
      so no code path performs I/O beyond local files when `--offline` is set, in `fetch_pricing.py`.
- [x] T018 [US4] Add tests asserting zero network for all four actions under `--offline`
      (raising fake fetchers; stale cache served exit 1; unknown model exit 2)
      in `tests/test_fetch_pricing.py`.

**Checkpoint**: Offline guarantee verified for every action.

---

## Phase 7: User Story 5 - Agents discover the tool (Priority: P3)

**Goal**: A global Pi skill makes the queries discoverable and documents the contract.

**Independent Test**: The skill file exists at `~/.pi/agent/skills/llm-pricing/SKILL.md`
with a triggering description and the documented commands.

### Implementation for User Story 5

- [x] T019 [US5] Create the versioned skill copy `skills/llm-pricing/SKILL.md` in this
      repo (name `llm-pricing`, description mentioning pricing/cost, body: repo path,
      the four query commands, `--offline`, exit codes, baseline labeling, refresh command).
- [x] T020 [US5] Install the live skill at `~/.pi/agent/skills/llm-pricing/SKILL.md`
      (same content; global discovery for Pi).

**Checkpoint**: Discovery artifact in place.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Validation, documentation sync, and delivery.

- [x] T021 Run the full hermetic suite `python -m unittest` in the repo root; all
      existing + new tests pass with zero network.
- [x] T022 Manual smoke against real sources: `query price gemini-3.7-flash`,
      `query cheapest gemini-3.7-flash`, `query fresh`, `query list | head`; verify
      JSON shape, `baseline` labels, and exit codes (network allowed here only).
- [x] T023 Walk `specs/001-pricing-query/quickstart.md` commands to confirm they match
      the shipped CLI exactly.
- [x] T024 Update `spec.md` Status to Approved; commit the feature
      (`git add specs/ fetch_pricing.py tests/ skills/ && git commit`).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup. BLOCKS all user stories.
- **User Stories (Phases 3-7)**: depend on Foundational. US1 is MVP; US2-US5 add on.
- **Polish (Phase 8)**: depends on all stories.

### User Story Dependencies

- **US1 (P1)**: after Phase 2; no story dependencies.
- **US2 (P2)**: after Phase 2 (uses `ensure_discovery` + `_variant_matches` from
  Foundational; independent of US1's action).
- **US3 (P2)**: after Phase 2; independent.
- **US4 (P3)**: after US1-US3 exist (it asserts the offline behavior of all actions).
- **US5 (P3)**: after US1-US3 exist (documents working commands).

### Parallel Opportunities

- T002, T003, T006, T007 touch different regions of `fetch_pricing.py` but the same
  file — keep sequential in this single-file project; [P] markers omitted accordingly.
- US2 and US3 phases could proceed in parallel after Foundational (single developer:
  follow priority order).

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 + Phase 2 → foundation.
2. Phase 3 (US1) → `query price` end to end.
3. **STOP and VALIDATE**: price lookup hermetic tests + manual run.

### Incremental Delivery

4. Phase 4 (US2 cheapest) → validate.
5. Phase 5 (US3 list/fresh) → validate.
6. Phase 6 (US4 offline) → validate.
7. Phase 7 (US5 skill) → validate.
8. Phase 8 polish → suite + smoke + commit.

---

## Notes

- Single-module project: all CLI work lives in `fetch_pricing.py`; tests in
  `tests/test_fetch_pricing.py`.
- Hermetic tests: inject fake fetchers; never hit the network (Constitution V).
- Commit after each phase checkpoint.
- Record any deviation from plan.md in plan.md before implementing it.
