# Feature Specification: Single-sourced pipeline contract

**Feature Branch**: `003-contract-single-source`
**Created**: 2026-08-31
**Status**: Draft
**Input**: User description: "Make the load-bearing parts of the pipeline contract single-sourced so a behaviour change cannot leave an agent-facing document silently wrong"

## Context

`fetch_pricing.py` publishes a contract with three normative parts: **exit-code
meanings**, the **cache envelope schema**, and the **trust rule** for deciding whether a
price is usable. Those statements are currently repeated across nine documents with no
authoritative source, so changing behaviour means finding and correcting an unbounded set
of readers by hand.

Measured cost over one working session: the contract changed twice (exit `1` widened from
*stale* to *stale-or-degraded*; `source: override` stopped implying *authoritative*), and
propagation took **four commits**, each discovering documents the previous had missed —
`e807849`, `234dc5f`, `9ce70bc`, `92c3d52`.

The readers are not equally risky. `skills/llm-pricing/SKILL.md` is loaded by agents before
pricing decisions; for a period it stated that `"source": "override"` meant authoritative,
which was true for 9 of 9 models when written and 1 of 9 afterwards. An agent obeying it
would have rejected eight correct prices. The same wrong claim survived two commits longer
in `specs/001-pricing-query/quickstart.md`. The 120-test suite verifies the implementation
and never the documents describing it, so nothing detects this class of error.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An agent is never told a rule the code contradicts (Priority: P1)

An agent loads the `llm-pricing` skill to price a model. Whatever the skill says about exit
codes, the envelope, and which prices to trust matches what `fetch_pricing.py` actually
does — not because someone remembered to update it, but because it cannot be otherwise.

**Why this priority**: This is the only reader whose staleness has caused real harm, and the
harm is silent and financial (an agent mis-reading trust rules on money numbers). Solving
this one reader alone is a viable MVP: it removes the demonstrated failure while leaving the
lower-risk documents to be judged separately.

**Independent Test**: Change a normative rule at its source, run the pipeline's own checks,
and confirm the skill reflects the change with no hand-editing; then deliberately desync the
skill and confirm the change is reported rather than shipped.

**Acceptance Scenarios**:

1. **Given** a contract rule is changed at its source, **When** the maintainer makes no
   other edit, **Then** the skill's normative statements reflect the new rule.
2. **Given** the skill's normative statements are edited to disagree with shipped behaviour,
   **When** the default checks run, **Then** they fail and name the disagreeing statement.
3. **Given** the skill's prose explanation is reworded without changing meaning, **When** the
   checks run, **Then** they pass — prose is hand-written and not policed.

---

### User Story 2 - Drift is reported, not discovered by accident (Priority: P2)

A maintainer changes contract behaviour. Instead of learning months later which documents
are wrong, they get a single failure listing every live document that now disagrees.

**Why this priority**: Detection is cheaper than generation and covers all live readers at
once, but it is a safety net rather than a guarantee — it tells you what to fix instead of
preventing the mistake. Valuable independently of Story 1.

**Independent Test**: Desync each live document in turn and confirm the check names it;
confirm a clean tree passes.

**Acceptance Scenarios**:

1. **Given** any live document's normative block disagrees with the source, **When** the
   default test suite runs, **Then** it fails and names the file and the statement.
2. **Given** all live documents agree, **When** the suite runs, **Then** it passes with no
   network access.
3. **Given** a historical spec artifact states a superseded rule, **When** the suite runs,
   **Then** it passes — history is exempt by design.

---

### User Story 3 - Human-facing contract docs stay correct (Priority: P3)

`README.md` and the constitution state the same rules for maintainers and for agents doing
feature work. They stay correct without separate effort.

**Why this priority**: Real but lower-stakes — these readers are humans and agents who are
reading deliberately, more likely to notice an inconsistency than an agent following a skill
at decision time. Worth doing once the mechanism from Stories 1–2 exists.

**Acceptance Scenarios**:

1. **Given** a contract change, **When** it is made at the source, **Then** `README.md` and
   the constitution's normative statements agree with it.

---

### Edge Cases

- **Historical artifacts must not be "fixed".** `specs/*/research.md` and `spec.md` are
  point-in-time decision records; rewriting them destroys the history spec-kit exists to
  keep. `research.md:51` already carries an explicit supersession note — the mechanism must
  treat that as correct, not as drift.
