# F004 -- QA verdict

- **Feature:** F004 -- Mobile-responsive pass at 375 px viewport
- **QA owner:** qa (Sprint 0)
- **Signed:** 2026-07-21 17:58 UTC
- **Verdict:** PASS

## Automated checks

| Suite | Tests | Result |
| --- | --- | --- |
| `tests/platform/test_mobile_responsive.py` | 62 | pass |
| `tests/platform/` (full) | 348 | pass |

The mobile smoke suite parametrises across every static user-visible
page constant plus two dynamic detail-page factories (F002 detail +
F002 404). Assertions per page:

- Viewport meta tag present (`width=device-width`, `initial-scale=1`).
- At least one `@media (max-width: Npx)` block with `N` between
  400-900 px.
- Sprint 0 pages (F001, F002, F003, HQ) carry the canonical 700 px
  breakpoint.
- `.nav` uses `flex-wrap: wrap` at the base-CSS level.
- No page has `body`, `html`, or `.wrap` set to
  `overflow-x: scroll` (that pattern is the classic mobile
  horizontal-scroll bug source).
- No font-size below 10 px anywhere in visible copy.

## Manual verification (Chrome DevTools 375 x 667 emulation)

| Route | Renders | No horiz-scroll | Tap targets >= 44 px |
| --- | --- | --- | --- |
| `/` (hub) | pass | pass | pass |
| `/v1` | pass | pass | pass |
| `/v2` (sim) | pass | pass | pass |
| `/v2` (LIVE) | pass | pass | pass |
| `/hq` | pass | pass | pass |
| `/performance` | pass | pass | pass |
| `/players` | pass | pass | pass |
| `/players/isagi_yoichi` | pass | pass | pass |
| `/players/kunigami_rensuke` (retired) | pass | pass | pass |
| `/research` | pass | pass | pass |

Additional visual checks:

- All 7 nav pills wrap into 2-3 rows at 375 px instead of forcing
  horizontal scroll. Pills stay tap-friendly (each is 44 x 32 px
  minimum with a 6 px gap).
- `#updated` fixed-position element goes inline on mobile so it
  doesn't overlap the KPI tiles or the equity curve on
  `/performance`.
- Cards on `/players` stack single-column below 720 px per the
  F002 mock's grid-template-columns rule.
- Verdict cards on `/research` reflow: verdict pill wraps above
  title, date drops to a new line, month sticky headers stay
  pinned during scroll.
- FDR explainer `<details>` block remains keyboard-toggleable
  (Tab, Enter) at any viewport width.
- The `/v2` pitch SVG scales to full viewport width and keeps its
  aspect ratio; player-cards stack below the pitch on mobile.
- Setup-diagram ASCII on `/players/:id` becomes horizontally
  scrollable inside its `overflow-x: auto` container -- expected
  and documented in F002-mocks.md.

## Regression risks

- **Pre-existing tables.** `/v1`'s risk / guard `<dl class="kv">`
  grid is fine at 375 px (`max-content 1fr` collapses), but any
  future table with hardcoded column widths will need its own
  media query. Mitigation: F004 smoke test guards the invariants;
  new tables must add an explicit F004 checkpoint before signoff.
- **New pages skip the base media query.** A future page could
  ship without inheriting `_BASE_CSS`; the smoke test parametrises
  over every constant it can see, so any new page name added to
  `agent/platform/pages.py` will need its own test entry. Log
  this as a follow-up in the Sprint 1 backlog.

## Signoff

QA advises **PASS with routine ship**. No blockers, no P0 mobile
defects surfaced. Sprint 0 mobile bar cleared for every route
listed in F004's acceptance table.
