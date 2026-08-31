# llm-pricing-sot — Engineering Quality Pass · `9ce70bc`

> **Report · 2026-08-31 09:00 IST · branch `002-pricing-endpoints` · commit `9ce70bc`** — canonical read at this commit; refine while it's `HEAD`, frozen once `HEAD` advances.
> Clean worktree — findings are against `HEAD`. Stable entry: `latest.md` · history: `../INDEX.md` · home: `agent_review/`.

First pass in this tree (no prior baseline; `--full`). A repeatable
architecture-quality pass — **not** a formal security/correctness audit
(security-adjacent items are flagged, but a dedicated security scan is needed for
completeness). One question per unit: *is the problem solved at the right level,
and where is the risk?*

Layers: [Unit map](#unit-map-discovery) → [Rubric](#rubric) → [Audit view](#audit-view) →
[Evidence & fixes](#evidence--fixes) → [Emerging themes](#emerging-themes) →
[What it does well](#what-it-does-well) → [Highest-leverage fixes](#highest-leverage-fixes).

## Unit map (discovery)

The repo is one 917-line stdlib-only Python module plus a data file, a test suite,
and five documents that each restate its contract. Units below are coherent
responsibilities, not files, because `fetch_pricing.py` holds several.

**Mode axis:** `network` (touches an external API) · `cache` (reads/writes disk
state) · `pure` (computation only) · `doc` (contract artifact).

| Unit | Family | Role — what it does (plain) | Powers | Depends on / twin | Mode |
|---|---|---|---|---|---|
| `fetch_pricing.py::sources` (106-192, 636-666) | pipeline | Fetches and tolerantly normalizes OpenRouter catalog, LiteLLM prices, and per-provider endpoints into flat `{id: {in,out,source}}` layers | `run()`, `ensure_discovery`, `ensure_endpoints` | `urllib`; injectable `fetcher` callables | network |
| `fetch_pricing.py::merge` (194-214) | pipeline | Per-field deep merge of layers in ascending precedence | `run()` | pure dict work | pure |
| `fetch_pricing.py::attach_catalog_baseline` (253-324) | pipeline | Resolves each override to its catalog row; inherits the price, or honours an attested one and records drift; assigns `review` reasons | `run()` | `_resolve_slug`, `attestation_state`, `_relative_drift` | pure |
| `fetch_pricing.py::attestation_state` (230-251) | pipeline | Classifies a hand-typed price's attestation as valid / expired / missing | `attach_catalog_baseline` | `_parse_iso_utc` | pure |
| `fetch_pricing.py::validation` (326-366) | pipeline | Drops entries lacking a tokenizer or with negative prices | `run()` | — | pure |
| `fetch_pricing.py::cache-io` (368-470) | pipeline | TTL freshness maths, envelope construction, atomic JSON writes, cache loading | `run()`, `query_main`, consumers | `tempfile`, `os.replace` | cache |
| `fetch_pricing.py::run` (472-557) | pipeline | Orchestrates cache-hit / refresh / stale-fallback and returns the exit code | `main()`, `query_main`, estimator subprocess | all pipeline units | network+cache |
| `fetch_pricing.py::_resolve_slug` (668-684) | query | Maps a short model alias to an OpenRouter catalog slug: exact id → declared `openrouter_slug` → last-segment match | `attach_catalog_baseline`, `cheapest` | catalog ids, overrides | pure |
| `fetch_pricing.py::query_main` (749-905) | query | Serves `price` / `cheapest` / `list` / `fresh` / `review`; auto-refreshes stale data; prints JSON + exit code | `main()`, agents via the skill | `run`, `ensure_discovery`, `ensure_endpoints`, `_blended_cost` | network+cache |
| `overrides.json` | data | Truth layer: tokenizer mappings always, `openrouter_slug` pins, and attested prices where we pay a non-public rate | `load_overrides` → whole pipeline | catalog slugs it pins | doc |
| `tests/test_fetch_pricing.py` (1137 lines, 103 tests) | tests | Hermetic unit + orchestration coverage with injected fetchers | `python -m unittest` | fakes only — never `_default_fetcher` | pure |
| `skills/llm-pricing/SKILL.md` | contract | The artifact an agent actually reads to use the SOT; symlinked into `~/.pi/agent/skills/` | any agent needing a price | mirrors CLI behaviour | doc |
| `README.md` | contract | Human/consumer contract: schema, exit codes, override semantics, source policy | maintainers, consumer repos | mirrors CLI behaviour | doc |
| `.specify/` (constitution v2.0.0, specs 001/002) | contract | Governance principles + ratified per-feature specs and CLI contracts | agents doing feature work | mirrors CLI behaviour | doc |
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

**P1 queue — fix first:** `_resolve_slug` · `query_main`

| Unit | Mode | Blast radius | Verdict | Theme | Action | Sev |
|---|---|---|---|---|---|---|
| `_resolve_slug` | pure | Wrong price silently inherited from a different model | risky | T3 | refactor | P1 |
| `query_main` | network+cache | Unverified price served as success; a query mutates shared cache state | overgrown | T2 | refactor | P1 |
| `overrides.json` | doc | Malformed shipped data reaches every consumer untested | brittle | T3 | test now | P2 |
| `specs/*/contracts/*.md` | doc | Ratified contract states superseded exit codes | brittle | T1 | refactor | P2 |
| consumer boundary | cache | Estimator inherits a mutated TTL | brittle* | T2 | watch | P2 |
| `attach_catalog_baseline` | pure | Inherits `_resolve_slug`'s unsafe fallback | right-sized* | T3 | watch | P2 |
| `tests/test_fetch_pricing.py` | pure | Exit-code gaps and data-file drift go uncaught | right-sized* | T2 | test now | P2 |
| `README.md` | doc | One of seven restatements of one contract | right-sized* | T1 | watch | P2 |
| `.specify/` constitution | doc | Principle III is violated by shipped code | right-sized* | T2 | watch | P2 |
| `run` | network+cache | Refresh policy wrong → stale or thin cache | right-sized | — | ignore | P3 |
| `cache-io` | cache | Torn cache file / wrong staleness | right-sized* | — | ignore | P3 |
| `validation` | pure | Bad entries reach consumers | right-sized | — | ignore | P3 |
| `sources` | network | Upstream shape change breaks ingestion | right-sized | — | ignore | P3 |
| `skills/llm-pricing/SKILL.md` | doc | Agents mis-read every answer | right-sized | T1 | ignore | P3 |

**Tally:** 9 right-sized (4 clean, 5 with `*`), 3 brittle, 1 overgrown, 1 risky · 2×P1, 7×P2, 5×P3, 0×P0.

## Report log

- **Report `9ce70bc`** · 2026-08-31 · full. First pass in this tree. Headline: the
  session's attestation work fixed the *pipeline's* honesty but the **query surface
  was never brought along** — a flagged model still answers with exit 0, violating
  the constitution ratified in the same session. Separately, making inheritance the
  default promoted `_resolve_slug`'s fuzzy fallback onto the primary path, where a
  retired pin now silently yields another model's price.

## Evidence & fixes

| Family | Unit | Role | Mode | Theme | Verdict — judgment · where (`file:line`) · Fix |
|---|---|---|---|---|---|
| **query** | `_resolve_slug` | alias → catalog slug | pure | T3 | ⚠️ **A declared pin that no longer resolves degrades to a guess instead of failing.** `openrouter_slug` exists to make resolution deterministic, but when the pinned slug is absent from the catalog the function falls through to last-segment matching (`fetch_pricing.py:680-682`). Verified: pinning `gpt-4o` to a retired `openai/gpt-4o` against a catalog holding `azure/gpt-4o` silently inherits **9.9/99.0** with no `review` flag and exit 0. Since price inheritance is now the default for 8 of 9 models, this is the primary path, and OpenRouter does retire slugs. **Fix:** if `entry.get("openrouter_slug")` is set but not in `catalog_ids`, return `None` immediately — a broken promise must fail loudly and land in `needs_review` as `dropped-unpriceable`. Reserve last-segment matching for entries that declared no pin. |
| **query** | `query_main` | the whole query surface | network+cache | T2 | 🔻⚠️ **156 lines holding five independent action handlers, shared setup, nested helpers and stderr table rendering — and the degradation signal was never wired into it.** Three verified defects: (a) `query price gpt-5.2` returns **exit 0** while serving a price flagged `unattested-price-ignored` (`fetch_pricing.py:841-844`), directly violating constitution Principle III ("a consumer MUST NOT be able to use an unverified price while seeing a success code"); (b) a transient `--ttl-hours 1` query rewrites the **persisted** envelope's `ttl_hours` to 1 (`fetch_pricing.py:765` passes the query's TTL into `run`, which stamps it via `build_cache`), so one agent's tight query makes every other consumer re-fetch hourly — verified by seeding a 3h-old cache and watching `ttl_hours` go 24 → 1; (c) `review` returns the literal string `"stale"` to `_exit_for` purely to obtain exit 1 (`fetch_pricing.py:813-814`) while the payload reports `"freshness": "fresh"` — the answer contradicts its own exit code. **Fix:** thread a `degraded` boolean alongside `freshness` and map exit codes from both; return the query's TTL as a *read-time* gate without persisting it (pass `ttl_hours` for the freshness check but let `run` stamp `DEFAULT_TTL_HOURS`, or thread the cache's own value); split the five handlers into functions. |
| **pipeline** | `attach_catalog_baseline` | resolve, inherit or attest | pure | T3 | ✅⚠️ **The core rule is right and unusually well documented, but it trusts its resolver.** The three-way split (inherit / attested / unattested-discarded) is clear at `fetch_pricing.py:253-324`, copies rather than mutates input (`:288`), and every branch assigns a `review` reason. Its correctness is bounded by `_resolve_slug`'s fallback above. **Fix:** none here once `_resolve_slug` is corrected; add a test asserting a pinned-but-missing slug produces `dropped-unpriceable`. |
| **data** | `overrides.json` | the truth layer | doc | T3 | ⚠️ **The shipped data contract has zero test coverage.** All 103 tests use synthetic fixtures; nothing loads the real file (`tests/test_fetch_pricing.py` references `overrides.json` only as tempfile paths). A malformed tokenizer spec, a typo'd pin, or a price without attestation ships silently — and four entries currently sit permanently in `needs_review`. **Fix:** add a test that loads the real `overrides.json` and asserts every entry has a well-formed `tokenizer`, every `openrouter_slug` is `author/slug`-shaped, and any `in`/`out` carries a complete attestation. |
| **tests** | `tests/test_fetch_pricing.py` | hermetic suite | pure | T2 | ✅⚠️ **Genuinely hermetic and well-injected, but it tests the pipeline's exit codes and never the query surface's.** Zero references to `_default_fetcher` and a 0.03s runtime for 103 tests confirm no network. `TestReviewSurvivesCacheHit` even asserts the cache-hit path cannot touch the network. The gap is that no test asserts what `query price <flagged-model>` exits with — which is exactly how P1(a) shipped. **Fix:** add exit-code assertions for each query action against a cache containing a flagged entry. |
| **contract** | `specs/*/contracts/*.md` | ratified CLI contract | doc | T1 | ⚠️ **Both contract files still state the superseded exit-code vocabulary.** `specs/001-pricing-query/contracts/query-cli.md:6,13,21,28,34` and `specs/002-pricing-endpoints/contracts/cheapest-query.md:7` all say `0 fresh / 1 stale / 2 no data`; the constitution was amended to `0 clean / 1 degraded / 2 no data` in `234dc5f`, and neither file mentions `query review`. **Fix:** update both to the degraded vocabulary and add the `review` action, or better, see T1's shared fix. |
| **contract** | `.specify/memory/constitution.md` | governance | doc | T2 | ✅⚠️ **Amended to match shipped behaviour, but the shipped code now violates its own Principle III.** The principle at `:61-67` requires that degradation be visible on every path; `query price` on a flagged model returns 0. **Fix:** no doc change — fix the code (P1 above); the principle is correct as written. |
| **contract** | `README.md` | consumer contract | doc | T1 | ✅⚠️ **Comprehensive and current, but it is one of seven places stating the same contract.** Accurate at `README.md` schema/exit-code sections as of this commit. **Fix:** see T1. |
| **contract** | `skills/llm-pricing/SKILL.md` | agent entrypoint | doc | T1 | ✅ **Now correct and drift-proofed.** Corrected in `9ce70bc` after `source: override` stopped meaning "authoritative", and the installed copy is now a symlink into the repo so the two cannot diverge. Trust is keyed off `baseline`, with `source` explaining provenance. This is the template for how the other contract restatements should be kept — one file, linked not copied. |
| **boundary** | `llm-cost-estimator` wiring | consumes the cache | cache | T2 | ⚠️ **Correctly handles the exit codes it is told about, and inherits a defect it cannot see.** `estimate_llm_cost.py:271-303` refreshes, distinguishes stale from `needs_review`, and never runs without pricing. But `cache_is_fresh` reads `ttl_hours` from the envelope, so P1(b)'s TTL mutation silently changes the estimator's own refresh cadence. **Fix:** fixing P1(b) closes this; optionally clamp the honoured TTL to a sane floor at the consumer. |
| **pipeline** | `run` | orchestration | network+cache | — | ✅ **Right-sized and the failure policy is now explicit.** The load-bearing/demoted source distinction is stated in code (`fetch_pricing.py:478-483`) rather than implied, and the unpriceable-override sweep (`:527-531`) closes a silent-drop path. |
| **pipeline** | `cache-io` | TTL + atomic writes | cache | — | ✅⚠️ **Atomic writes are correct; durability is not claimed and is not needed.** `_write_json_atomic` (`:418-436`) writes to a same-directory temp file and `os.replace`s, cleaning up on failure — verified that a failed write leaves the previous file intact and no temp files behind. It does not `fsync`, so a machine crash mid-write can lose the new content; acceptable for a regenerable cache. **Fix:** none — note the deliberate choice if durability ever matters. |
| **pipeline** | `validation` | entry gate | pure | — | ✅ **Right-sized.** Tokenizer + non-negative price gate at `:335-361`, extended to nested `catalog` rows without becoming a schema framework. |
| **pipeline** | `sources` | fetch + normalize | network | — | ✅ **Tolerant by design and consistently injectable.** Every fetcher takes a `fetcher` callable (`:184-192`, `:636`), and normalizers skip malformed rows rather than raising (`:125-177`), so one bad upstream entry cannot fail a refresh. This injection pattern is the repo's best structural habit. |

## Emerging themes

- **T1 — One contract, seven restatements.** The exit codes, schema and source
  policy are stated in `fetch_pricing.py`, `README.md`, `skills/llm-pricing/SKILL.md`,
  `.specify/memory/constitution.md`, `specs/001-pricing-query/data-model.md`,
  `specs/001-pricing-query/contracts/query-cli.md` and
  `specs/002-pricing-endpoints/contracts/cheapest-query.md`. This session changed the
  contract once and had to chase it through five files — and still missed two, which
  remain wrong at this commit. It has already caused real harm once: `SKILL.md` told
  agents `source: override` meant authoritative after that stopped being true for 8 of
  9 models. **Shared fix:** designate `SKILL.md` + `README.md` as the only
  human-facing statements and have the spec contracts reference them rather than
  restate; or generate the exit-code/schema block into all seven from one source. The
  symlink now protecting `SKILL.md` is the pattern to copy.
- **T2 — "Degraded" has no first-class representation, so it is smuggled through
  `freshness`.** `_exit_for` (`:745-747`) maps a three-value freshness vocabulary to
  exit codes, but the session added a fourth state — *needs review* — that does not
  fit. The consequences are all one root cause: `review` fakes `"stale"` to get exit 1
  while reporting `fresh`; `price` has no way to express it at all and returns 0; the
  constitution's Principle III is violated because the concept it names has no
  variable. **Shared fix:** make degradation an explicit input to the exit-code
  decision, independent of age.
- **T3 — Resolution trusts a guess where it was told the answer.** `_resolve_slug`
  falls back to fuzzy matching when an explicit pin misses, and no test covers the
  shipped `overrides.json` that supplies those pins. Both are the same posture: the
  mapping from alias to catalog row is assumed correct rather than verified, on the
  path that now prices most models. **Shared fix:** make a declared pin authoritative
  (fail, don't guess) and assert the real data file's shape in CI.

**Meta-observation:** risk sits almost entirely at the **query surface and the data
file** — the two boundaries the session's pipeline work did not reach. The pipeline
itself is now honest about degradation; the surface that agents actually call is not.

## What it does well

- **Dependency injection is universal, not selective.** Every network call takes a
  `fetcher` callable (`fetch_pricing.py:184-192`, `:636`, `run(...)` signature at
  `:472-477`), which is why 103 tests run hermetically in 0.03s with zero references
  to `_default_fetcher`. This is the template for testing anything added later.
- **Tolerant normalizers.** `_normalize_openrouter` and `_normalize_litellm`
  (`:125-177`) skip unusable rows instead of raising, so one malformed upstream entry
  cannot fail a whole refresh.
- **Decisions are recorded in code, not folklore.** The load-bearing vs demoted source
  policy (`:478-483`), the field-name collision with the boolean `baseline` (`:262-263`),
  and the symmetric drift formula's JSON-safety rationale (`:216-228`) are all
  explained where they are implemented — each is a choice a future reader would
  otherwise undo.
- **The cache-hit path is defended by test, not intention.**
  `TestReviewSurvivesCacheHit` injects a fetcher that raises, proving zero network on
  a fresh cache. That is the template `overrides.json` needs.
- **`SKILL.md` is now single-sourced by symlink** — the only one of the seven contract
  statements that structurally cannot drift.

## Highest-leverage fixes

The warnings collapse into three root causes; fixing them clears 9 of the 14 rows.

1. **Give degradation a first-class representation** (T2). Thread a `degraded` flag
   next to `freshness` through `query_main` and `_exit_for`. Clears P1(a) and P1(c),
   satisfies constitution Principle III, and removes the `"stale"`-as-a-lie hack —
   three rows plus the constitution row.
2. **Make a declared `openrouter_slug` authoritative** (T3). Return `None` when a pin
   misses instead of falling through to last-segment matching
   (`fetch_pricing.py:678-682`). Turns a silent wrong price into a `needs_review`
   entry — clears the only `risky` verdict and de-risks `attach_catalog_baseline`.
3. **Stop the query TTL from persisting** (T2). Use the caller's `--ttl-hours` as a
   read-time gate only; never stamp it into the shared envelope
   (`fetch_pricing.py:765`). Clears P1(b) and the consumer-boundary row.

Then, cheaper but overdue: a test over the real `overrides.json` (T3), and updating
the two stale contract files or collapsing the seven restatements (T1).

---

> **⏳ Currentness.** Valid only for commit `9ce70bc` at the time this report was
> written. **A source edit since then can invalidate these findings — re-run
> `/quality-pass` after changes.**
