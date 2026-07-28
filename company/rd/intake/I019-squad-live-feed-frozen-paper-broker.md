---
id: I019
source: post-mortem
submitter: "self-observation"
submitted_at: 2026-07-28T16:55:00Z
classification: BUG
priority: P0
status: shipped
route: bug
linked_features: []
linked_decisions: [D129]
linked_experiments: []
contact: null
resolved_at: 2026-07-28T17:10:00Z
history:
  - stage: filed
    at: 2026-07-28T16:55:00Z
    by: user_advocate
    note: "Root-caused while investigating the 8 silent weekdays in the
      2026-07-15..28 weekly v2 bundle: state.json pinned at Jul 24
      07:00 even across manual restarts."
  - stage: shipped
    at: 2026-07-28T17:10:00Z
    by: engineering
    note: "CEO gave explicit go-ahead to patch the off-limits
      scripts/run_squad_live.py same day (D129). Feed now attaches a
      real MT5 broker or fails loudly; 4 regression tests pin it."
---

# I019 — `--feed mt5` silently ran on a frozen PaperBroker snapshot (P0)

## What happened

`run_squad_live._connect_mt5()` built a bare `LiveConfig()`, whose
`broker_type` defaults to `"paper"`. `PaperBroker._load_data`
memoizes the parquet cache **once at boot** and serves every
subsequent `get_bars` call from that in-memory snapshot. Net effect:
a runtime launched with `--feed mt5` connected, seeded warm-up from
the cache, evaluated the newest cached bar(s)... and then starved —
no new bar ever arrived, because the "live" feed was a frozen file.

This is the true root cause of the 8 silent weekdays in the
2026-07-15..28 weekly bundle (the review's section 2 blamed process
downtime; downtime was real but secondary — even a 24/5 scheduled
task would have starved the same way). It also explains why the
Jul 28 manual restart produced exactly one burst of thoughts
(Bachira's 0.75-conviction EURUSD fade on the newest cached bar) and
then went quiet with `last_bar_times` pinned at Jul 24 07:00.

## Why it matters (P0)

The shadow-evidence clock cannot start until the squad sees a moving
tape. Every silent day pushes back the earliest possible
squad-vs-baseline verdict. Worse, the failure mode was **silent**:
heartbeat kept ticking, the process looked healthy, and only the
weekly bundle (or the new `squad_tape_freshness` watchdog check,
I017) would surface it.

## Fix (shipped, D129)

`_connect_mt5` now builds `LiveConfig(broker_type="mt5", ...)` with
credentials from the agent's `.env` (same wiring as v1's
`run_live.py`), and raises `RuntimeError` instead of degrading if:
credentials are missing, an explicit paper config is passed, or the
broker connect fails. Regression tests:
`tests/test_squad_live_feed_broker.py` (4 tests).

VM follow-up: `git pull`, restart the runtime (or register the 7b.9
scheduled tasks), then confirm the boot log line
`squad feed broker: mt5 login=... (read-only)` and watch
`last_bar_times` advance at the next H4 close.

## Notes for triage

`scripts/run_squad_live.py` is on the off-limits list (sealed parity
port); the CEO explicitly approved this touch. The fix deliberately
changes only the broker construction path, not engine/roster logic,
to preserve sim parity.
