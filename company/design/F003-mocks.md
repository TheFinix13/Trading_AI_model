# F003 -- UI mocks: `/research`

- **Feature:** F003 -- Verdict timeline
- **Reviewer:** UI Designer
- **Related spec:** `../sprints/sprint-0-trust-foundation/F003-research-page.md`
- **Related research:** `../research/F003-user-journey.md`

## Desktop (1440 x 900)

```
+----------------------------------------------------------------+
| Hub | v1 | v2 | HQ | Perf. | Squad | [Research]                |
+----------------------------------------------------------------+
|                                                                |
| Research verdicts                                              |
| We publish the experiments that failed. This is the receipt    |
| trail for the ones that worked -- and the ones that didn't.    |
| Every verdict below is pre-registered; no cherry-picks.        |
| ▸ Approved for publication by cpo · 2026-07-21                 |
|                                                                |
| [SOURCE] 1 of 10 candidate reports published (6 approved).     |
|                                                                |
+----------------------------------------------------------------+
| July 2026                                                      |
+----------------------------------------------------------------+
| [FAIL] Phase AC -- pitch assignment                            |
| 2026-07-21 · phase_ac_pitch_assignment                         |
|                                                                |
| Phase AC asked whether widening one striker's tradeable pair   |
| set improved the whole squad's decision quality. The pre-      |
| registered criterion was a +0.02 lift in squad mean TQS; the   |
| observed effect was -0.006 with a 95% CI spanning zero...      |
|                                                                |
| HEADLINE: A2 - A1 = -0.006 TQS; 95% CI [-0.017, +0.005]        |
| [read full report ->]                                          |
+----------------------------------------------------------------+
| [DEAD] Structure-aware TP snap                                 |
| 2026-07-20 · E022_structure_aware_tp_snap                      |
|                                                                |
| Snap take-profit to nearby swing structure was tested as an    |
| exit improvement layer. It did not clear its promotion         |
| criterion. The proposal was rejected...                        |
|                                                                |
| HEADLINE: Did not clear the pre-registered promotion criterion.|
| [read full report ->]                                          |
+----------------------------------------------------------------+
| ... more cards ...                                             |
|                                                                |
+----------------------------------------------------------------+
| ▸ How pre-registration + BH-FDR works (click to expand)        |
+----------------------------------------------------------------+
|                                                                |
| Legal disclaimer footer                                        |
|                                                                |
+----------------------------------------------------------------+
```

## Mobile (375 x 667)

```
+-------------------------+
| Nav pills wrap          |
+-------------------------+
| Preamble reflows        |
| SOURCE hint stacks      |
+-------------------------+
| Date header sticky      |
| top:0 so scrolling      |
| through Aug -> Jul      |
| keeps context.          |
+-------------------------+
| Verdict card:           |
|                         |
| [FAIL] tag on its own   |
| Campaign name           |
| Date                    |
| ---                     |
| Summary paragraph       |
| reflows.                |
|                         |
| HEADLINE box: wraps.    |
| [read full report ->]   |
+-------------------------+
| ...                     |
+-------------------------+
| FDR-explainer <details> |
| still fits.             |
+-------------------------+
```

## Verdict-pill palette

Uses only `_BASE_CSS` tokens plus one alpha overlay per state:

- `alive_survivor` / `pass` / `pass_thin`: `--green` border,
  `--green` text at 70 %.
- `complete` / `stage_1_complete`: `--accent` border,
  `--accent` text at 70 %.
- `dead` / `fail`: `--red` border, `--red` text at 70 %.
- `stopped_at_stage_1` / `stopped` / `parked` / `parked_low_yield`:
  `--dim` border, `--dim` text.
- `unknown`: `--dim`, italic.

Every pill carries text label; the state colour is a bonus, not
the sole signal.

## New primitives (F003-owned)

- `.verdict-card` -- one card per entry with a top row (pill +
  title + date) and a body (summary + headline + link).
- `.date-header` -- sticky month heading (`position: sticky;
  top: 0`).
- `.fdr-explainer` -- `<details>` block reusing the existing
  hub-glossary detail pattern.
- `.source-hint` -- reused from F001.
- `.disclaimer` -- reused from F001; carries the research-verdict
  clause.

## Reused primitives

- `.kpi-tile` -- for the headline-stat box inside the card.
- Nav pills from `_NAV`.
- F005 helper for skeleton / error / empty states.

## Empty / unconfigured states

- **Research repo not on the machine:** `source_exists=False`
  fires the empty state. Copy: "Research repo not configured on
  this machine -- see docs/RUNBOOK_demo_launch.md §7b for setup."
- **Manifest missing / malformed:** `unconfigured=True` fires the
  empty state with a slightly different copy: "The publication
  manifest is not on tape yet. CPO signoff pending."

## What we deliberately did NOT ship

- Live-progress bars for in-flight campaigns.
- Search / filter.
- Subscribe / RSS.
- Comments.
- Any way to run experiments from this page.
- Any per-experiment metric plot (mocks describe headline-stat
  text only; charting is Sprint 3+).

## Sign-off

Mocks approved. Ready to hand to Frontend (module count stays at 3
this feature: `research.py` + `pages.py` + `serve_platform.py`).
