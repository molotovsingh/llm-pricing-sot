# llm-pricing-sot — Engineering Quality Pass · `6a12f98`

> **Report · 2026-09-08 08:37 IST · branch `004-clear-review-queue` · commit `6a12f98`** — canonical read at this commit; refine while it's `HEAD`, frozen once `HEAD` advances.
> Clean worktree — findings are against `HEAD`. Stable entry: `latest.md` · history: `../INDEX.md` · home: `claude_review/`.
> **Baseline:** `agent_review/quality-pass/2026-08-31-9ce70bc.md` (legacy home, read **read-only**; see [Home migration](#home-migration)).

Second pass. Delta `9ce70bc..6a12f98` is 2,642 insertions across 28 files — the
query surface, the test suite and the contract mechanism all changed — so this
was run as a **full** pass rather than a delta. Every carried-forward finding was
re-verified against the current source, not trusted from the prior report.

**Headline: all three of the last report's highest-leverage fixes landed, and the
`risky` verdict is gone. The suite is now the weakest unit** — it carries a
scheduled failure on **2026-11-15**, and the drift gate that exists to stop
contract restatement does not govern the two restatements inside the contract's
own source file.

Layers: [Home migration](#home-migration) → [Unit map](#unit-map-discovery) → [Rubric](#rubric) →
[Audit view](#audit-view) → [Report log](#report-log) → [Evidence & fixes](#evidence--fixes) →
[Emerging themes](#emerging-themes) → [What it does well](#what-it-does-well) →
[Highest-leverage fixes](#highest-leverage-fixes).

## Home migration

Prior runs live in `agent_review/`. This run establishes `claude_review/` as the
review home per the skill's fixed layout. The legacy folder was read as baseline
and **not modified** — its report is still the canonical text for `9ce70bc`, and
`../INDEX.md` links to it in place rather than duplicating 20KB. Nothing outside
`claude_review/` was written by this pass.

## Unit map (discovery)

One 946-line stdlib-only Python module, a data file, two test modules (1,926
lines), a generated-block contract gate, and the autoresearch instruments added
since the baseline. Units are coherent responsibilities, not files.

**Mode axis:** `network` (touches an external API) · `cache` (reads/writes disk
state) · `pure` (computation only) · `doc` (contract artifact).

| Unit | Family | Role — what it does (plain) | Powers | Depends on / twin | Mode |
|---|---|---|---|---|---|
| `fetch_pricing.py::sources` (124-192, 640-670) | pipeline | Fetches and tolerantly normalizes OpenRouter catalog, LiteLLM prices, and per-provider endpoints into flat `{id: {in,out,source}}` layers | `run()`, `ensure_discovery`, `ensure_endpoints` | `urllib` (deferred); injectable `fetcher` callables | network |
| `fetch_pricing.py::merge` (193-214) | pipeline | Per-field deep merge of layers in ascending precedence | `run()` | pure dict work | pure |
| `fetch_pricing.py::attach_catalog_baseline` (252-324) | pipeline | Resolves each override to its catalog row; inherits the price, or honours an attested one and records drift; assigns `review` reasons | `run()` | `_resolve_slug`, `attestation_state` | pure |
| `fetch_pricing.py::attestation_state` (229-251) | pipeline | Classifies a hand-typed price's attestation as valid / expired / missing | `attach_catalog_baseline`, **the suite** | `_parse_iso_utc`, wall clock | pure |
| `fetch_pricing.py::validation` (325-366) | pipeline | Drops entries lacking a tokenizer or with negative prices | `run()` | — | pure |
| `fetch_pricing.py::cache-io` (367-470) | pipeline | TTL freshness maths, envelope construction, atomic JSON writes, cache loading | `run()`, `query_main`, consumers | `tempfile` (deferred), `os.replace` | cache |
| `fetch_pricing.py::run` (472-560) | pipeline | Orchestrates cache-hit / refresh / stale-fallback and returns the exit code | `main()`, `query_main`, estimator subprocess | all pipeline units | network+cache |
| `fetch_pricing.py::_exit_for` (755-765) | query | **The** exit-code decision: maps freshness × degraded → 0/1/2 | `query_main`, the drift gate's `derive_exit_codes` | — | pure |
| `fetch_pricing.py::_resolve_slug` (672-693) | query | Maps a short model alias to a catalog slug: exact id → declared `openrouter_slug` (authoritative) → last-segment match | `attach_catalog_baseline`, `cheapest` | catalog ids, overrides | pure |
| `fetch_pricing.py::query_main` (768-933) | query | Serves `price` / `cheapest` / `list` / `fresh` / `review`; auto-refreshes stale data; prints JSON + exit code | `main()`, agents via the skill | `run`, `ensure_discovery`, `ensure_endpoints`, `_exit_for` | network+cache |
| `overrides.json` | data | Truth layer: tokenizer mappings always, `openrouter_slug` pins, and attested prices where we pay a non-public rate | `load_overrides` → whole pipeline | catalog slugs it pins | doc |
| `tests/test_contract_drift.py` (606 lines, 31 tests) | tests | **New.** Derives 3 facts from the code, compares them against marked blocks in 6 governed documents; ships a `--fix` generator that never runs during the test run | `python -m unittest` | `fetch_pricing` internals | pure |
| `tests/test_fetch_pricing.py` (1,320 lines, 120 tests) | tests | Hermetic unit + orchestration coverage with injected fetchers; now includes `TestShippedOverridesFile` over the real data file | `python -m unittest` | fakes; the real `overrides.json` | pure |
| `autoresearch.{sh,checks.sh,md,jsonl}` | instruments | **New.** Cold-start benchmark harness, correctness backpressure (suite + offline smoke), and the session record | a human running a perf session | the CLI's exit codes | doc |
| `skills/llm-pricing/SKILL.md` | contract | The artifact an agent reads to use the SOT; symlinked into `~/.pi/agent/skills/`; contract blocks generated | any agent needing a price | governed by the gate | doc |
| `README.md` · `.specify/` · `specs/*/contracts/` | contract | Human/consumer contract and ratified per-feature specs | maintainers, consumer repos | governed by the gate | doc |
| consumer boundary (`llm-cost-estimator`) | boundary | Reads `cache/pricing.json`, shells out to `fetch_pricing.py`, honours exit codes | `estimate_llm_cost.py:271-303` | the cache envelope | cache |

## Rubric

| Field | Allowed values |
|---|---|
| mode | `network` · `cache` · `pure` · `doc` |
| verdict | `right-sized` · `brittle` · `overgrown` · `risky` (`*` = minor warning) |
| theme | discovered `T#` · `—` if clean |
| action | `ignore` · `watch` · `refactor` · `test now` |
| severity | `P0` blocking · `P1` next-milestone/correctness/security · `P2` minor · `P3` clean |

## Audit view

**P1 queue — fix first:** `tests/test_fetch_pricing.py` (scheduled failure 2026-11-15)

| Unit | Mode | Blast radius | Verdict | Theme | Action | Sev |
|---|---|---|---|---|---|---|
| `tests/test_fetch_pricing.py` | pure | Green suite turns red on a date, with no code change | brittle | T2 | refactor | P1 |
| `query_main` | network+cache | 165 lines, five handlers inline; hard to extend safely | overgrown | — | refactor | P2 |
| `fetch_pricing.py` docstrings | doc | Source states superseded exit codes the gate cannot see | brittle | T1 | refactor | P2 |
| `overrides.json` | doc | `glm-5.2`'s attestation is unverified and expires 2026-11-14 | right-sized* | T2 | watch | P2 |
| `autoresearch.checks.sh` | doc | An eighth, ungoverned restatement of the exit contract | right-sized* | T1 | watch | P3 |
| `tests/test_contract_drift.py` | pure | A doc using `~~~` fences could hide or expose a marker | right-sized* | — | watch | P3 |
| `_resolve_slug` | pure | ~~Wrong price silently inherited~~ — **cleared** | right-sized | — | ignore | P3 |
| `attach_catalog_baseline` | pure | ~~Inherits an unsafe resolver~~ — **cleared** | right-sized | — | ignore | P3 |
| `_exit_for` | pure | The whole exit contract | right-sized | — | ignore | P3 |
| consumer boundary | cache | ~~Inherits a mutated TTL~~ — **cleared** | right-sized | — | ignore | P3 |
| `specs/*/contracts/*.md` | doc | ~~Superseded exit codes~~ — **cleared, now generated** | right-sized | — | ignore | P3 |
| `README.md` · `SKILL.md` · constitution | doc | ~~Seven hand-maintained restatements~~ — **cleared** | right-sized | — | ignore | P3 |
| `run` | network+cache | Refresh policy wrong → stale or thin cache | right-sized* | T1 | watch | P3 |
| `cache-io` | cache | Torn cache file / wrong staleness | right-sized* | — | ignore | P3 |
| `validation` · `sources` · `merge` | pure/network | Bad entries reach consumers | right-sized | — | ignore | P3 |

**Tally:** 13 right-sized (7 clean, 6 with `*`), 2 brittle, 1 overgrown, **0 risky** · 1×P1, 3×P2, 11×P3, 0×P0.

Prior run: 9 right-sized, 3 brittle, 1 overgrown, 1 risky · 2×P1, 7×P2, 5×P3.

## Report log

- **Report `6a12f98`** · 2026-09-08 · full (home migrated to `claude_review/`).
  Headline: all three highest-leverage fixes from `9ce70bc` landed and verified;
  the `risky` verdict and both P1s are cleared. Risk has **moved into the test
  suite** — an attestation assertion coupled to the wall clock will fail the
  suite on 2026-11-15, and the new drift gate governs six markdown documents
  while two stale restatements sit in `fetch_pricing.py`'s own docstrings.
- **Report `9ce70bc`** · 2026-08-31 · full. First pass. Headline: the pipeline's
  attestation work never reached the query surface; `_resolve_slug` guessed after
  a retired pin. See `agent_review/quality-pass/2026-08-31-9ce70bc.md`.

## Evidence & fixes

| Family | Unit | Role | Mode | Theme | Verdict — judgment · where (`file:line`) · Fix |
|---|---|---|---|---|---|
| **tests** | `tests/test_fetch_pricing.py` | hermetic suite | pure | T2 | ⚠️ **The suite has a scheduled failure: it goes red on 2026-11-15 with no code change.** `test_no_half_declared_attestation` (`tests/test_fetch_pricing.py:1310-1320`) asserts `attestation_state(entry) == "valid"` for any entry carrying a full attestation. `glm-5.2` is attested `verified_at: 2026-08-16` and `ATTESTATION_MAX_AGE_DAYS` is 90 (`fetch_pricing.py:27`). Verified by evaluating `attestation_state` at fixed dates: `valid` through 2026-11-14, `'expired'` from 2026-11-15. The pipeline **already** has a channel for an expired attestation — it reports the entry under `needs_review`, which is the designed prompt to re-confirm the rate. Duplicating that as a hard assertion converts a data-freshness reminder into a CI outage, on a date, in a repo whose whole point is that degradation is reported rather than fatal. **Fix:** assert attestation *shape* only (all three keys present, `verified_at` parseable) and let `attestation_state` expiry surface through `needs_review` as designed — or, if the intent is genuinely to force a re-confirmation deadline, pass an explicit `now=` so the test states its own clock and add a separate, clearly-named test that documents the deadline. |
| **query** | `query_main` | the whole query surface | network+cache | — | 🔻 **The three correctness defects are fixed; the altitude finding stands.** Verified fixed: (a) `price` on a flagged entry now passes `bool(entry.get("review"))` as `degraded` (`fetch_pricing.py:871`) → exit 1; (b) a query's `--ttl-hours` is a read-time gate only, with the cache's own declared TTL used for the refresh and validated against bool/non-int/≤0 (`:782-790`); (c) `review` no longer fakes `"stale"` — it passes `bool(rows)` as `degraded` (`:840-841`). But the function is still **165 lines holding five action handlers**, shared setup, two nested helpers and stderr table rendering (`:768-933`). That is unchanged from the baseline. **Fix:** split the five handlers into functions taking `(cache, disc, ctx)`; the shared prologue at `:801-805` is already a natural seam. |
| **contract** | `fetch_pricing.py` docstrings | the source of truth's own prose | doc | T1 | ⚠️ **The contract gate governs six markdown documents and misses the two restatements inside the file it derives from.** `fetch_pricing.py:773` says "Exit codes (FR-008): 0 fresh answer, 1 stale answer, 2 no data / not found" — three lines above a `_exit_for` that returns 1 for `degraded or stale`. `fetch_pricing.py:480-481` says "0 fresh (cache-hit or refresh), 1 stale cache served, 2 no usable cache", but `run` returns 1 for flagged entries at `:494` and `:540` (its own comment at `:536` calls that "served, but degraded"). Both predate the degraded vocabulary and both are wrong now. `GOVERNED` (`tests/test_contract_drift.py:85-92`) lists only `.md` paths, so neither is checkable. This is the exact failure the gate was built to end, surviving in the one file nobody thought to govern. **Fix:** register the two docstrings — either extract the exit-code sentence into a module constant rendered from `render_exit_codes()`, or add a test asserting that no docstring in `fetch_pricing.py` contains the superseded phrases. |
| **data** | `overrides.json` | the truth layer | doc | T2 | ✅⚠️ **Now covered and the review queue is clean; one attestation remains unverified.** `TestShippedOverridesFile` (`tests/test_fetch_pricing.py:1264-1320`) loads the real file and asserts tokenizer shape, fallback distinctness, `author/slug` pins, both price halves, and no partial attestation — the baseline's zero-coverage finding is closed. This commit also cleared the four permanently-unpriceable entries by deleting their pre-attestation `in`/`out` so each inherits from the catalog; `needs_review` is now `[]`. Remaining: `glm-5.2`'s `verified_at: 2026-08-16` was derived from git history, not from anyone confirming the z.ai rate (`README.md` open questions), and it is the sole input to the T2 time bomb. **Fix:** confirm the rate against the z.ai plan and restamp `verified_at`; that is a human decision, not a code change. |
| **tests** | `tests/test_contract_drift.py` | the drift gate + generator | pure | — | ✅⚠️ **The strongest new unit in the repo; one narrow blind spot.** `find_blocks` (`:114-163`) is genuinely careful: markers count only at column 0 outside a fence, an unknown fact id raises rather than silently disabling a check (`:139-140`), and nesting, duplication and non-termination are each a distinct hard error. The generator is import-isolated from the test run (`:172-174`), which is the right call — a gate that repairs itself hides the drift it reports. `TestCheckerIsHermetic` and `TestSkillSymlinkIsGoverned` close the two ways this could rot. The blind spot: fence detection matches only ` ``` ` (`:126`), so a document using `~~~` fences would have markers inside it treated as real, or a real marker after one swallowed. No governed document uses `~~~` today. **Fix:** match `^(```\|~~~)` in the fence toggle; one-character change, removes a whole class of future surprise. |
| **instruments** | `autoresearch.checks.sh` | correctness backpressure | doc | T1 | ✅⚠️ **A genuinely good habit — and an eighth, ungoverned restatement of the exit contract.** Running the full suite plus an offline smoke of every read action before accepting a perf change is exactly right, and it caught this session's data fix immediately. But its header comment (`autoresearch.checks.sh:10-11`) restates the exit-code contract in prose the gate does not govern. **Noted honestly: this pass's own commit edited that comment** rather than removing the restatement. Its expectations previously asserted `list`/`fresh` must exit 1 — encoding the four-model defect as permanent, which is why the suite stayed green while four of nine models were unpriceable. **Fix:** replace the prose with a pointer to `README.md`'s generated block; a check script should not be a ninth place the contract can drift. |
| **pipeline** | `_resolve_slug` | alias → catalog slug | pure | — | ✅ **Cleared — the baseline's only `risky` verdict is gone.** A declared `openrouter_slug` is now authoritative: `return pin if pin in catalog_ids else None` (`fetch_pricing.py:687-689`), with the reasoning recorded in the docstring (`:679-682`). Last-segment matching is reserved for entries that declared no pin. A retired pin now lands in `needs_review` as `dropped-unpriceable` instead of silently inheriting another model's price. |
| **pipeline** | `_exit_for` | the exit contract | pure | — | ✅ **The fix that dissolved the baseline's T2 theme, and now the single source for three documents.** Degradation is a first-class parameter independent of age (`:755-765`), the docstring states why, and `derive_exit_codes` (`tests/test_contract_drift.py:38-42`) enumerates the function over its whole domain so the documented table cannot drift from the code. This is the template for how the rest of the contract should be pinned. |
| **pipeline** | `attach_catalog_baseline` | resolve, inherit or attest | pure | — | ✅ **Cleared.** The three-way split is unchanged and correct; its bounded correctness now rests on a resolver that fails instead of guessing. |
| **pipeline** | `run` | orchestration | network+cache | T1 | ✅⚠️ **Right-sized; only its docstring is wrong** (see the docstrings row). The load-bearing/demoted source distinction (`:497-502`) and the unpriceable-override sweep (`:524-528`) remain the clearest failure-policy prose in the repo. |
| **pipeline** | `cache-io` | TTL + atomic writes | cache | — | ✅⚠️ **Atomic writes correct; durability deliberately not claimed.** `_write_json_atomic` (`:417-436`) writes to a same-directory temp file and `os.replace`s. No `fsync`, so a crash mid-write can lose new content — acceptable for a regenerable cache, and now additionally justified by the cold-start work (`tempfile` is imported lazily at this call site). |
| **pipeline** | `sources` · `validation` · `merge` | fetch, normalize, gate | network/pure | — | ✅ **Unchanged and still the repo's best structural habit.** Every network call takes an injectable `fetcher`; normalizers skip malformed rows rather than raising. The cold-start session deferred `urllib.request` into `_default_fetcher` (`:104-109`) without breaking injection — a perf change that respected the seam. |
| **boundary** | `llm-cost-estimator` wiring | consumes the cache | cache | — | ✅ **Cleared.** `cache_is_fresh` reads `ttl_hours` from the envelope; with the query TTL no longer persisting, the estimator's refresh cadence can no longer be changed by another consumer's tight query. |
| **contract** | governed documents | six `.md` files | doc | — | ✅ **The baseline's T1 is structurally solved for markdown.** Three facts derived from code, compared against marked blocks in six documents, with `specs/*/research.md` and `specs/*/spec.md` exempt **by declared path rule** (`tests/test_contract_drift.py:94-99`) rather than by content inference — the right call, since those must keep stating what was decided then. The two contract files the baseline flagged as stale are now generated. |

## Emerging themes

- **T1 — The gate stops at the file boundary.** Contract single-sourcing succeeded
  for the six governed markdown documents and failed to cover the three
  restatements that are not markdown: `fetch_pricing.py:480-481`,
  `fetch_pricing.py:773`, and `autoresearch.checks.sh:10-11`. Two of the three are
  **wrong at this commit**, and both sit in the very file the facts are derived
  from. The baseline's lesson was "seven copies drift"; the mechanism built to fix
  it counted only the copies that looked like documentation. **Shared fix:** extend
  `GOVERNED` beyond `.md`, or assert the superseded phrases appear nowhere in the
  source. The cheapest restatement is still the one that doesn't exist —
  `checks.sh` should point at `README.md`, not paraphrase it.
- **T2 — Correctness gates coupled to the wall clock.** Two units now depend on
  *when* the suite runs rather than *what the code does*: `test_no_half_declared_attestation`
  asserts a 90-day-expiring attestation is `valid`, and `overrides.json` supplies
  the expiry via a `verified_at` that was inferred from git history rather than
  confirmed. Together they schedule a red suite for 2026-11-15. The repo's own
  design principle — degradation is *reported*, not fatal — is the fix already
  present elsewhere in the codebase. **Shared fix:** let expiry flow through
  `needs_review`; assert shape in tests, not freshness.

**Meta-observation:** risk has moved cleanly from where it was. The baseline found
it at the **query surface and the data file**; both are now clean, and the exit
contract is derived rather than restated. It now sits in the **verification
layer** — the suite and the gate. That is a better place for it to be (a false red
costs less than a wrong price), but it is the same posture as before, one level
up: the mechanism that checks correctness is itself unchecked, and the drift gate
does not read the file it derives from.

## What it does well

- **The exit contract is now *derived*, not restated.** `derive_exit_codes`
  enumerates `_exit_for` over its whole domain (`tests/test_contract_drift.py:38-42`)
  and renders the table into six documents. A behaviour change cannot leave a
  reader silently wrong — the mechanism the baseline asked for, built well.
- **The gate refuses to repair itself during a test run**
  (`tests/test_contract_drift.py:172-174`). The reasoning is written down: a gate
  that fixes drift on the fly hides the drift it exists to report. That is a
  subtle call most implementations get wrong.
- **Exemption is by declared path, never inferred from content**
  (`:94-99`). Spec `research.md`/`spec.md` must keep saying what was true then;
  deciding that by path rule rather than by sniffing the text is why the rule
  can't quietly widen.
- **Dependency injection survived a performance rewrite.** The cold-start session
  cut 26.6% by deferring `urllib.request` and `tempfile` to their single call
  sites (`:104-109`, `_write_json_atomic`) — without touching the `fetcher`
  seam that makes 151 tests run hermetically in 0.05s.
- **Decisions are recorded where they are implemented.** The load-bearing vs
  demoted source policy (`fetch_pricing.py:497-502`), the read-time-TTL rationale
  (`:782-784`), and the authoritative-pin reasoning (`:679-682`) each explain a
  choice a future reader would otherwise undo. All three are fixes from the last
  pass, and each shipped with its "why" attached.
- **A correctness gate runs before perf changes are accepted.**
  `autoresearch.checks.sh` pairs the full suite with an offline smoke of every
  read action, so a speed win that breaks the contract cannot land quietly.

## Highest-leverage fixes

Two changes clear the P1 and both P2 correctness rows.

1. **Defuse the scheduled suite failure** (T2, P1). In
   `tests/test_fetch_pricing.py:1310-1320`, assert attestation *shape* rather than
   `attestation_state(entry) == "valid"`, and let expiry reach a human through
   `needs_review` — the channel the pipeline already implements for exactly this.
   Clears the only P1 and the `overrides.json` watch. If the deadline is
   deliberate, make it explicit with a pinned `now=` and a test named for it.
2. **Extend the drift gate past `.md`** (T1, P2). `fetch_pricing.py:773` and
   `:480-481` state superseded exit codes inside the file the facts are derived
   from; `autoresearch.checks.sh:10-11` adds a third ungoverned copy. Either
   register them in `GOVERNED` or assert the superseded phrasing appears nowhere
   in the source. Clears two rows and closes the theme the whole 003 spec existed
   to close.

Then, cheaper: decompose `query_main`'s five handlers (P2 — the correctness
defects are gone, so this is now purely altitude), and match `~~~` in the gate's
fence toggle (P3, one character).

---

> **⏳ Currentness.** Valid only for commit `6a12f98` at the time this report was
> written, with a clean worktree. **A source edit since then can invalidate these
> findings — re-run `/quality-pass` after changes.**
