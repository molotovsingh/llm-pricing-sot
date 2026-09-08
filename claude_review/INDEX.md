# Review index

Chronological history of quality passes. Newest first. One row per commit
reviewed; `quality-pass/latest.md` always mirrors the newest report.

| # | When (IST) | Commit | Branch | Headline | P0 | P1 | P2 | P3 | Report |
|---|---|---|---|---|---|---|---|---|---|
| 3 | 2026-09-08 09:02 | `374f234` | `004-clear-review-queue` | Delta. Whole P1/P2 queue cleared and verified by experiment (faked clock, two-direction guard, 26-invocation differential). No open P0/P1; one human decision left. | 0 | 0 | 1 | — | [2026-09-08-374f234.md](quality-pass/2026-09-08-374f234.md) |
| 2 | 2026-09-08 08:37 | `6a12f98` | `004-clear-review-queue` | All three leverage fixes landed; `risky` cleared. Risk moved into the verification layer — a suite assertion goes red on 2026-11-15, and the drift gate misses two stale restatements in its own source file. | 0 | 1 | 3 | 11 | [2026-09-08-6a12f98.md](quality-pass/2026-09-08-6a12f98.md) |
| 1 | 2026-08-31 09:00 | `9ce70bc` | `002-pricing-endpoints` | First pass. The pipeline's attestation work never reached the query surface; `_resolve_slug` guessed after a retired pin. | 0 | 2 | 7 | 5 | [`agent_review/…/2026-08-31-9ce70bc.md`](../agent_review/quality-pass/2026-08-31-9ce70bc.md) † |

† Run 1 predates this folder and still lives in the legacy `agent_review/` home.
It is linked in place rather than copied, so there is exactly one canonical text
per commit. See "Home migration" in run 2.

## Trend

| | Run 1 (`9ce70bc`) | Run 2 (`6a12f98`) | Run 3 (`374f234`) |
|---|---|---|---|
| right-sized | 9 | 13 | 16 |
| brittle | 3 | 2 | **0** |
| overgrown | 1 | 1 | **0** |
| **risky** | **1** | **0** | **0** |
| P1 | 2 | 1 | **0** |
| P2 | 7 | 3 | **0** |

Cleared between runs: `_resolve_slug` (fuzzy fallback after a retired pin),
`query_main` exit codes (a flagged model returned 0), query-TTL persistence,
`overrides.json` test coverage, the two stale spec contract files, and the four
permanently-unpriceable models.

Opened between runs: a wall-clock-coupled attestation assertion (P1) and two
superseded exit-code docstrings the new gate does not govern (P2).

Cleared in run 3: the dated suite failure, both superseded exit-code
docstrings, `query_main`'s five inline handlers, the ungoverned contract copy
in `checks.sh`, and the gate's backtick-only fence toggle.

Open after run 3: `glm-5.2`'s `verified_at` is still an unconfirmed date --
a human decision, not a code change.
