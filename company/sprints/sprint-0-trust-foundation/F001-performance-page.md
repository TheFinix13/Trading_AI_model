# F001 — Public `/performance` route

- **Priority:** P0
- **Sprint:** Sprint 0 · Trust Foundation
- **Owner (build):** Frontend + Backend
- **Reviewers:** UX Researcher, UI Designer, Brand Designer, CTO,
  QA, Legal, CEO
- **Current stage:** `spec`
- **Written by:** CPO

## User story

> As a **prospect evaluating an AI trading product**, I want to
> land on `/performance` and see — within 10 seconds and without
> reading a paragraph — what the platform's actual results look
> like, so that I can decide whether it's worth clicking further.

Corollary stories:

> As a **user with an account (Sprint 1+ audience)**, I want to
> see the same performance page and know it's the same numbers a
> prospect sees, so that I trust the platform isn't showing me a
> flattering view.

> As a **journalist / researcher**, I want to link a specific
> equity-curve moment ("this drawdown in April") and have the URL
> resolve to that view.

## Acceptance criteria

The feature is done when:

1. `GET /performance` returns 200 and renders the page without
   auth on localhost binds (same auth model as `/`, `/v1`, `/v2`).
2. Above the fold on desktop (1440 × 900) the user sees, in order:
   (a) an equity-curve chart (SVG, no external chart lib —
   framework-free per CTO), (b) 4 headline stats (running
   `days-live`, `net-pip`, `worst-drawdown-pips`, `win-rate-pct`),
   (c) a per-pair breakdown table (EURUSD, GBPUSD, USDCAD as
   rows; trades, wins, net pips, avg pips per trade, best trade,
   worst trade as columns).
3. At 375 px viewport (F004 coordination) the same content is
   accessible; equity curve reflows to full-width, KPI tiles
   stack single-column, per-pair table becomes swipeable /
   scrollable horizontally.
4. Loading state (F005 coordination) shows skeleton placeholders
   for the equity curve, the 4 KPIs, and the per-pair table.
5. Error state (F005 coordination): if the backend endpoint
   `/api/performance` returns non-200 or empty, the page shows a
   friendly message ("No shadow-paper data yet — the squad is
   still warming up") with a retry button that re-fetches.
6. `Sharpe` renders **only if computable** (≥ 30 daily returns
   available). Below 30, the tile shows `Sharpe: n/a (need N more days)`.
7. The page includes a visible disclaimer footer authored by
   Legal: past-performance boilerplate + explicit "demo /
   shadow-paper account, no real money" clause.
8. Backend endpoint `GET /api/performance` returns a JSON payload
   with keys `{days_live, net_pips, worst_dd_pips, win_rate_pct,
   sharpe_or_null, equity_curve: [{ts, cum_pips}],
   per_pair: [{symbol, trades, wins, net_pips, avg_pips,
   best_pips, worst_pips}], generated_at, source_hint}`.
9. `source_hint` explicitly states whether the numbers are (a)
   the v1 live-demo agent's `state.json` PnL history or (b) the
   v2 shadow-paper `squad_live/events.jsonl` synthetic fills, or
   (c) both blended (in which case the split is visible on the
   page).
10. A test file `tests/platform/test_performance_page.py` and
    `tests/platform/test_performance_api.py` land with the
    feature; total test count is > 686 + baseline.

## Non-goals

- **No** interactive chart (zoom, pan). Static SVG, click-to-tooltip
  is fine but no D3 / chart.js.
- **No** benchmarking against S&P 500 / EURUSD passive buy-and-hold.
  That's a Sprint 3+ Marketing conversation.
- **No** downloadable CSV / PDF. Sprint 3 has "full P&L reporting"
  which subsumes this.
- **No** user-selectable date range. Ships as "all time"; date-range
  picker is a Sprint 3 concern.
- **No** per-agent (striker) equity attribution on this page. F002
  already handles per-character stats; keep concerns separated.
- **No** claim of any kind that isn't a raw number ("+120 pips this
  month" is fine; "we outperform the market" is not).

## Dependencies

- **Data source (v1):** `agent/live/state_store.py` writes
  `state.json` sidecars under `~/Documents/TradingAgentLogs/<PAIR>/`.
  Trade history is embedded in the daily log lines (`[TRADE CLOSED]`
  events) — Backend Engineer needs to parse these into a canonical
  trades stream.
- **Data source (v2):** `squad_live/events.jsonl` — the paper-loop
  fills, already parsed by `agent/platform/squad_events.py`.
- **Backend module:** a new `agent/platform/performance.py`
  (Backend Engineer). Reads both sources, computes derived stats,
  returns the payload above. Read-only.
- **Frontend page:** a new `PERFORMANCE_PAGE` constant in
  `agent/platform/pages.py`. Route in `scripts/serve_platform.py`.
- **UI Designer** produces mocks for desktop + mobile + skeleton +
  error state.
- **Brand Designer** produces the source-hint copy variants
  ("live demo agent", "shadow-paper squad", "combined view").
- **Legal** authors the disclaimer footer text — mandatory.

## Review checklist

Each reviewer verifies:

| Reviewer | Check |
|---|---|
| UX Researcher | Research memo cites ≥ 3 signals; jobs-to-be-done table present; accessibility brief covers colour-blind palette + screen-reader labels for KPI tiles. |
| UI Designer | Mocks include desktop + 375 px + skeleton + error state; colours from `_BASE_CSS` tokens only; component inventory names the KPI tile, equity chart, per-pair table for reuse. |
| Brand Designer | Zero uses of "ensemble" or "aggregator" in user-visible copy; source-hint copy is stranger-friendly; disclaimer copy reads warmly, not lawyer-ily. |
| CTO | Architecture review green; modules touched ≤ 4; test-delta ≥ 2; `security_relevant: false`; `legal_relevant: true`. |
| Frontend Engineer | Test file present; 375 px check green; skeleton + error state wired; no npm / CDN added. |
| Backend Engineer | JSON schema test present; blank-500 impossibility test present; read-only invariant preserved (no writes to `state.json` or `squad_live/`). |
| QA Engineer | Automated tests pass; manual desktop check green; manual mobile check green; empty-state and error-state tested by unplugging the data source. |
| Legal | Disclaimer footer present and matches `company/legal/disclaimers.md` `performance` entry; claim register updated. |
| CEO | Signs off in `decisions_log.md` after friend-test dogfood (share URL to one non-technical friend, watch them for 2 minutes). |

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Backend can't reliably parse `[TRADE CLOSED]` lines from daily logs (schema drift). | Backend Engineer writes a robust parser with a fallback; QA seeds test fixtures for known drift patterns. Escalate to CTO if parser complexity exceeds one module. |
| Equity curve rendering on 375 px is unreadable. | UI Designer mocks the 375 px variant FIRST; Frontend implements mobile-first. |
| Sharpe computation is misleading with < 30 data points. | Explicit "n/a (need N more days)" display — never a false number. |
| Legal disclaimer takes > 2 days to finalise. | Brand + Legal draft in parallel with build; boilerplate v1 already exists in disclaimer library by day 3. |

## Definition of shipped

`decisions_log.md` has a `[FEATURE]` entry from CEO signing off F001;
`../../handoffs/F001-devops-ship.json` exists with `verdict: shipped`;
`/performance` route responds 200 on the platform server; the friend-
test has been performed and passed.
