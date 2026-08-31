# Quickstart: changing a contract rule

Phase 1. What a maintainer or agent does once this feature ships.

## Changing a normative rule

1. Change the behaviour in `fetch_pricing.py` (e.g. add a new exit-code case).
2. Run the suite:

   ```bash
   python -m unittest discover -s tests
   ```

3. The drift check fails, naming every governed document that now disagrees and printing
   the correct block for each:

   ```
   FAIL: test_governed_documents_match_derived_facts
     skills/llm-pricing/SKILL.md [exit-codes] is stale. Replace the block with:

     | freshness | degraded | exit |
     |---|---|---|
     ...
   ```

4. Run the generator to write every block at once:

   ```bash
   python tests/test_contract_drift.py --fix
   ```

5. Re-run the suite. Green.

One hand-edited file (the code); no document edited by hand; none left disagreeing. For a
single-document change you can paste the printed block instead — the failure message
contains it verbatim.

The generator writes **only** between markers. Prose outside them is never touched, and it
never runs as part of the test run — a gate that could silently repair itself would hide the
drift it exists to report.

## Adding a governed document

Add the path, role, and required facts to the registry beside the checker, then paste the
blocks in. The suite fails until both are done, which is the point: registering a document
without its blocks, or adding blocks without registering, are both errors.

## Writing a new document that mentions the contract

If a new document needs to state an exit code, envelope field, or the trust rule:

- **Copy the marked block** from a governed document, and register the new file. The
  checker fails on a marked block in an unregistered file, so copy-paste alone will remind
  you.
- **Or reference instead of restating** — link to `skills/llm-pricing/SKILL.md` or the
  constitution rather than repeating the rule. This is preferred; the cheapest restatement
  is the one that does not exist.

Writing a *fresh* restatement in your own words, without copying a block, is the one case
tooling cannot catch. Don't.

## Writing a historical record

`research.md` and `spec.md` files record what was decided at a point in time and **must not
be updated** when behaviour changes later. Mark the superseded statement in place, as
`specs/001-pricing-query/research.md:51` does:

```markdown
*(Superseded: exit `1` was later widened from "stale" to "served but degraded".
This is a point-in-time decision record; the live contract is constitution Principle III.)*
```

Do not add contract blocks to historical documents. They are exempt by registry entry, not
by appearance.

## Checking without changing anything

```bash
python -m unittest tests.test_contract_drift -v
```

Silent pass means every live document agrees with shipped behaviour. This is also the fast
way to audit after a merge that touched documentation.
