# F001 — UX research memo: `/performance` user journey

- **Feature:** F001 — Public `/performance` route
- **Reviewer:** UX Researcher
- **Related spec:** `../sprints/sprint-0-trust-foundation/F001-performance-page.md`
- **Related handoff:** `../handoffs/F001-cpo-to-ux_researcher.json`

## Target segment

Primary: **retail forex trader evaluating an AI trading product**.
Reads Twitter, Discord, YouTube. Skeptical of "MyFxBook screenshots".
Assumes 95 % of posted "signals bots" are scams. Values raw numbers
over marketing copy.

Secondary: **journalist or independent researcher** who's landed on
the platform via search or a share. Doesn't know what MT5 is; needs
a plain-English summary within 30 seconds.

Tertiary (Sprint 1+): **existing user** who wants to confirm they're
seeing the same numbers a stranger sees (trust-symmetry).

## Jobs to be done

| Job (verb phrase) | Success criterion | Failure mode this feature prevents |
|---|---|---|
| Find out if this thing makes money on real markets. | Sees +/- pip aggregate, days live, drawdown all within 10 seconds. | Bounces because there's no proof of numbers. |
| Judge whether the numbers are cherry-picked. | Sees the raw data source named (v1 live / v2 shadow / combined), reads the disclaimer. | Assumes cherry-pick because the framing hides the source. |
| Understand the risk story before the return story. | Worst-drawdown tile is visible above the fold, same size as the net-pips tile. | Users only see the return number and buy on FOMO. |
| Compare pair-level performance. | Per-pair breakdown table (EURUSD / GBPUSD / USDCAD) visible below the KPIs. | Suspects one pair carries the whole result. |
| Skim on mobile between meetings. | Full page renders correctly at 375 px viewport; no horizontal scroll; tap targets ≥ 44 × 44 px. | Bounces because the equity curve overflows. |

## The "trust in 10 seconds" framing

The CPO's opening framing survives contact with the (CEO-as-proxy)
walkthrough. Concretely: within 10 seconds the user must be able to
answer three questions from what's above the fold:

1. **How long has this been running?** — the "Days live" KPI.
2. **Is it up or down?** — the net-pips KPI's colour and sign.
3. **How much did it lose at the worst point?** — the worst-drawdown
   KPI (always shown as a negative pip number for visual honesty).

Sharpe is deferred below the 30-day floor; win rate is complementary,
not primary (charts frequently show 30 % win-rate systems that make
money — placing it above the pip aggregate misleads).

## Accessibility brief

- **Colour-blind palette.** Equity curve uses `--green` / `--red` for
  above/below zero. Red-green colour-blindness is common; the curve
  is monotone in position (up = good) so a viewer with achromatopsia
  can still read direction from the axis alone. Zero-line is drawn
  as a dashed grey — never depended on for red/green distinction.
- **Screen-reader labels.** Every KPI tile has an explicit label
  (`<div class="k">Net pips</div>`) that reads cleanly. The SVG has
  `aria-label="Equity curve"`; the skeleton has
  `role="progressbar" aria-label="Loading equity curve"`.
- **Font size.** No text below 12 px effective. Skeleton lines are
  presentational (`aria-hidden="true"`) so a screen reader jumps
  straight to the copy that matters.
- **Keyboard.** Retry buttons are native `<button>` elements — full
  keyboard support with zero extra JS. No custom interactive
  widgets on this page.

## One adjacent user need this feature does NOT try to solve

**Attributing return to individual strikers.** The prospect will
ask "was it Isagi or Bachira that made the money?" — that's F002's
job. F001 answers "is the platform making money" without splitting
per character. Keeping the concerns separate prevents F001 from
turning into a per-character equity dashboard (Sprint 3+ concern).

## Risks the researcher wants downstream stages to watch for

1. **Equity curve on cold start looks flat / broken.** Empty-state
   copy must be warm, not scary ("No shadow-paper data yet — the
   squad is still warming up"). F005 empty-state affordance covers
   this if wired correctly.
2. **Sharpe number appears too early.** If the module ever shows a
   Sharpe below the 30-day floor, it will be misinterpreted as a
   real result. The "n/a — need N more days" affordance is
   mandatory, not optional.
3. **Drawdown feels absent.** If the equity curve is monotone-up in
   its first few days (small n), the worst-drawdown tile shows 0.
   That's honest but reads as "no risk shown" — the KPI still helps
   because it's paired with days_live: a viewer sees "3 days live,
   -0 pips drawdown" and correctly reads it as "no history yet".

## Sign-off

Segment, journey, and accessibility brief acceptable to feed into UI
Design.
