# Research: Single-sourced pipeline contract

Phase 0. Resolves the three `NEEDS CLARIFICATION` items in `spec.md` (FR-008, FR-009,
FR-010) plus one defect discovered while filling the plan's Constitution Check.

These were put to the maintainer as open questions before planning and not answered
individually; each decision below is the recommended option, recorded with its rationale so
it can be overridden cheaply. **R2 is the one most worth a second opinion** — it is a
judgment about how much of the documentation should be machine-owned.

---

## R1 — Where does the authoritative statement live? (resolves FR-009)

**Decision**: The **running code**. The checker derives each normative fact from
`fetch_pricing.py` at test time. No document is the source.

**Rationale**: Verified that all three fact groups are mechanically derivable:

| Fact | Derived from | Verified output |
|---|---|---|
| Exit-code table | enumerating `_exit_for(freshness, degraded)` over its 6-case domain | `(fresh,F)→0 (fresh,T)→1 (stale,*)→1 (no-data,*)→2` |
| Envelope schema | keys of `build_cache(...)` | `fetched_at, freshness, models, needs_review, ttl_hours` |
| Trust rule | per-entry agreement between a document's stated decision procedure and the `degraded` flag `query price` returns | 9 models, 4 flagged, sources `{openrouter, override}` |

A document-as-source cannot detect the failure mode where every document agrees with every
other and all of them are wrong. That is not hypothetical here: the constitution *already
claimed* canonical status for exit codes (Principle III) and was itself stale relative to
spec 002's demotion of LiteLLM for roughly two days — a document source that had already
silently failed once.

**Alternatives considered**:

- *Constitution as source* — rejected. It cannot self-verify against behaviour, and has
  demonstrably drifted from it before.
- *A new `CONTRACT.md`* — rejected. Adds an eleventh location with the same failure mode;
  single-sourcing to a document just relocates the problem.

**Known limitation, accepted**: the trust rule is semantic prose, and only its *operational
consequence* is checkable (does the documented procedure reach the same usability decision
the code reaches, for every model in the cache?). A document could therefore explain the
rule confusingly and still pass. The check catches wrongness, not unclarity.

---

## R2 — Generate the blocks, or assert them? (resolves FR-010)

**Decision**: **Assert.** The checker compares each governed document's marked block against
the derived facts and fails with the correct block printed in the failure message.
Documents are never written by tooling.

**Rationale**: Generation would require a build step, which contradicts the repo's stated
clone-and-run property (constitution Principle I) and would make hand-written prose partly
machine-owned. Assertion runs inside the existing `python -m unittest discover -s tests`
invocation that the constitution's Development Workflow already mandates, so it is not a new
discipline anyone has to remember. Because the failure message contains the exact correct
block, fixing drift is a copy-paste — most of generation's benefit at a fraction of its cost.

**Residual risk, accepted**: assertion detects drift rather than preventing it, so a
document is briefly wrong between the code edit and the test run. Bounded by the workflow
rule that the suite runs before work is marked done.

**Alternatives considered**:

- *Generate blocks into documents* — rejected for the build-step and ownership reasons
  above. Reconsider if the governed set grows well beyond ~10 documents, where copy-paste
  fixing stops being cheap.
- *Manual discipline* — rejected. This is the status quo, and it failed four times in one
  session (`e807849`, `234dc5f`, `9ce70bc`, `92c3d52`).
- *A `--fix` mode that rewrites blocks on request* — deferred, not rejected. It is a small
  addition to the assert design and can be added if copy-paste proves annoying; building it
  now would be speculative.

---

## R3 — Is an allow-list of governed files acceptable? (resolves FR-008)

**Decision**: **Yes — an explicit registry**, hardened with one exactness guard: the checker
also fails when a marked block appears in a file that is *not* registered.

**Rationale**: Automatically recognising "a contract statement" in arbitrary prose is an NLP
problem with a bad false-positive profile — it would flag historical artifacts, examples,
and this very research file. The registry is small (seven documents), reviewed, and lives
beside the check. The realistic way an unregistered restatement appears is copy-paste from a
governed document, which carries the marker with it — so the guard catches the likely case
exactly, without heuristics.

**Alternatives considered**:

- *Full-repo heuristic scan for contract-like prose* — rejected: false positives on the two
  intentionally-historical artifacts and on spec examples; unbounded maintenance.
- *No registry, govern everything* — rejected: would force historical records to be
  rewritten, destroying the point-in-time history spec-kit exists to preserve.

**Residual risk, accepted**: someone writes a *fresh* restatement in a new document without
copying a marked block. Mitigated by convention (documented in `quickstart.md`), not by
tooling. Accepted because the alternative costs more than the failure.

---

## R4 — Defect found while planning: the plan template's own gate is stale

**Decision**: Correct `.specify/templates/plan-template.md` and add it to the governed set.

**Finding**: The template's Constitution Check gate reads *"SOT precedence honored: overrides
> LiteLLM > OpenRouter"*. Constitution v2.0.0 (`234dc5f`, Principle II) amended this to
**overrides > OpenRouter catalog > LiteLLM**, aligning with spec 002's demotion of LiteLLM
and with the price-inheritance path. The template has therefore been asking every feature
planned since to verify a superseded rule.

**Why it matters beyond a typo**: this is a tenth instance of the problem this feature
exists to solve, and it was found by *using* the artifact rather than by reviewing it —
which is exactly how the other nine were found. It also demonstrates the blast radius is
wider than the document set: a stale gate propagates into every future feature's plan.

**Rationale for including it in scope**: leaving it means future plans keep checking the
wrong rule, and the fix is one line.

---

## Consolidated decisions

| # | Question | Decision | Reversibility |
|---|---|---|---|
| R1 | Source of truth | The running code, via derivation | Low cost to change — the checker's fact-extraction layer is isolated |
| R2 | Generate vs assert | Assert, failure prints the correct block | Low — generation could be layered on later as `--fix` |
| R3 | Governed-file discovery | Explicit registry + unregistered-marker guard | Trivial — registry is a list |
| R4 | Stale plan-template gate | Fix and govern it | Trivial |
