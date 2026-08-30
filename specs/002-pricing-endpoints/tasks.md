---

description: "Task list for feature implementation: Pricing Endpoints Upgrade"
---

# Tasks: Pricing Endpoints Upgrade

**Input**: Design documents from `/specs/002-pricing-endpoints/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Hermetic tests are REQUIRED by the constitution (Principle V).

**Organization**: Tasks grouped by user story; each story independently testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Exact file paths in every description

---

## Phase 1: Setup (Shared Infrastructure)

- [x] T001 Confirm base: branch `002-pricing-endpoints`, existing suite green
      (`python -m unittest`) with the shipped `001-pricing-query` code.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Endpoint plumbing all stories depend on. All in `fetch_pricing.py`
unless noted.

- [x] T002 Add `ENDPOINTS_CACHE_DIR` constant (`cache/endpoints`) and
      `_endpoint_snapshot_path(slug)` helper in `fetch_pricing.py`.
- [x] T003 Add endpoint snapshot helpers `_emit_endpoint_snapshot` and
      `_load_endpoint_snapshot` (envelope `{fetched_at, ttl_hours, slug, endpoints}`)
      in `fetch_pricing.py`.
- [x] T004 Add `_normalize_openrouter` extensions: capture `input_cache_read`,
      `input_cache_write` (via `_to_price_per_1m`) and `has_pricing_overrides`
      flag from the pricing block, in `fetch_pricing.py`.
- [x] T005 Add `_openrouter_slug(models_catalog, model, overrides)` resolver:
      catalog exact match → override `openrouter_slug` → None, in `fetch_pricing.py`.
- [x] T006 Add `fetch_endpoints(slug, fetcher)` (GET
      `https://openrouter.ai/api/v1/models/{slug}/endpoints`, tolerant extraction
      of `provider_name`, `tag`, `quantization`, `pricing.prompt/completion/
      input_cache_read`) with injectable fetcher, in `fetch_pricing.py`.

**Checkpoint**: Endpoint plumbing in place; suite still green.

---

## Phase 3: User Story 1 - Cheapest host from OpenRouter endpoints (Priority: P1) 🎯 MVP

**Goal**: `query cheapest` answers from `/endpoints` (provider, price,
quantization, cache-read) with TTL-cached snapshots and LiteLLM fallback.

**Independent Test**: `query cheapest kimi-k3` names a provider from the
endpoints API; `query cheapest glm-5.2` (vendor-direct) falls back to LiteLLM.

### Implementation for User Story 1

- [x] T007 [US1] Implement `ensure_endpoints(model, offline, ...)` in
      `fetch_pricing.py`: resolve slug → serve fresh snapshot → fetch when stale
      (online) → write snapshot; returns `(slug, endpoints, freshness)` or fallback
      signal (no slug / fetch failure).
- [x] T008 [US1] Rewrite the `cheapest` action in `query_main` to prefer the
      endpoints path (min by `in` then `out`; include `provider_name`,
      `quantization`, `in_cache_read`, `variants`, `authoritative`), falling back
      to the existing variant scan with `fallback: true`, in `fetch_pricing.py`.
- [x] T009 [US1] Add unit tests: endpoints cheapest with quantization; snapshot
      cache hit = zero network (raising fetchers); snapshot stale + online → refetch;
      no-slug → fallback scan; endpoints fetch failure → snapshot/fallback behavior;
      offline with snapshot → exit per freshness, in `tests/test_fetch_pricing.py`.

**Checkpoint**: US1 functional end to end, hermetic tests pass.

---

## Phase 4: User Story 2 - Richer baseline fields (Priority: P2)

**Goal**: Discovery baseline carries cache-read/write prices; nothing else changes.

**Independent Test**: OpenRouter baseline entries include `in_cache_read` /
`in_cache_write` for models that expose them; existing suite unaffected.

### Implementation for User Story 2

- [x] T010 [US2] Add unit tests for the `_normalize_openrouter` extensions
      (cache fields present/absent, `has_pricing_overrides`), in
      `tests/test_fetch_pricing.py`.
- [x] T011 [US2] Run the full suite; confirm zero regressions across the
      authoritative cache, pipeline, and query paths.

**Checkpoint**: Baseline data capture verified with no regressions.

---

## Phase 5: User Story 3 - Source roles documented (Priority: P3)

**Goal**: README roles updated; skill gains the MCP role-split note.

**Independent Test**: README sources table and the skill file state the new
roles; MCP note says interactive-only.

### Implementation for User Story 3

- [x] T012 [US3] Update the README sources table and caveats (OpenRouter
      endpoints = cheapest host; LiteLLM = fallback/cross-check for vendor-direct)
      in `README.md`.
- [x] T013 [US3] Add the MCP role-split note to `skills/llm-pricing/SKILL.md`
      and sync the live copy to `~/.pi/agent/skills/llm-pricing/SKILL.md`.

**Checkpoint**: Documentation matches the shipped behavior.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T014 Run the full hermetic suite `python -m unittest`; all tests pass with
      zero network.
- [x] T015 Manual smoke against real sources: `query cheapest kimi-k3`,
      `query cheapest glm-5.2` (fallback), repeat cheapest to confirm cache hit,
      `query cheapest <model> --offline`; verify JSON shape and exit codes
      (network allowed here only).
- [x] T016 Walk `specs/002-pricing-endpoints/quickstart.md` commands to confirm
      they match the shipped CLI.
- [x] T017 Update `spec.md` Status to Approved; commit the feature.

---

## Dependencies & Execution Order

- **Setup (P1)** → **Foundational (P2)** blocks all stories.
- **US1 (P1)** after Foundational; **US2 (P2)** after Foundational (independent);
  **US3 (P3)** after US1 (documents its behavior).
- **Polish** after all stories.

### Parallel Opportunities

- US2's tests could run in parallel with US1 implementation (different concerns);
  single developer follows priority order.

---

## Implementation Strategy

### MVP First

1. Phase 1 + 2 → foundation.
2. Phase 3 (US1) → endpoints-based cheapest.
3. **STOP and VALIDATE**: hermetic tests + manual smoke.

### Incremental Delivery

4. Phase 4 (US2) baseline fields → validate.
5. Phase 5 (US3) docs/skill → validate.
6. Phase 6 polish → suite + smoke + commit.

---

## Notes

- Single-module project: all code in `fetch_pricing.py`; tests in
  `tests/test_fetch_pricing.py`.
- Hermetic: inject fake fetchers; never hit the network (Constitution V).
- Commit after each phase checkpoint.
- Record any deviation from plan.md in plan.md before implementing it.