- **The authoritative statement can itself be wrong.** Single-sourcing removes disagreement between
  documents; it does not prove any of them match the code. A statement that drifts from
  `fetch_pricing.py` while all documents agree is still undetected unless the source is
  anchored to observable behaviour.
- **Paraphrase vs restatement.** Documents legitimately explain the same rule in different
  registers (a skill tells an agent what to do; the constitution says what MUST hold).
  Requiring byte-identical text would force unreadable docs; requiring nothing detects
  nothing. The unit of authority needs to be narrower than "the document".
- **A new document is added** that restates the contract without being registered — it is
  invisible to any check keyed off a known list.
- **Partial adoption.** While only some documents are single-sourced, the others still drift;
  the check must not imply coverage it does not have.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST have exactly one authoritative statement of each normative
  contract element — exit-code meanings, cache envelope schema, and the trust rule.
- **FR-002**: The agent-facing skill's normative statements MUST be **written by the
  generator and verified by the gate** against that authoritative statement — never
  maintained independently (`research.md` §R2).
- **FR-003**: The system MUST detect and report when a live document's normative statement
  disagrees with the authoritative one, naming the file and the specific statement.
- **FR-004**: The check MUST run as part of the default test suite and MUST NOT access the
  network (constitution Principle V).
- **FR-005**: The system MUST NOT introduce a third-party dependency or a build step
  (constitution Principle I: stdlib-only, clone-and-run).
- **FR-006**: Historical spec artifacts MUST be exempt by a **declared rule**, never by
  inference from a document's content or apparent age, so a genuinely stale live document
  cannot hide by looking historical. A path rule (e.g. `specs/*/research.md`) satisfies
  this; "it reads like a record" does not.
- **FR-007**: Prose and examples MUST remain hand-written; only normative statements are
  governed.
- **FR-008**: Adding a new document that restates the contract MUST NOT silently escape the
  check. Resolved (`research.md` §R3): an explicit registry of governed documents, hardened
  by failing when a real contract block appears in an unregistered file. A **real** block is
  one at column 0, outside any fenced code block, bearing a known fact id (`research.md`
  §R5) — so documentation may show the syntax without tripping the guard.
- **FR-009**: The authoritative statement MUST be **derived from the running code**, not
  held in any document. Resolved (`research.md` §R1): a document source cannot detect the
  case where every document agrees and all are wrong — a failure this repo has already had,
  when the constitution claimed canonical status for exit codes while being stale itself.
- **FR-010**: The system MUST both **assert** agreement (a gate that fails on drift in the
  default suite) and **generate** the canonical blocks on demand (a stdlib writer that
  rewrites them in place). Resolved (`research.md` §R2, revised): assertion alone leaves
  SC-001 unachievable; generation alone leaves drift silent until someone runs the writer.

### Key Entities

- **Normative statement**: A rule a reader could act on incorrectly — an exit-code meaning,
  an envelope field, or a trust rule. Distinct from prose that explains or motivates it.
- **Live document**: A document describing current behaviour, which must never disagree with
  the code. Today: `README.md`, `skills/llm-pricing/SKILL.md`,
  `.specify/memory/constitution.md`, and the `specs/*/contracts/` and `quickstart.md` files.
- **Historical artifact**: A point-in-time record whose value is that it does *not* change.
  Today: `specs/*/research.md` and `specs/*/spec.md`.
- **Authoritative statement**: The single origin of each normative fact. Derived from the
  running code, never held in a document (`research.md` §R1). Used consistently under this
  name across spec, plan, research and data-model.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Changing a normative contract rule requires **one hand-edited file** (the
  code) plus running the generator; no live document is edited by hand and none is left
  disagreeing. Baseline: the last two contract changes each took four commits across seven
  hand-edited documents.
- **SC-002**: A deliberately desynced live document is reported by the default test suite in
  a single run, naming the file — verified by desyncing each governed document in turn.
- **SC-003**: At any commit, **zero** live documents disagree with shipped behaviour on exit
  codes, envelope schema, or the trust rule.
- **SC-004**: The default test suite still runs with no network access and no third-party
  packages, and its runtime grows by less than one second.
- **SC-005**: An agent following `skills/llm-pricing/SKILL.md` alone reaches the same
  usability decision the code makes, for every model in the emitted cache — including
  entries in `needs_review`.
