---
id: I018
source: post-mortem
submitter: "self-observation"
submitted_at: 2026-07-28T15:25:00Z
classification: BUG
priority: P2
status: shipped
route: bug
linked_features: []
linked_decisions: [D128]
linked_experiments: []
contact: null
resolved_at: 2026-07-28T16:40:00Z
history:
  - stage: filed
    at: 2026-07-28T15:25:00Z
    by: user_advocate
    note: "Found while analyzing the 2026-07-15..28 weekly v2 bundle
      against a live /v2 screenshot."
  - stage: shipped
    at: 2026-07-28T16:40:00Z
    by: engineering
    note: "CEO asked to proceed same day; countdown now anchors to
      the tape's tick_summary timestamps (D128)."
---

# I018 — /v2 "Next bar close" countdown assumes the wrong H4 grid (1 h off)

## What happened

The /v2 waiting panel's `nextH4CloseMs()` (client JS in
`agent/platform/pages.py`) computes the next H4 close on the
**00/04/08/12/16/20 UTC** grid (as does `next_h4_close_utc` in
`agent/live/signal_loop.py`). The actual tape closes on the
**03/07/11/15/19/23 UTC** grid: the weekly bundle's evaluated bars
are stamped 19:00 and 07:00 UTC, and Karasu's Jul 24 advisory
("French Flash Manufacturing PMI in +15 min" — a 07:15 UTC release)
pins 07:00 as a true wall-clock evaluation moment. A live screenshot
on 2026-07-28 at 14:59 UTC showed "Next bar close 16:00 UTC · in
1 h 0 m 25 s" while the real next close was 15:00 UTC — about 35
seconds away.

## Why it matters

Display-only, but it misleads exactly the person the "Waiting on the
market" panel exists for: the operator watching for the first
thoughts after a restart sees a countdown pointing an hour late, and
"wait for the next H4 close at HH:00" in the empty workspace panel
inherits the same error. Evaluation timing is NOT affected — the
runtime's idle sleep is capped at ≤ 60 s
(`run_squad_live.run_loop`), so bars are picked up within a minute of
the real close regardless.

## Proposed resolution (optional)

Platform-side fix: derive the grid from the tape instead of assuming
midnight anchoring — latest `tick_summary` timestamp (or
`last_bar_times`) plus the smallest multiple of 4 h that lands after
now. Falls back to the current midnight grid when no tape exists.
The `agent/live/signal_loop.py` twin is off-limits outside an
integration sprint and is functionally harmless there (same ≤ 60 s
poll cap for v1); note it in the fix but don't touch it.

## Notes for triage

Root cause of the offset (broker server clock vs UTC anchoring) is
worth one look during A004's FOMC live capture this week — if the
Exness H4 grid is genuinely +3 h from UTC midnight, the A004 note
"H4 closes on UTC grid" should be tightened to name the actual grid.
