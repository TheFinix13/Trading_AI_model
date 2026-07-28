# v1 weekly review ledger

Registry of every live-window analysis done on the v1 agent, so a new
zip never re-analyzes bars we've already reviewed.

## Protocol (read before analyzing a new zip)

1. Look up **covered-through** below. The new-information window of an
   incoming zip is `(covered-through, zip end]` — analyze ONLY that,
   regardless of how many days the zip spans.
2. Use the overlap region as a **cross-check, not a re-analysis**: the
   zip's numbers for already-covered days must match the prior ledger
   row (realized P&L, closes, incidents). Divergence = data problem or
   phantom bookkeeping — investigate before trusting the new window.
3. After the review: append a row, update covered-through, link the
   review artifact. Keep rows append-only.
4. Positions still open at a window end are carried in the "Open at
   end" column — next week's review must reconcile them first.

**Covered-through: 2026-07-28 15:25 UTC** (agent shutdown for MT5 update).

## Ledger

| Window analyzed | Zip / source | Artifact | Realized P&L (window) | Open at end | Key findings / follow-ups |
|---|---|---|---|---|---|
| ~Jun 16 – Jun 30 (pre-ledger, approximate) | charts + VM logs, no zip | chat only (Jun 30 session) | — | — | First market-replay ritual; led to E011–E016 pipeline sweep + PostLossGuard discussion. |
| Jul 11 – Jul 20 | `weekly_report_2026-07-11_to_2026-07-20.zip` | chat only (Jul 20 session) | +5.74 (GBPUSD 2966547972 +8.88 TP, USDCAD 2963842103 −3.14 soft-SL) | GBPUSD 2969136564 short (Jul 16), USDCAD 2981476697 long (Jul 20) | "Winners exit too early / losers linger" pain → E020–E025 exit-stack pre-registrations; GBPUSD Telegram open-line gap fixed. |
| Jul 20 – Jul 28 | `weekly_report_2026-07-15_to_2026-07-28.zip` (14d zip; Jul 15–19 overlap used as cross-check only) | `docs/reviews/2026-07-28_week_review.md` | +14.83 (GBPUSD 2969136564 +7.96 TP Jul 20 after the prior session, USDCAD 2981476697 +6.87 TP Jul 21) | GBPUSD 3000652586 long (Jul 24, ~−31p), USDCAD 2987854368 long (Jul 21, ~−6p) | Jul 24 I015 phantom closes distorted the bundle report; NEW I016 orphaned-position/soft-stop gap (fix in progress); near-miss resolver: htf_gate blocks net protective; Jul 28 MT5-update outage handled clean. |

## Cross-check log

- **2026-07-28 zip vs Jul 11–20 row**: overlap (Jul 15–20) matches —
  same two GBPUSD TPs, same USDCAD soft-SL loss, same balance path
  948.97→954.71→962.67. One caveat surfaced: the trade tickets the
  Jul 20 session treated as open (GBPUSD 2969136564, USDCAD
  2981476697) both closed at TP within a day — consistent.
