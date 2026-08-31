# Contract: Contract-block syntax and drift checker

Surface: `python -m unittest discover -s tests` (the existing suite; no new command).

The checker is a test module, not a CLI. It has no flags, no network access, and no output
on success — a maintainer never invokes it directly, they just run the suite.

## Block syntax

```markdown
<!-- contract:begin <fact-id> -->
<canonical rendering>
<!-- contract:end <fact-id> -->
```

- Markers are HTML comments: invisible in rendered markdown, greppable in source.
- `<fact-id>` ∈ `exit-codes` · `envelope` · `trust-rule`.
- At most one block per fact id per document.
- Everything outside the markers is free prose and is never inspected.

### What counts as a real block

A marker is a real block only when **all three** hold (`research.md` §R5):

1. it starts at **column 0** — excludes inline mentions inside backticks;
2. it is **outside any fenced code block** — excludes syntax examples like the one above;
3. its fact id is **known** — excludes the `<fact-id>` placeholder.

Without these rules the unregistered-marker guard fails on this very document. Note that the
example above is itself excluded by rules 1–3, which is the intended behaviour and the
cheapest available test of them.

Rule 3 governs *recognition* only. Once a block is recognised, an unknown fact id inside it
is still a hard error — see the behaviour table.

## The facts

### `exit-codes`

Derived by enumerating `_exit_for(freshness, degraded)`. Canonical rendering:

```markdown
| freshness | degraded | exit |
|---|---|---|
| `fresh` | no | `0` |
| `fresh` | yes | `1` |
| `stale` | no | `1` |
| `stale` | yes | `1` |
| `no-data` | no | `2` |
| `no-data` | yes | `2` |
```

Meaning, fixed prose inside the block: `0` clean · `1` served but degraded (stale **or**
the answer's entry is in `needs_review`) · `2` no usable data.

### `envelope`

Derived from `sorted(build_cache(...).keys())`. Canonical rendering is the ordered key
list: `fetched_at`, `freshness`, `models`, `needs_review`, `ttl_hours`.

### `trust-rule`

Canonical rendering states the decision procedure:

- `baseline: false` → the model is tracked by the SOT; use this price.
- `source` explains provenance only — `override` is an attested rate, `openrouter`/`litellm`
  is the live catalog price. **`source` does not gate trust.**
- `baseline: true` → discovery data, not a tracked model; informational only.
- `degraded: true` → usable but stale or in `needs_review`.

Verified operationally, not textually: for every model in the emitted cache, the procedure
above MUST reach the same usability decision as the `degraded` flag returned by
`query price`. This catches a wrong rule; it does not catch a confusingly-worded one.

## Generator behaviour

The writer rewrites canonical blocks in place, so a contract change costs one hand-edited
file (`research.md` §R2, SC-001).

| Aspect | Behaviour |
|---|---|
| Scope of writes | **Only** the text between markers, in registered live documents |
| Prose outside markers | Never read, never written |
| Missing block in a live document | Reported, not silently inserted — placement is an editorial choice |
| Unregistered file | Never written |
| Idempotence | Running twice with no code change produces no diff |
| Invocation | On demand only; never as part of the test run, so the gate cannot self-heal and hide drift |

## Checker behaviour

| Condition | Result |
|---|---|
| Every live document carries every required block, all matching | pass, silent |
| A block's body differs from canonical | **fail** — names path, fact id, and prints the correct block verbatim |
| A required block is missing from a live document | **fail** — deleting a block must not be a way to opt out |
| A registered live document does not exist on disk | **fail** — a rename must not silently drop coverage |
| A *real* block appears in a file not in the registry | **fail** — catches copy-paste into a new document |
| A marker appears indented, inside a code fence, or with an unknown id | ignored — not a real block (see above) |
| An unknown `<fact-id>` appears inside a recognised block | **fail** — a typo must not silently disable a check |
| A historical document states a superseded rule | pass — exemption is explicit and intended |

Comparison normalises line endings and trailing whitespace only. There is no semantic
tolerance: a reworded block is a failure, because the block is the normative statement.

## Guarantees

- **No network.** Pure file I/O over repo-local paths (constitution Principle V).
- **No new dependency, no build step** (Principle I).
- **Runs in the default suite**, so coverage is automatic rather than remembered
  (Development Workflow).
- **Failure output is the fix**: the printed canonical block is pasted between the markers,
  or the generator is run to write every block at once.

## Non-guarantees

- Does **not** verify prose outside the markers.
- Does **not** detect a fresh restatement written in a new document without copying a marked
  block. Convention only — see `quickstart.md`.
- Does **not** prevent drift, only detect it, so a document is briefly wrong between a code
  edit and the next suite run (`research.md` §R2).
