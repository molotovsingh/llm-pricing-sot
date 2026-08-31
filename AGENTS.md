## Spec-Kit

This repository uses the [spec-kit](https://github.com/github/spec-kit) workflow for AI-assisted feature development.
Spec-kit is a convention for structuring feature specs, plans, and tasks in a `.specify/` directory so that AI agents can read and act on them.
This project uses an opinionated local tooling layer to generate the artifacts that live there — the source of truth for the workflow itself is the spec-kit repo linked above.

### `.specify/` directory

| Path | Purpose |
|------|---------|
| `.specify/templates/` | Markdown templates for specs, plans, tasks, and checklists |
| `.specify/memory/` | Long-lived context files (e.g. `constitution.md`) read by agents |
| `.specify/scripts/` | Helper shell scripts for common workflow steps |
| `.specify/hooks.yml` | CI/automation hook definitions |

### How to use it

- Start a new feature: `/speckit-specify` — creates a spec from a template and opens a clarification loop.
- Generate a plan: `/speckit-plan` — converts an approved spec into a structured plan.
- Break into tasks: `/speckit-tasks` — decomposes a plan into trackable tasks.
- Implement: `/speckit-implement` — works through tasks and updates checklists.

## The pipeline contract is single-sourced

Three normative facts — exit-code meanings, the cache envelope schema, and the trust rule —
are **derived from `fetch_pricing.py`** and compared against a marked block in each governed
document. Before this, the same rules were restated in ten places and drifted silently; one
stale copy told agents that `source: override` meant authoritative after that became true
for one model in nine.

| Task | Do this |
|------|---------|
| Change a contract rule | Edit `fetch_pricing.py`, then `python tests/test_contract_drift.py --fix` |
| See what drifted | `python -m unittest discover -s tests` — the failure names each file and prints the correct block |
| Add a governed document | Add markers, register it in `GOVERNED` in `tests/test_contract_drift.py`. Both, or the suite fails |
| Write a doc that mentions the contract | **Reference** it rather than restating. The cheapest restatement is the one that doesn't exist |
| Write a spec `research.md` / `spec.md` | Nothing — they are exempt by declared path rule and must keep stating what was decided *then* |

Blocks look like this, and only the text between the markers is machine-owned — prose
outside them is yours:

    <!-- contract:begin exit-codes -->
    ...generated...
    <!-- contract:end exit-codes -->

Two rules worth knowing: a marker only counts at column 0 outside a code fence, so
documentation can show the syntax freely; and the generator never runs during the test run,
because a gate that repairs itself hides the drift it exists to report.
