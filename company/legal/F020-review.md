# F020 — Legal review (match highlights: /highlights + teaser)

**Verdict:** APPROVED — claims registered in-commit; deterministic
templating only; Brand sweep clean.

## Why this review fired

`legal_relevant: true`: a new public route (`/highlights`) publishes
performance-shaped numbers (trade counts, R multiples, pips, TQS,
win/loss outcomes) derived from the shadow-paper tape.

## Claims

Every public field of `agent/platform/highlights.py` is registered in
`company/legal/claim_register.md` §F020 in the same commit, under the
provenance disclaimer "shadow-paper activity/quality metrics, NOT
profit performance". `PROVENANCE_NOTE` is echoed in every API payload
and rendered as an amber banner at the top of the page — the same
labelling posture `/performance` uses ("Past activity is not
indicative of future results" mirrors its lead disclaimer).

## Honesty mechanics reviewed

1. **Recomputability.** Every number in a report is recomputed from
   raw `events.jsonl` rows; the module test asserts equality against
   an independent recomputation, not a snapshot.
2. **Quiet days are honest.** A day with only tick_summary rows says
   so, reusing the I002 quiet-reason vocabulary — no fabricated
   drama, no empty page pretending nothing ran.
3. **No invention.** `trade_story` chapters are stitched exclusively
   from recorded rows; a close with no matching proposal/open tells a
   shorter story rather than inventing one.
4. **Missing tape** renders the F005 empty state.

## Brand sweep

Template strings contain neither "ensemble" nor "aggregator"
(page-level absence is pinned by test). Metaphor voice ("GOAL!",
"The wall holds", "tackles") stays within the established Blue Lock
register used on /v2.

## Research Lead note (research_relevant)

The spec DECLARES the hypothesis "users with access to daily match
reports return on more distinct days" per literature-standards §5.
Nothing in this feature measures it and no engagement number is
published anywhere. Pre-registration of the measurement is a future
Research Lead action once real visitors exist.

## Rolling constraint

Narrative strings must remain deterministic template assembly from
recorded fields. Introducing LLM retelling, or publishing any number
about the declared engagement hypothesis before its pre-registered
experiment reports, requires a fresh Legal review.

— Legal, 2026-07-24 (Sprint 3, F020)
