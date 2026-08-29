# LLM Pricing Pipeline Tasks

Spec: `llm-pricing-pipeline`  
Status: implementation-complete  
Created: 2026-08-29  
Brainstorm: `./brainstorm.md`
Requirements: `./requirements.md`
Design: `./design.md`

## Implementation Plan

Only include implementation tasks after requirements and design are accepted. Keep tasks small, ordered, and traceable.

- [x] 1. Scaffold the module and CLI entrypoint
  - ID: T-001
  - Requirement(s): FR-001, FR-010
  - Files/areas: `fetch_pricing.py` (module skeleton, `argparse` with `--force`, `--ttl-hours` default 24, `def main(argv=None)`)
  - Validation: `python fetch_pricing.py --help`; unit test that defaults and overrides parse correctly.

- [x] 2. Implement `load_overrides(path)`
  - ID: T-002
  - Requirement(s): FR-001, FR-009
  - Files/areas: `fetch_pricing.py`
  - Validation: unit test — missing/empty file returns empty layer; happy path returns parsed entries keyed by `model_id`.

- [x] 3. Implement source fetchers (`fetch_openrouter`, `fetch_litellm`) with injectable fetcher
  - ID: T-003
  - Requirement(s): FR-003, NFR-002
  - Files/areas: `fetch_pricing.py` (URL constants + `fetcher` param, default `urllib.request.urlopen` wrapper)
  - Validation: unit test with a fake fetcher returns parsed JSON; assert the real network path is never reached in default tests.

- [x] 4. Implement `merge(layers)` — per-field deep merge with precedence overrides > LiteLLM > OpenRouter
  - ID: T-004
  - Requirement(s): FR-001, FR-007
  - Files/areas: `fetch_pricing.py`
  - Validation: unit test — same `model_id` in multiple layers resolves top-down; a partial override inherits omitted fields from the next layer.

- [x] 5. Implement `validate_entry(entry)` and the batch validator
  - ID: T-005
  - Requirement(s): FR-001, NFR-005, FR-005
  - Files/areas: `fetch_pricing.py`
  - Validation: unit test — accepts non-negative `in`/`out` + present `tokenizer`; rejects negative prices, missing tokenizer, non-numeric; also validates each `alternatives[]` entry has non-negative `in`/`out`.

- [x] 6. Implement TTL / freshness logic (`is_fresh`)
  - ID: T-006
  - Requirement(s): FR-002, FR-006, FR-008
  - Files/areas: `fetch_pricing.py`
  - Validation: unit test — within TTL = fresh; exactly at TTL boundary = stale; beyond = stale; missing `fetched_at` = stale.

- [x] 7. Implement `emit(payload, out_path)` writing `cache/pricing.json`
  - ID: T-007
  - Requirement(s): FR-001, FR-006, FR-008, NFR-005
  - Files/areas: `fetch_pricing.py`, `cache/`
  - Validation: unit test — payload writes `fetched_at`, `ttl_hours`, `freshness`, `models`; output loads via `json.load`.

- [x] 8. Implement `main()` orchestration and exit-code mapping (0 fresh / 1 stale / 2 no cache)
  - ID: T-008
  - Requirement(s): FR-002, FR-003, FR-004, FR-005, NFR-003, NFR-004
  - Files/areas: `fetch_pricing.py`
  - Validation: integration tests (with injected fake fetchers) for all four paths: cache-hit exit 0, refresh exit 0, stale-cache-served exit 1, no-cache exit 2; plus the path where fetches succeed but every entry is invalid → exit 2 with no file written.

- [x] 9. Seed `overrides.json` from `~/llm-cost-estimator/data/pricing.json`
  - ID: T-009
  - Requirement(s): FR-009
  - Files/areas: `overrides.json`
  - Validation: script/one-shot produces valid JSON; spot-check a few `model_id` entries have non-negative `in`/`out` and a `tokenizer`.

- [x] 10. Write hermetic integration tests (no network)
  - ID: T-010
  - Requirement(s): FR-002, FR-003, FR-004, FR-005, NFR-002, NFR-003, NFR-004
  - Files/areas: `tests/`
  - Validation: `python -m unittest` passes with zero network access (fake fetchers injected); assert fetchers called/not-called appropriately.

- [x] 11. Write unit tests (merge, TTL, validator, args, emit)
  - ID: T-011
  - Requirement(s): FR-007, FR-010, NFR-005
  - Files/areas: `tests/`
  - Validation: `python -m unittest` passes; covers precedence, deep-merge inheritance, TTL boundary, validator accept/reject, arg parsing, payload metadata.

- [x] 12. Manual end-to-end validation and README status update
  - ID: T-012
  - Requirement(s): FR-001, NFR-001, NFR-005
  - Files/areas: `README.md`, `cache/pricing.json`
  - Validation: run `python fetch_pricing.py` once against real sources; confirm `cache/pricing.json` loads and entries are valid; update README build status to note the pipeline is built.

## Verification Checklist

- [x] Requirements IDs are referenced by tasks.
- [x] Design testing strategy is represented by tasks (unit + hermetic integration + manual opt-in).
- [x] Each task has a clear validation command or manual check.
- [x] Rollback/migration tasks are included when applicable (T-009 seed; rollback is trivially safe per design — no task needed).

## Execution Notes

- Keep `Status: tasks-draft` until the user explicitly approves this task plan.
- After approval, change status to `tasks-approved` and run implementation-readiness validation before coding.
- When coding starts, change status to `implementation-in-progress`.
- When all tasks are checked and validated, change status to `implementation-complete`.
- Complete tasks in order unless the user approves reordering.
- Mark tasks complete only after validation passes.
- Record deviations from design in design.md before implementing them.
