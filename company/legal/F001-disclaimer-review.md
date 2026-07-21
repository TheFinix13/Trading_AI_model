# F001 — Legal disclaimer review

- **Feature:** F001 — Public `/performance` route
- **Reviewer:** Legal
- **Verdict:** `pass`
- **Date:** 2026-07-21

## What was reviewed

The rendered `/performance` page includes:

1. A **preamble** — "This is the demo-account P&L for our live
   zones agent and the paper equity curve for the striker squad,
   updated bar-by-bar. Every number here is a real number the
   platform wrote to disk — no back-tests, no cherry-picks."
2. A **source hint** — dynamic string from
   `performance.get_state()['source_hint']`, one of three shapes
   ("v1 live-demo agent", "shadow-paper fills from the v2 squad",
   or "combined view: N + M"). All three variants reviewed.
3. **KPI tiles** — 5 tiles surfacing days_live, net_pips,
   worst_dd_pips, win_rate_pct, sharpe_or_null. Each tile has a
   foot line describing what the number means.
4. **Equity curve SVG** — inline chart, no claim beyond the raw
   number.
5. **Per-pair breakdown table** — factual table of aggregates.
6. **Disclaimer footer** — the `performance` entry from
   `company/legal/disclaimers.md`.

## Verdict

`pass` — all copy checked against the claim register in
`disclaimers.md`; no banned-claim phrasing appears; the disclaimer
footer is verbatim from the library.

## Specific checks

| Requirement | Verdict |
|---|---|
| Disclaimer footer present and verbatim from `disclaimers.md`. | ✅ |
| No implied claim beyond the raw numbers (e.g. no "we outperform"). | ✅ |
| "Demo / shadow-paper account, no real money" clause visible. | ✅ |
| Sharpe metric shows "n/a — need N more days" below 30-day floor. | ✅ (module-tested) |
| Source hint names the specific data source used. | ✅ |
| No user testimonials or forward projections. | ✅ (there are none). |
| "Ensemble" / "aggregator" not present in user-visible copy. | ✅ |
| Third-party name usage (Blue Lock characters) — none on this page. | ✅ (F001 does not surface character names). |

## Claim register update

Added to `disclaimers.md`:

- F001 "closed trades on tape" — traces to
  `performance.get_state()['trades_total']`.
- F001 "net pips" — traces to
  `performance.get_state()['net_pips']`.
- F001 "worst drawdown" — traces to
  `performance.get_state()['worst_dd_pips']`.
- F001 "Sharpe" (only when ≥ 30 daily returns) — traces to
  `performance._sharpe_or_null()`.

## Sign-off

F001 disclaimer surface cleared for CEO signoff.
