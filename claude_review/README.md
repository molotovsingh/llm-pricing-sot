# claude_review

Agent review artifacts for this repo. **Reports only — nothing here changes
source.** `quality-pass/` holds recurring engineering-quality passes: one report
per reviewed commit, named `<date>-<short-commit>.md`.

- **`quality-pass/latest.md`** — the current report. Start here.
- **`INDEX.md`** — the run history, mapping runs to commits, with the trend
  across passes. The diff between runs is the point.

A report is valid only for the commit in its banner; each ends with a currentness
footer saying so. Re-run `/quality-pass` after source changes rather than trusting
a stale report.

**History note.** Runs before 2026-09-08 live in the legacy `agent_review/` folder
at the repo root. `INDEX.md` links them in place rather than duplicating them, so
each commit has exactly one canonical report. New runs land here.
