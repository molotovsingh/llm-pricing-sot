# Data Model: Single-sourced pipeline contract

Phase 1. Entities are conceptual — this feature stores nothing new on disk beyond text
already in the repo.

## Entities

### Normative Fact

A rule a reader could act on incorrectly. Each has a stable id, a derivation from the
running code, and a canonical rendering.

| Field | Type | Notes |
|---|---|---|
| `id` | string | `exit-codes` · `envelope` · `trust-rule` |
| `derivation` | callable | Reads `fetch_pricing.py` behaviour; never reads a document |
| `canonical` | string | Deterministic markdown rendering, byte-stable across runs |

Derivations (all verified feasible in `research.md` §R1):

| id | Derived by | Shape |
|---|---|---|
| `exit-codes` | enumerating `_exit_for(freshness, degraded)` across its 6-case domain | table of `(freshness, degraded) → code` |
| `envelope` | `sorted(build_cache(...).keys())` | ordered key list |
| `trust-rule` | per-entry comparison of the documented decision procedure against the `degraded` flag returned by `query price` | assertion over every model in the cache |

**Invariant**: a derivation MUST NOT read any governed document. If it did, the check would
verify documents against each other and re-admit the "all agree, all wrong" failure.

---

### Contract Block

A marked region inside a governed document holding one fact's canonical rendering.

```markdown
<!-- contract:begin exit-codes -->
...canonical rendering...
<!-- contract:end exit-codes -->
```

| Field | Type | Notes |
|---|---|---|
| `fact_id` | string | Must match a known Normative Fact id |
| `body` | string | Compared to `canonical` after normalising line endings and trailing whitespace only |
| `document` | path | The file containing it |

Rules:

- Markers are HTML comments, so they are invisible in rendered markdown.
- A document may hold any number of blocks, at most one per `fact_id`.
- Prose **outside** the markers is free — each audience explains the rule in its own
  register. Only the block is governed. This is what keeps the unit of authority narrower
  than the document (spec, Edge Cases).
- A block whose `fact_id` is unknown is an error, not a skip — it usually means a typo that
  would otherwise silently disable the check for that document.

---

### Governed Document

| Field | Type | Notes |
|---|---|---|
| `path` | path | Repo-relative |
| `role` | `live` \| `historical` | Only `live` documents are checked |
| `facts` | set of `fact_id` | Which facts this document is required to carry |

Registry at feature start:

| Path | Role | Required facts |
|---|---|---|
| `skills/llm-pricing/SKILL.md` | live | `exit-codes`, `trust-rule` |
| `README.md` | live | `exit-codes`, `envelope`, `trust-rule` |
| `.specify/memory/constitution.md` | live | `exit-codes`, `envelope` |
| `.specify/templates/plan-template.md` | live | *(gate text only — see `research.md` §R4)* |
| `specs/001-pricing-query/contracts/query-cli.md` | live | `exit-codes` |
| `specs/001-pricing-query/quickstart.md` | live | `exit-codes`, `trust-rule` |
| `specs/002-pricing-endpoints/contracts/cheapest-query.md` | live | `exit-codes` |
| `specs/001-pricing-query/research.md` | historical | — (exempt) |
| `specs/00*/spec.md` | historical | — (exempt) |

**Exemption is explicit, never inferred** (FR-006): a document is historical because it is
listed as such, not because it looks old. A genuinely stale live document therefore cannot
hide by resembling a record.

---

### Registry

The single list mapping paths to roles and required facts. Lives with the checker.

Validation rules:

- Every `live` entry MUST exist on disk — a renamed or deleted document must fail loudly
  rather than silently drop out of coverage.
- Every `live` entry MUST contain a block for each of its required facts; a missing block is
  a failure, not a pass. Otherwise deleting a block would be a way to opt out of the check.
- A marked block found in a file absent from the registry is a failure (`research.md` §R3),
  which is how copy-paste propagation into a new document is caught.

## State transitions

There is no persistent state. One transition matters, and it is the workflow the feature
exists to make safe:

```
contract behaviour changes in fetch_pricing.py
        │
        ├─ derivations now produce new canonical renderings
        │
        ├─ test suite runs  ──▶  every governed document whose block differs FAILS,
        │                        naming the file, the fact id, and the correct block
        │
        └─ maintainer pastes the printed block into each named document ──▶ suite green
```

Before this feature the middle step did not exist, so the transition ended with an unknown
number of documents silently wrong.
