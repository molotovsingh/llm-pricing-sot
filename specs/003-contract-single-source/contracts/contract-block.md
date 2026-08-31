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

## Checker behaviour

| Condition | Result |
|---|---|
| Every live document carries every required block, all matching | pass, silent |
| A block's body differs from canonical | **fail** — names path, fact id, and prints the correct block verbatim |
| A required block is missing from a live document | **fail** — deleting a block must not be a way to opt out |
| A registered live document does not exist on disk | **fail** — a rename must not silently drop coverage |
| A block appears in a file not in the registry | **fail** — catches copy-paste into a new document |
| An unknown `<fact-id>` appears in any block | **fail** — a typo must not silently disable a check |
| A historical document states a superseded rule | pass — exemption is explicit and intended |

Comparison normalises line endings and trailing whitespace only. There is no semantic
tolerance: a reworded block is a failure, because the block is the normative statement.

## Guarantees

- **No network.** Pure file I/O over repo-local paths (constitution Principle V).
- **No new dependency, no build step** (Principle I).
- **Runs in the default suite**, so coverage is automatic rather than remembered
  (Development Workflow).
- **Failure output is the fix**: the printed canonical block is pasted between the markers.

## Non-guarantees

- Does **not** verify prose outside the markers.
- Does **not** detect a fresh restatement written in a new document without copying a marked
  block. Convention only — see `quickstart.md`.
- Does **not** prevent drift, only detect it, so a document is briefly wrong between a code
  edit and the next suite run (`research.md` §R2).
