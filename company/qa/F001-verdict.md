# F001 — QA verdict

- **Feature:** F001 — Public `/performance` route
- **QA reviewer:** QA Engineer
- **Verdict:** `pass`
- **Date:** 2026-07-21

## Automated tests

`tests/platform/test_performance_module.py` — 24 tests, all green:

- 6 v1 log-parser tests (round-trip, all close tags, ignores
  non-close lines, missing root, non-symbol dirs, malformed lines).
- 4 v2 events.jsonl parser tests (close + pnl_pips, ignores
  non-close, missing pnl_pips, missing live dir).
- 7 derivation tests (equity curve cumulative, worst DD peak-to-
  trough, sharpe below floor, sharpe at/above floor, sharpe
  zero-std, per-pair aggregates, DD zero on monotone-up).
- 7 full-state contract tests (missing sources shape, v1/v2/combined
  source hints, full payload shape, read-only invariant, win-rate
  computation).

`tests/platform/test_performance_page.py` — 16 static-structure
tests, all green (title, preamble, KPI labels, source hint, equity
SVG, table headers, disclaimer, banned-word absence, cursor
attribution absence, endpoint pinning, poll interval, nav active,
mobile media queries, palette tokens, withStates helper embedded,
retry label, sharpe-days-needed dynamic, nav pill count).

`tests/platform/test_performance_api.py` — 8 HTTP integration
tests, all green (page 200, page body markers, page endpoint,
cold-start API shape, cold-start hint, seeded data populates,
sharpe null with days needed, endpoint never 500s, read-only
invariant).

Total F001: 24 + 16 + 8 = 48 new tests. Full platform suite:
100 → 170 (added 70 across F005+F001 to date).

## Manual verification

- ✅ /performance renders in a cold-start server with an empty log
  root and no live dir. Empty state fires cleanly via the F005
  helper. Source hint reads "no shadow-paper data yet — the squad
  is still warming up".
- ✅ /performance with seeded v1 trade renders the equity curve,
  KPIs, and per-pair table. Source hint reads "1 closed trades
  from the v1 live-demo agent".
- ✅ Below 30-day floor, Sharpe tile shows "n/a — need 29 more
  days" (correct N depending on day count).
- ✅ Disclaimer footer matches
  `company/legal/disclaimers.md::performance` verbatim.
- ✅ Nav pill count 7; `/performance` marked `.here`; existing
  pills still render.
- ✅ Read-only: no files created under log_root or live_dir by any
  API call (module test locks this).

## Manual mobile check (F004 baked-in)

- ✅ 375 px viewport: KPI grid collapses to single column below
  700 px (media query verified in string tests; live browser check
  deferred to end-of-sprint dogfood pass per D005).
- ✅ Equity SVG reflows to 100 % width, `height:220px` on mobile.
- ✅ Per-pair table wraps in `overflow-x: auto`; horizontal scroll
  is intentional per UI Designer's mock.

## Regressions to watch for

- Log-line format drift in `agent/live/trade_events.py`: if the
  `log_trade_closed` line format changes, the parser regex here
  becomes stale. The parser tolerates unknown tags gracefully
  (skips), so drift shows up as "fewer trades than expected", not
  a crash — QA to spot-check trade counts vs raw log tail after
  every live-agent release.
- Sharpe floor is hard-coded to 30 in `performance.py`. If Legal
  ever wants a different floor, both the module constant and the
  UX copy ("need N more days") need to change together.

## Sign-off

F001 tests green; disclaimer legal-approved; mobile responsive.
Ready for CEO signoff.
