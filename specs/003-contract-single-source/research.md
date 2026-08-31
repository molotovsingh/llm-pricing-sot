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

> **Revised after `/speckit-analyze` finding F3.** The first decision was *assert only*.
> Analysis showed that choice made SC-001 unachievable — SC-001 requires a rule change to
> cost one hand-edited file, while assert-only costs one code edit plus a manual paste into
> every governed document. Re-examining the rejection also showed its main premise was
> wrong: see below. Recorded rather than silently amended, because the reasoning is the
> useful part.

**Decision**: **Both, with distinct roles.** Assertion is the *gate*: the test suite fails
on any drift. Generation is the *remedy*: an on-demand stdlib writer rewrites the canonical
blocks in place. Documents are machine-written **only between the markers**; all prose
outside them remains hand-written and untouched.

**Rationale**: The original rejection rested on "generation would require a build step,
which contradicts clone-and-run." That premise does not survive checking. Constitution
Principle I forbids *third-party dependencies* and an *install step*; a stdlib writer
invoked on demand adds neither — it is the same kind of artifact as `fetch_pricing.py`
itself, which already writes files. No build step is introduced because nothing must run
before the repo works; the writer is only used when a contract rule changes.

The surviving objection — that documents become partly machine-owned — is real but already
bounded by the block design: ownership stops at the markers, which is precisely the scope
the feature intends to govern. Paying for that with an unachievable success criterion was
the wrong trade.

Keeping assertion as the gate matters independently: generation alone would leave a document
wrong until someone remembered to run the writer, whereas the suite fails on every run.

**Residual risk, accepted**: a maintainer can still edit inside the markers by hand and be
briefly out of step until the next suite run. Bounded by the Development Workflow rule that
the suite runs before work is marked done.

**Alternatives considered**:

- *Assert only* — rejected on re-analysis: leaves SC-001 unachievable and the N-file chase
  intact, merely guided.
- *Generate only, no gate* — rejected: drift would persist silently until someone chose to
  run the writer, which is the status-quo failure mode with an extra step.
- *Manual discipline* — rejected. This is the status quo, and it failed four times in one
  session (`e807849`, `234dc5f`, `9ce70bc`, `92c3d52`).

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

## R5 — What counts as a real marker? (raised by `/speckit-analyze` finding F1)

**Problem**: The unregistered-marker guard from R3 fails on any `contract:begin` found in an
unregistered file. But this feature's own documents contain that literal four times —
`contracts/contract-block.md:11` and `data-model.md:37` show the syntax inside fenced code
blocks, and `tasks.md` mentions it inline twice. As first specified, the guard would fail on
the documentation that defines it. It was unimplementable.

**Decision**: A marker counts as a **real block** only when all three hold:

1. it begins at **column 0** (excludes inline mentions inside backticks in prose);
2. it is **not inside a fenced code block** (excludes syntax examples);
3. its **fact id is known** — one of `exit-codes`, `envelope`, `trust-rule` (excludes the
   `<fact-id>` placeholder used in examples).

All four existing occurrences are excluded by rules 1–2, and the two in code fences are
excluded twice over. Documentation can therefore show the syntax without special-casing.

**Rationale**: Each rule is mechanical and needs no heuristics. Rule 3 also preserves the
separate guarantee that an unknown fact id is an *error* rather than a skip — that check
applies to blocks that already passed rules 1–2, so a typo inside a real block still fails
loudly while a placeholder in an example does not.

**Alternatives considered**:

- *Exclude `specs/003-*/**` from the walk* — rejected: weakens FR-008 permanently to fix a
  presentation problem, and any future document explaining the syntax would need the same
  exemption.
- *Escape the markers in documentation* (e.g. zero-width characters) — rejected: makes the
  syntax uncopyable, which defeats the purpose of documenting it.

---

## Consolidated decisions

| # | Question | Decision | Reversibility |
|---|---|---|---|
| R1 | Authoritative statement | The running code, via derivation | Low cost to change — the checker's fact-extraction layer is isolated |
| R2 | Generate vs assert | **Both**: assert as the gate, on-demand stdlib writer as the remedy (revised — see F3) | Low — the writer is additive to the gate |
| R3 | Governed-file discovery | Explicit registry + unregistered-marker guard | Trivial — registry is a list |
| R4 | Stale plan-template gate | Reference the constitution instead of restating it | Trivial |
| R5 | Marker recognition | Column 0 + outside code fences + known fact id | Trivial — three predicates |
