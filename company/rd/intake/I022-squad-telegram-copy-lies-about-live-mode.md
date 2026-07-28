---
id: I022
source: user-report
submitter: "CEO (Telegram screenshot, 2026-07-28 18:02)"
submitted_at: 2026-07-28T17:40:00Z
classification: BUG
priority: P2
status: new
route: bug
linked_features: []
linked_decisions: []
linked_experiments: []
contact: null
resolved_at: null
history:
  - stage: filed
    at: 2026-07-28T17:40:00Z
    by: user_advocate
    note: "CEO asked why stopping the v2 runtime pages 'step budget
      reached' and which other messages are inaccurate. Full audit of
      squad_notify.py + run_squad_live.py call sites below."
---

# I022 — Squad Telegram copy describes the live runtime in replay vocabulary (and mislabels stops)

## What happened

`agent/platform/squad_notify.py` was written for the file-replay
paper loop (`run_squad_paper.py`) and reused verbatim by the live
runtime (`run_squad_live.py`). Three defects, worst first:

1. **Crash reported as clean completion (silent-failure class).**
   `run_loop` initializes `outcome = "done"` before the loop; the
   `finally` block sends FULL TIME on any non-kill exit. An unhandled
   exception therefore pages "replay exhausted — every row emitted" —
   a crash masquerading as a happy ending. On the live feed there is
   no legitimate "done" exit at all.
2. **Ctrl+C pages "step budget reached".** `KeyboardInterrupt` sets
   `outcome = "interrupted"`, but `notify_stop(outcome if outcome !=
   "interrupted" else "max_steps")` deliberately funnels it into the
   max-steps phrase because `build_squad_full_time` only knows
   done/max_steps. (`--max-steps` is a test-harness tick cap the VM
   never sets.) The terminal log is accurate; only Telegram lies.
3. **KICKOFF replay vocabulary on a live boot.** "Paper loop started —
   replaying `live_market:mt5`", "0 rows queued" (hardcoded
   `n_rows=0`; the row queue only exists in file replay — at a healthy
   live boot it reads like 'no data loaded'), and "stream:" labelling
   the output DIRECTORY.

Accurate and untouched: MATCH HALTED (kill.txt), GOAL / Shot MISSED,
league table, SYSTEM news-cache warnings, and all terminal log lines.

## Why it matters

The Telegram bot is the CEO's primary at-a-glance ops channel. Copy
that misstates WHY the runtime stopped (or that a crash was a clean
finish) trains the operator to ignore the channel — the exact failure
mode the I017/I019 week showed is expensive.

## Proposed resolution

- `build_squad_kickoff`: live-mode wording ("Live shadow loop started
  — feed `mt5`"; drop rows-queued when n_rows is None; "out:" not
  "stream:").
- `build_squad_full_time`: add "interrupted" ("stopped from terminal —
  restart resumes from state.json") and "crashed" outcomes; stop
  mapping interrupted→max_steps at the call site.
- `run_loop`: initialize `outcome = "crashed"` (or wrap loop body) so
  an unhandled exception pages honestly; set "done" only where the
  cache feed genuinely exhausts.
- Pure-formatter tests in `tests/test_squad_notify.py` extended.

NOTE: the call-site half touches `scripts/run_squad_live.py`
(off-limits) — needs the same explicit CEO go-ahead as I019, or an
integration-sprint slot. The formatter half is ordinary platform code.
