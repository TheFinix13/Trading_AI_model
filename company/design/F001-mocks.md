# F001 — UI mocks: `/performance`

- **Feature:** F001 — Public `/performance` route
- **Reviewer:** UI Designer
- **Related spec:** `../sprints/sprint-0-trust-foundation/F001-performance-page.md`
- **Related research:** `../research/F001-user-journey.md`

## Layout (desktop, 1440 × 900)

```
+----------------------------------------------------------------+
|  Hub  |  v1  |  v2  |  HQ  |  [Performance]  |  Squad  |  Res.  |
+----------------------------------------------------------------+
|                                                                |
| How we're doing                                                |
| This is the demo-account P&L for our live zones agent and the  |
| paper equity curve for the striker squad, updated bar-by-bar.  |
| Every number here is a real number the platform wrote to disk  |
| -- no back-tests, no cherry-picks.                             |
|                                                                |
| [SOURCE] combined view: 42 closed trades from the v1 live-demo |
|          agent + 8 shadow-paper fills from the v2 squad        |
|                                                                |
+----------------------------------------------------------------+
|                                                                |
|  +---------+ +---------+ +---------+ +---------+ +---------+   |
|  | Days    | | Net     | | Worst   | | Win     | | Sharpe  |   |
|  | live    | | pips    | | drawdown| | rate    | |         |   |
|  |   42    | |  +512.4 | |  -84.2  | |  58.3%  | |   1.24  |   |
|  |  ...    | |  ...    | |  ...    | |  ...    | |  ...    |   |
|  +---------+ +---------+ +---------+ +---------+ +---------+   |
|                                                                |
+----------------------------------------------------------------+
|  Equity curve  cumulative pips across every closed trade       |
|  +-------------------------------------------------+           |
|  |                                        /\       |           |
|  |                                       /  \      |           |
|  |                                  /\  /    \___/ |           |
|  |             / \                /  \/            |           |
|  | ___________/   \___/\    /\  _/                 |           |
|  | 0                    \  /  \/                   |           |
|  |                       \/                        |           |
|  +-------------------------------------------------+           |
|  2026-06-24                                    2026-07-21      |
+----------------------------------------------------------------+
|  By pair                                                       |
|  Pair    Trades  Wins  Net pips  Avg pips  Best   Worst        |
|  EURUSD  18      12    +234.5    +13.03    +48.2  -22.1        |
|  GBPUSD  15      8     +142.9    +9.53     +64.0  -31.4        |
|  USDCAD  9       4     +12.0     +1.33     +22.5  -18.6        |
+----------------------------------------------------------------+
|                                                                |
|  Past performance is not indicative of future results. These   |
|  numbers are from a demo (paper-money) MetaTrader 5 account.   |
|  ...                                                           |
|                                                                |
+----------------------------------------------------------------+
```

## Layout (mobile, 375 × 667 — F004 baseline)

```
+-------------------------+
| Nav pills wrap onto     |
| 2 rows                  |
+-------------------------+
|                         |
| How we're doing         |
| Preamble reflows...     |
|                         |
| [SOURCE] combined...    |
+-------------------------+
| +---------------------+ |  <- KPI grid collapses to
| |   Days live         | |     single column at 700 px
| |   42                | |
| +---------------------+ |
| +---------------------+ |
| |   Net pips          | |
| |   +512.4            | |
| +---------------------+ |
| +---------------------+ |
| |   Worst drawdown    | |
| |   -84.2             | |
| +---------------------+ |
| +---------------------+ |
| |   Win rate          | |
| |   58.3 %            | |
| +---------------------+ |
| +---------------------+ |
| |   Sharpe            | |
| |   1.24              | |
| +---------------------+ |
+-------------------------+
| Equity curve            |
| +---------------------+ |  <- SVG reflows to 100% width,
| |                     | |     height stays at 220 px
| |                     | |
| +---------------------+ |
+-------------------------+
| By pair                 |
| +---------------------+ |  <- Table wraps in overflow-x
| | Pair | ... | Worst  | |     scroll container so tall
| |      |     |        | |     content stays legible
| +---------------------+ |
+-------------------------+
| Disclaimer text stacks  |
+-------------------------+
```

## Skeleton (loading state)

Uses F005's shared `withStates()` helper via a per-page
`performanceSkeleton()` factory:

- Header line (short) — 40 % width, 12 px tall.
- KPI grid — 5 `.sk-tile` placeholders, each 88 px min-height with
  two `.sk-line` inside so the "label + value + foot" layout
  matches the final content.
- Equity chart — one `.sk-chart` (220 px tall on mobile, 260 px on
  desktop), shimmer sweep in `--accent` at 6 % opacity so it reads
  as "loading a chart", not "empty box".
- Per-pair table — 3 `.sk-row` placeholders, matching the 3-4
  rows the final table shows.

No layout shift when data lands: each skeleton element has the same
container dimensions as its final content.

## Error state

`sk-error` variant of the shared helper, using the
`server_restarting` / `temporary_glitch` copy keys depending on the
fetch outcome. Retry button labelled "Try again" per Brand.

## Empty state

Distinct from error (grey left-border vs amber). Copy: "No
shadow-paper data yet — the squad is still warming up. Come back
after the next H4 bar close." Retry button optional; F001 wires it
in so a user who reloads two seconds later gets the new data.

## Component inventory

Reusable across F002 / F003 where they need the same primitives:

- `.kpi-tile` — background, border, padding, label + value + foot
  three-liner. Value has `ok` / `bad` colour classes for +/- pip
  sums.
- `.per-pair-table` — full-width table with a `min-width: 520px`
  and `overflow-x: auto` container so mobile users get horizontal
  scroll instead of squashed columns.
- `.disclaimer` — Legal-authored footer, dim colour, subtle border,
  first line ("lead") in `--fg`.
- `.source-hint` — inline info bar with a subtle blue tint so it's
  distinct from an error or empty state.
- `#equity-svg` — inline SVG polyline; the JS `renderEquityCurve`
  function is reusable in principle but currently pinned to F001.

## Palette usage

Only tokens from `_BASE_CSS` — no new colours:

- `--panel`, `--border`, `--bg` for surfaces.
- `--fg`, `--dim` for text.
- `--accent` (blue) for the source-hint tint.
- `--green` / `--red` for the equity polyline stroke (`--green` on
  net-positive equity, `--red` on net-negative). Zero-line is
  dashed `--border` grey.

## What we deliberately did NOT ship

- No interactive tooltip on the equity curve (Sprint 3+ polish).
- No date-range picker (Sprint 3+ concern).
- No S&P benchmark overlay (Sprint 3+ Marketing concern).
- No per-agent (striker) equity attribution — F002 owns that.
- No CSV / PDF download — Sprint 3 "full P&L reporting" subsumes.

## Sign-off

Mocks approved. Ready to hand to CTO for architecture review.
