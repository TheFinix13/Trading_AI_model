# F002 -- UI mocks: `/players` + `/players/:id`

- **Feature:** F002 -- Character bio index and detail
- **Reviewer:** UI Designer
- **Related spec:** `../sprints/sprint-0-trust-foundation/F002-player-bios.md`
- **Related research:** `../research/F002-user-journey.md`

## `/players` index (desktop, 1440 x 900)

```
+----------------------------------------------------------------+
|  Hub  |  v1  |  v2  |  HQ  |  Perf.  |  [Squad]  |  Research   |
+----------------------------------------------------------------+
|                                                                |
| The squad                                                      |
| Ten specialists, one pitch. Each striker owns a specific       |
| trading playstyle. Click any card to read their bio and see    |
| what they've done recently.                                    |
|                                                                |
+----------------------------------------------------------------+
|                                                                |
| +---------------+ +---------------+ +---------------+           |
| | Isagi     #11 | | Bachira    #8 | | Rin       #10 |           |
| | active        | | active        | | active        |           |
| | Metavision    | | Rebel dribbler| | Cold          |           |
| | zone reader   | | (tight-stop   | | geometric     |           |
| |               | | specialist)   | | precision     |           |
| | 12 props · 8W | | 15 props · 6W | | 4 props · 3W  |           |
| | +42.5 pips    | | +18.2 pips    | | +22.0 pips    |           |
| +---------------+ +---------------+ +---------------+           |
| ... (7 more cards in same grid, retired dimmed) ...            |
|                                                                |
+----------------------------------------------------------------+
|                                                                |
| Blue Lock is a manga / anime by Yusuke Nomura and Muneyuki     |
| Kaneshiro, published by Kodansha. Characters here are named as |
| homage to describe our AI agents' trading playstyles; no       |
| affiliation, endorsement, or commercial arrangement is claimed.|
|                                                                |
+----------------------------------------------------------------+
```

## `/players/:id` bio detail (desktop, 1440 x 900)

```
+----------------------------------------------------------------+
|  [<- Back to squad]                                            |
|                                                                |
| Isagi                                                    #11   |
| Metavision zone reader                                         |
| [active] Tier 1 · EURUSD, GBPUSD, USDCAD                       |
|                                                                |
| Isagi is the striker who sees the whole field. He waits for    |
| price to touch a fresh supply / demand zone and only fires     |
| when the daily bias points the other way -- a counter-trend    |
| fade with a story.                                             |
|                                                                |
+----------------------------------------------------------------+
| Career stats                                                   |
|  +---------+ +---------+ +---------+ +---------+ +---------+   |
|  | Props.  | | Wins    | | Win %   | | Net pips| | Best pair|  |
|  |   14    | |    9    | |  64.3%  | | +52.5   | | EURUSD  |   |
|  +---------+ +---------+ +---------+ +---------+ +---------+   |
|  +---------+ +---------+ +---------+                           |
|  | Best    | | Worst   | | Days    |                           |
|  | +48.2   | | -22.1   | |   14    |                           |
|  +---------+ +---------+ +---------+                           |
+----------------------------------------------------------------+
| Playstyle                                                      |
|                                                                |
| Isagi is the anchor of the squad. His job is not to be the     |
| loudest gun; it is to see the pitch first...                   |
| (paragraphs continue)                                          |
+----------------------------------------------------------------+
| Signature setup                                                |
|   D1 uptrend                                                   |
|        \\                                                       |
|         \\                                                      |
|   ...........o    <-- price touches supply zone                |
|                     __                                         |
|                    /                                           |
|              ____/       <-- Isagi fades DOWN, target 1.5R     |
+----------------------------------------------------------------+
| Recent activity (last 5)                                       |
|  2026-07-21 17:00  close  EURUSD short  +12.5p                 |
|  2026-07-21 13:00  propose EURUSD short                        |
|  ...                                                           |
+----------------------------------------------------------------+
| Evolution history                                              |
|  - v1.0 landed 2026-06-24 -- E004 walk-forward gate cleared    |
|  - v1.1 (2026-07-14) -- F20 provenance stamping added          |
|  - v1.2 (2026-07-14) -- F19 metavision variance shipped        |
+----------------------------------------------------------------+
| IP disclaimer (verbatim from legal library)                    |
+----------------------------------------------------------------+
```

## Mobile (375 x 667)

```
+-------------------------+
| Nav wraps to 2 rows     |
+-------------------------+
| Header stacks:          |
|   Isagi                 |
|   Metavision zone reader|
|   [active]              |
|   #11 · Tier 1          |
|   EURUSD, GBPUSD, USDCAD|
|                         |
|   Signature blurb...    |
+-------------------------+
| Career stats: 8 tiles   |
| collapse to 2-col grid  |
| below 700 px, then 1-col|
| below 480 px.           |
+-------------------------+
| Playstyle prose reflows |
+-------------------------+
| Signature setup: pre    |
| tag with overflow-x:auto|
| so ASCII art scrolls    |
| horizontally instead of |
| wrapping.               |
+-------------------------+
| Recent activity: rows   |
| stack; timestamp above  |
| body on narrow view.    |
+-------------------------+
| Evolution list stacks   |
+-------------------------+
| Disclaimer              |
+-------------------------+
```

## Status pill styling

Three distinct visual states, all using existing palette tokens:

- **active** -- solid `--green` border, `--green` text at 70% opacity.
- **standby** -- solid `--accent` border, `--accent` text at 70% opacity.
- **retired** -- solid `--dim` border, `--dim` text; card itself
  renders at 65% opacity so the retired striker reads as historical
  without disappearing.

## Reused primitives

Copied verbatim from F001's mock library:

- `.kpi-tile` -- one tile per stat.
- `.disclaimer` -- IP footer.
- `.source-hint` -- data-freshness note.
- Palette tokens from `_BASE_CSS`; no new colours.

## New primitives (F002-owned)

- `.player-card` -- index-grid card; hover raises `border` to
  `--accent`. Retired variant: `.player-card.retired` at 65 %.
- `.player-header` -- detail-page header block with name, tag,
  status pill, symbols list.
- `.setup-diagram` -- `<pre>` wrapper with overflow-x for mobile.

## What we deliberately did NOT ship

- Inline character images (IP posture — see
  `company/legal/blue-lock-ip-notice.md`).
- Side-by-side comparison ("Isagi vs Bachira").
- User-editable notes.
- Search / filter.

## Sign-off

Mocks approved. Ready to hand to Frontend (no separate CTO handoff
needed — the module is fresh but tiny, and total files touched
stays under the 3-module threshold: `players.py` + `pages.py` +
`serve_platform.py`.)
