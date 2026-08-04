---
id: I024
source: post-mortem
submitter: "user (weekly v2 squad review, 2026-08-04)"
submitted_at: 2026-08-04T03:00:00Z
classification: BUG
priority: P0
status: shipped
route: bug
linked_features: []
linked_decisions: [D135]
linked_experiments: []
contact: null
resolved_at: 2026-08-04T04:30:00Z
history:
  - stage: filed
    at: 2026-08-04T03:00:00Z
    by: user_advocate
    note: "User: no players took trades all week; the confidence bar went back to 0 the day after launch and stayed there."
  - stage: shipped
    at: 2026-08-04T04:30:00Z
    by: engineering
    note: "Roster re-prepare on newly-extending live bars; regression tests fail on the old code."
---

# I024 — squad agents frozen at startup prepare(): every post-launch bar abstains `timestamp_miss`

## What happened

The Jul 28 - Aug 3 live week produced **0 proposals, 0 trades** — but
not because the market was quiet. The weekly zip's tape shows real
analysis on the first two bars after launch (Jul 28 11:00/12:00 UTC,
Bachira 0.75-conv EURUSD fade), then from the 16:00 bar — the first
bar to close AFTER startup — every bar-based agent (Isagi, Bachira,
Rin, Chigiri, Barou) abstained with `timestamp_miss` at confidence
0.00, on every symbol, every bar, for the rest of the week: 160 such
abstains in 69 of 74 tick summaries.

Root cause: agents build a frozen `_PreparedSeries` (zones, swings,
`index_by_ts`) exactly once, in `SquadEngine.prepare()` at startup.
`on_bar` extends the ENGINE's history but never re-prepares the
roster, so every post-startup bar misses the agents' timestamp index.
A sim-to-live port artifact: the research replay prepares on the FULL
series (including every "future" bar) up front, so batch/parity runs
can never hit it.

A brutal compounding irony: the 2-bar live burn-in consumed exactly
the two catch-up bars that WERE in the prepared index, so `intend()`
never ran once with valid data all week.

## Why it matters

The v2 shadow-paper clock ran a full week and measured nothing. The
/v2 dashboard's "evaluating quietly — no fresh setups" banner was
honest reporting of dishonest inputs, which cost days of debugging
trust. Same class as I019 (feed frozen at boot) — the second
"silently blind live runtime" incident in two weeks.

## Closure notes

- **Outcome:** `SquadEngine._maybe_reprepare_roster` re-prepares the
  roster per symbol whenever a bar extends history past the prepared
  horizon (`_roster_prepared_through`). No-op on batch/replay/parity
  paths (they prepare on the full series up front), so parity stays
  byte-identical. Keeps zone context fresh too, not just the
  timestamp index.
- **Measurement:** `tests/squad/test_live_reprepare.py` (5 tests) +
  `tests/test_squad_live_mt5_loop.py` (end-to-end through the real
  `run_loop`/`Mt5Feed`, asserts `timestamp_miss` never lands on the
  tape). Both fail against the pre-fix code.
- **User notified:** yes · 2026-08-04
- **Related decisions:** D135
