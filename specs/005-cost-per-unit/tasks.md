# Tasks: Cost per unit of work at a named deployment

**Input**: Design documents from `/specs/005-cost-per-unit/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Requested by the spec (FR-013, SC-004, SC-005). Each story's tests are
written to fail first, in the existing hermetic suite.

**Organization**: by user story, in the sequencing order plan.md fixes. Every phase
ends green and committed.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Foundational — units, envelope, constitution (US1) 🎯

**Goal**: every price carries a unit; the envelope gains `deployments`; nothing that
worked yesterday changes.

- [x] T001 [US1] Add `UNITS` to `fetch_pricing.py`: ordered mapping unit → price fields,
      with a docstring stating the vocabulary is governed.
- [x] T002 [US1] `validate_entry`: require `unit` (default `per_1m_tokens` for legacy
      entries), validate per unit, reject unknown units and foreign price fields.
- [x] T003 [US1] Stamp `unit: "per_1m_tokens"` on every merged model entry in `run()`
      before validation; `build_cache` gains `deployments=None` → `{}`.
- [x] T004 [P] [US1] Tests: `TestUnits` — vocabulary shape, per-unit validation,
      unknown unit rejected, legacy entry defaults, envelope key present and empty.
- [x] T005 [US1] `tests/test_contract_drift.py`: `render_units()` from `UNITS`; register
      `units` in `FACTS`; add to `GOVERNED` for `README.md`, `SKILL.md`, constitution,
      and the 005 contract; `derive_envelope` picks up `deployments` unchanged.
- [x] T006 [US1] Amend `.specify/memory/constitution.md` → 3.0.0 with Sync Impact Report:
      Principle II (two-file truth layer), Principle IV (HF demoted), Data constraints
      (unit vocabulary via governed block replaces "MUST be USD per 1M tokens").
- [x] T007 [US1] Insert `units` marker blocks in the governed docs; run
      `python tests/test_contract_drift.py --fix`; suite green.

**Checkpoint**: cache regenerated; every `models[*]` has `unit`; estimator still runs.

## Phase 2: Deployments and GPU rates (US2)

**Goal**: what the user actually runs is the truth, in its native unit, attested,
derived where self-hosted, cross-checked where a catalog exists.

- [x] T008 [US2] `load_deployments(path)` and `load_gpu_rates(path)` mirroring
      `load_overrides` (underscore keys are docs; missing/corrupt → `{}`).
- [x] T009 [US2] `validate_deployment(entry)` per data-model.md; `deployment_attestation_state`
      (note + parseable verified_at; expiry via `ATTESTATION_MAX_AGE_DAYS`).
- [x] T010 [US2] `derive_deployment_price(entry, gpu_rates, now)` →
      `usd_per_hour × seconds_per_unit / 3600`, attaching `rate`; reasons
      `gpu-rate-missing`, `gpu-rate-expired`, `bench-missing`.
- [x] T011 [US2] `resolve_deployments(deployments, gpu_rates, host_rows_for, now)` →
      emitted dict: quoted vs derived, attestation, `unattested-deployment` rule
      (catalog at host replaces; else keep), `catalog` + `drift` for per-token quoted
      entries at a catalog host.
- [x] T012 [US2] Wire into `run()`: deployments resolved every refresh, emitted under
      `deployments`, ids rolled into `needs_review`, warnings to stderr, exit 1 when
      flagged (cache-hit path re-reports, as for models).
- [x] T013 [US2] `_query_deployments(ctx)` + `parse_args` choice `deployments`; stderr
      table via `_print_review_table`-style helper.
- [x] T014 [P] [US2] Seed `gpu_rates.json` from research.md §R5 (RunPod Secure Cloud,
      Modal), each with note + `verified_at: 2026-09-08`.
- [x] T015 [P] [US2] Seed `deployments.json`: quoted `kimi-k3@together`,
      `glm-5.2@together`, `glm-5.2@baseten`, `deepseek-v4-pro-0813@together` (research.md
      §R1, verified 2026-09-08); derived `deepseek-ocr@self-host` on `l40s@runpod`
      with `seconds_per_unit: 15` sourced from Replicate's published typical run time,
      note saying so and that a bench run should replace it.
- [x] T016 [P] [US2] Tests: `TestDeployments*` — load, validate, derive math, missing/
      expired rate, bench missing, attestation expiry, unattested with/without catalog,
      drift, `query deployments` exit codes; `TestShippedDeploymentsFile`,
      `TestShippedGpuRatesFile` (shape + attestation completeness, clock pinned).

**Checkpoint**: `query deployments` lists five entries; the derived one shows
`≈ $0.0045/page` on `l40s@runpod`; suite green.

## Phase 3: Hugging Face router (US3)

**Goal**: a second per-host catalog, demoted.

- [x] T017 [US3] `HF_ROUTER_URL`; `_normalize_hf_router(data)` → `{hf_id: {canonical_host:
      {in,out,context_length,status}}}`; providers without pricing kept priceless.
- [x] T018 [US3] `fetch_hf_router(url, fetcher)`; `run()` and `ensure_discovery` fetch it
      with LiteLLM's failure semantics (`_last_known_layer(..., "hf_router")`, warning).
- [x] T019 [US3] `_emit_discovery`/`_load_discovery`: add `hf_router` (tolerate absence).
- [x] T020 [US3] `overrides.json`: add `hf_id` to kimi-k3, glm-5.2, deepseek-v4-pro,
      claude-*, gpt-* where a Hub id exists; `TestShippedOverridesFile` asserts shape.
- [x] T021 [P] [US3] Tests: `TestHfRouter` — normaliser on a fixture payload, priceless
      provider retained, fetch failure reuses last layer and refresh succeeds, older
      discovery.json without the layer still loads.

**Checkpoint**: `discovery.json.hf_router` populated; suite green; offline query
cold-start unchanged.

## Phase 4: Per-host queries (US4)

**Goal**: the price at *my* host.

- [x] T022 [US4] `canonical_host(name)` + `HOST_ALIASES`; tests for every form in
      data-model.md.
- [x] T023 [US4] `host_rows(ctx, model)` → merged rows from the endpoints snapshot and
      `hf_router` (via `hf_id`), canonicalised, `source` per row, sorted by
      `_blended_cost`; priceless rows last and never candidates.
- [x] T024 [US4] `_query_hosts(ctx, model)`; `parse_args` choice `hosts`.
- [x] T025 [US4] `--host` on `query` parser; `_query_price` resolution order
      deployment → catalog row → not found; `_query_cheapest` restricts candidates.
- [x] T026 [P] [US4] Tests: `TestQueryHosts`, `TestQueryPriceHost`,
      `TestQueryCheapestHost` — merge, canonicalisation, deployment wins, baseline
      fallback, not-found exit 2, priceless host never cheapest, two SKUs at one host.

**Checkpoint**: SC-001 holds — `query price glm-5.2 --host together` = 1.40/4.40.

## Phase 5: Polish & acceptance

- [x] T027 [P] README.md: deployments / hosts / units sections; CLI surface; file tree;
      envelope example; correct the stale "router API is auth-walled" note.
- [x] T028 [P] skills/llm-pricing/SKILL.md: `hosts`, `--host`, `deployments`, units.
- [x] T029 Run `python tests/test_contract_drift.py --fix`; suite green; grep for
      ungoverned restatements of the unit vocabulary.
- [x] T030 `autoresearch.checks.sh`: offline smoke for `hosts`, `deployments`,
      `price --host`.
- [x] T031 Acceptance: `uv run` the estimator end-to-end (SC-003); cold-start ruler
      (`autoresearch.sh` bench) within noise of 34 ms.
- [x] T032 `claude_review/` delta report at the final commit.

## Dependencies

Phase 1 blocks all. Phase 2 and Phase 3 are independent of each other; Phase 4 needs
both for full coverage but is testable with either. Phase 5 last.
