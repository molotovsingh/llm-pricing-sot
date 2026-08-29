# Consumer Wiring Tasks

Spec: `consumer-wiring`  
Status: implementation-complete  
Created: 2026-08-29  
Brainstorm: `./brainstorm.md`
Requirements: `./requirements.md`
Design: `./design.md`

## Implementation Plan

Only include implementation tasks after requirements and design are accepted. Keep tasks small, ordered, and traceable. The consumer lives at `~/llm-cost-estimator` (`estimate_llm_cost.py`, `tests/`); the pipeline repo is `~/projectless/llm-pricing-sot`.

- [x] 1. Document the read/refresh contract in the pipeline README
  - ID: T-001
  - Requirement(s): FR-001, FR-006
  - Files/areas: `README.md` — add `### Consuming the cache` (cache path, freshness fields, auto-refresh rule, Hermes/Pi read steps)
  - Validation: doc review — covers cache location, `fetched_at`/`ttl_hours`/`freshness`, refresh rule, per-consumer steps.

- [x] 2. Implement `resolve_pricing_dir(pricing_dir, env)`
  - ID: T-002
  - Requirement(s): FR-005
  - Files/areas: `~/llm-cost-estimator/estimate_llm_cost.py`
  - Validation: unit test — precedence `--pricing-dir` > `LLM_PRICING_SOT_DIR` > default; wrong/missing path yields a clear error.

- [x] 3. Implement `read_pricing_cache(dir)`
  - ID: T-003
  - Requirement(s): FR-002, FR-008
  - Files/areas: `~/llm-cost-estimator/estimate_llm_cost.py`
  - Validation: unit test — returns `data["models"]`; missing/corrupt file returns None.

- [x] 4. Implement `cache_is_fresh(cache, now)`
  - ID: T-004
  - Requirement(s): NFR-003
  - Files/areas: `~/llm-cost-estimator/estimate_llm_cost.py`
  - Validation: unit test — fresh within TTL; stale at/beyond TTL; missing `fetched_at` = stale.

- [x] 5. Implement `refresh_pricing(dir, runner)` — subprocess + exit-code mapping
  - ID: T-005
  - Requirement(s): FR-003, FR-004
  - Files/areas: `~/llm-cost-estimator/estimate_llm_cost.py` (injectable `runner`, default = `[sys.executable, <dir>/fetch_pricing.py]`)
  - Validation: unit test — maps exit `0`/`1`/`2`; spawn failure propagates.

- [x] 6. Implement `load_pricing_for_wiring(dir)` orchestration
  - ID: T-006
  - Requirement(s): FR-002, FR-003, FR-007
  - Files/areas: `~/llm-cost-estimator/estimate_llm_cost.py`
  - Validation: unit test — fresh reads without refresh; stale/missing triggers refresh then re-reads; exit `2`/spawn-fail raises a clear error (no silent run).

- [x] 7. Wire `main()` to use the cache-aware loader (`--pricing-dir`)
  - ID: T-007
  - Requirement(s): FR-002, FR-005
  - Files/areas: `~/llm-cost-estimator/estimate_llm_cost.py` (add `--pricing-dir`, call `load_pricing_for_wiring`)
  - Validation: unit test for arg/loader wiring; run `estimate_llm_cost.py --pricing-dir <pipeline-repo>` against the cache.

- [x] 8. Add unit tests for the new loader functions
  - ID: T-008
  - Requirement(s): FR-005, FR-004, FR-007, NFR-003
  - Files/areas: `~/llm-cost-estimator/tests/`
  - Validation: `python -m unittest` (in the consumer repo) passes.

- [x] 9. Add integration tests with a temp pipeline dir + `fetch_pricing.py` stub
  - ID: T-009
  - Requirement(s): FR-002, FR-003, FR-004
  - Files/areas: `~/llm-cost-estimator/tests/`
  - Validation: `python -m unittest` — fresh cache read; stale triggers stub script; exit `2` no-cache → error; no network.

- [x] 10. Manual end-to-end validation against the real pipeline
  - ID: T-010
  - Requirement(s): FR-002, FR-003
  - Files/areas: `~/llm-cost-estimator/estimate_llm_cost.py`, pipeline `cache/pricing.json`
  - Validation: run `estimate_llm_cost.py --pricing-dir ~/projectless/llm-pricing-sot <input>`; confirm prices come from the cache and a stale cache triggers refresh.

- [x] 11. Confirm the pipeline is unchanged
  - ID: T-011
  - Requirement(s): NFR-002
  - Files/areas: pipeline `fetch_pricing.py`, pipeline `tests/`
  - Validation: pipeline `python -m unittest` still green; no edits to `fetch_pricing.py`.

## Verification Checklist

- [x] Requirements IDs are referenced by tasks.
- [x] Design testing strategy is represented by tasks (unit + integration + manual + doc review).
- [x] Each task has a clear validation command or manual check.
- [x] Rollback/migration tasks are included when applicable (config opt-in + legacy fallback; rollback = unset config — noted, no data migration).

## Execution Notes

- Keep `Status: tasks-draft` until the user explicitly approves this task plan.
- After approval, change status to `tasks-approved` and run implementation-readiness validation before coding.
- When coding starts, change status to `implementation-in-progress`.
- When all tasks are checked and validated, change status to `implementation-complete`.
- Complete tasks in order unless the user approves reordering.
- Mark tasks complete only after validation passes.
- Record deviations from design in design.md before implementing them.
