# F012 — Design mocks: `/risk`

## Layout

Three vertical panels on desktop (`grid-template-columns: 1fr 1fr 1fr`)
collapsing to a single column at `max-width: 700px`. Panels reuse the
`.panel` shell (dark surface + accent border) from `_BASE_CSS`.

```
+-----------+  +------------+  +---------------------+
| Live      |  | Budget     |  | Broker connections  |
| exposure  |  | headroom   |  |                     |
|           |  |            |  | main-broker · demo  |
| 0 open    |  | per-day    |  |   OK (12 s ago)     |
| positions |  |   $0/$100  |  |                     |
|           |  |            |  | secondary · demo    |
|           |  | per-symbol |  |   ERR conn refused  |
|           |  |   $0/$50   |  |                     |
|           |  |            |  |                     |
|           |  | per-strat  |  |                     |
|           |  |   $0/$50   |  |                     |
+-----------+  +------------+  +---------------------+
```

## Trust receipts (top-of-page pinned banner)

- "Live-mode is **OFF**. Nothing is placing orders."
- "Budgets refresh every 30 s. `cached=true` = last probe within 30 s."

## Colour semantics

- Green `--accent`: `alive=true`, headroom >= 50%.
- Amber (deferred to F013 palette bump): headroom 25-50%.
- Red `--danger`: headroom <= 25% or `alive=false`.

## Interaction

- No inline edit in Sprint 2 -- the "Edit budgets" button is stubbed and
  links to `POST /api/risk/budgets` documentation.
- Auto-refresh every 30 s via `setInterval(refresh, 30_000)`.
- Manual "Refresh now" button next to the timestamp.

## Copy strings (for `company/brand/copy.md`)

- **Live-mode banner:** "Live-mode is OFF — the platform is in read-only
  mode. Toggle it on at `/settings/live-mode` (Sprint 2, F013)."
- **Sprint 2 caveat:** "Budgets are enforced **before** any order sends.
  Wins do NOT restore headroom. The cap resets at 00:00 UTC."
- **Probe cache:** "Broker connectivity is checked at most once per 30
  seconds to stay under MT5's rate limit."
