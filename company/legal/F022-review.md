# F022 — Legal review (leaderboard groundwork: standings table)

**Verdict:** APPROVED — claims registered in-commit; header framing
pre-approved as specified; Brand sweep clean.

## Why this review fired

`legal_relevant: true`: `/leaderboard` is a new public route whose
entire content is performance-shaped ranking numbers (closed-trade
count, cumulative R, mean TQS, win rate per agent and per pair).
Rankings invite comparison claims, which is exactly the surface the
register exists to police.

## Claims

Every public field of `agent/platform/leaderboard.py` (`standings`
accessor + `PROVENANCE_NOTE` / `GROUPINGS` / `WINDOWS_SUPPORTED`
constants) is registered in `company/legal/claim_register.md` §F022
in the same commit, under the provenance disclaimer "internal squad
standings on a demo feed — shadow-paper activity/quality metrics,
NOT investment performance". Every payload names its computation
window (`window_label`) and its sample scope (`total_closed`), and
the page header repeats both in plain words.

## Honesty mechanics reviewed

1. **Insufficient-sample rule (rolling constraint, SHARED with
   F021 — same rule, same constant).** The module reuses
   `players.MIN_FORM_SAMPLE` (5): below 5 closed trades the win-rate
   is `None` in the payload and the UI renders the literal
   "insufficient sample (n=…)" note — no percentage is ever computed
   from a sub-5 sample. Pinned by module tests (n=2, n=5 boundary)
   and a page-wiring test. Rendering any percentage below the floor,
   or lowering the constant, requires a fresh Legal review.
2. **Recomputability.** Standings are equality-tested against
   independent recomputations from fixture rows for both groupings
   and all three windows — not snapshotted.
3. **No external comparison.** The header states the rankings are
   internal squad standings on a demo feed, one install ranked within
   itself. "Best squad" claims against any external benchmark are out
   of scope (spec §Scope-out) and the framing is pinned by test;
   cross-user ranking stays blocked on the D115 auth migration.
4. **Deterministic ordering.** Cumulative R desc, mean-TQS tie-break,
   entity-name stability — pinned by test, so the same tape can never
   render two different tables.
5. **Empty history is honest.** No closes in the window renders the
   F005 empty state ("standings appear after the first close"), never
   a fabricated table.

## Brand sweep (character-voice co-check)

The page copy uses the established squad register ("league table",
"striker in form") and contains neither "ensemble" nor "aggregator"
(pinned by test on both the module source and the page). No profit
language, no "verified", no forward-looking claims.

## Rolling constraints (on tape)

- The shared F021/F022 insufficient-sample rule (claim register
  §F022).
- The "internal squad standings" framing is load-bearing: any future
  cross-install or benchmark-comparison copy requires a fresh Legal
  review under the D115 auth-migration charter's Phase-2 gates.
