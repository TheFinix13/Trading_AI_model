---
id: I017
source: post-mortem
submitter: "self-observation"
submitted_at: 2026-07-28T15:20:00Z
classification: FEATURE-REQUEST
priority: P1
status: shipped
route: feature
linked_features: [F017]
linked_decisions: [D127, D133]
linked_experiments: []
contact: null
resolved_at: 2026-07-28T19:20:00Z
history:
  - stage: filed
    at: 2026-07-28T15:20:00Z
    by: user_advocate
    note: "Filed from the 2026-07-15..28 weekly v2 review."
  - stage: routed
    at: 2026-07-28T15:30:00Z
    by: engineering
    note: "Routed to F017 registry extension; check implemented same
      day (D127). Closure waits on VM wiring + first ok reading."
  - stage: shipped
    at: 2026-07-28T19:20:00Z
    by: engineering
    note: "VM wired per runbook 7b.9 (SquadLiveRuntime + OpsWatchdog
      + PlatformServer tasks); first live ok reading landed same
      evening ('newest bars 7.4h old (worst: EURUSD)', overall ok)
      after the D133 threshold recalibration."
---

# I017 — Squad tape freshness is not monitored (8 silent weekdays went unflagged)

## What happened

The first weekly v2 report bundle (2026-07-15 to 2026-07-28, D126
tool) showed the squad runtime ingested **6 symbol-bars out of ~180
expected** — no tape at all on 8 of 10 weekdays — and nothing flagged
it while it was happening. The F017 `runtime_heartbeat` check watches
artefact mtimes, so it catches a dead process, but (a) the watchdog
loop itself was never wired into Task Scheduler, and (b) even a live,
heartbeat-fresh process can be starved of bars: the Jul 28 boot had a
fresh `poll_heartbeat.txt` while `last_bar_times` in `state.json` sat
at Jul 24 07:00 UTC — four days stale.

## Why it matters

The shadow clock (D095 step 2) is the evidence pipeline for every v2
verdict; weeks without tape are weeks of no evidence. Worse, silence
is indistinguishable from "quiet market" until someone reads a weekly
report — this window's entire finding was operational, and it cost
two weeks. A single stalled symbol also silently blinds that
specialist (Rin/Barou) while everything else looks green.

## Proposed resolution

A `squad_tape_freshness` check in the F017 registry: age of the
OLDEST `last_bar_times` symbol in `state.json`, measured in market
seconds (Sat/Sun excluded so weekends never false-alarm); warn > 5 h
(one missed H4 close + slack), alarm > 9 h (two missed closes);
corrupt state alarms; never-ran is `na`. Plus the runbook 7b.9 Task
Scheduler wiring (SquadLiveRuntime restart-loop task +
OpsWatchdog `--loop 300` task) so both the runtime and the watcher
survive reboots.

## Triage decision (filled by CPO, Mondays)

- **Classification:** FEATURE-REQUEST
- **Priority:** P1
- **Route:** feature
- **Reasoning:** Same class as I011 (watchdog gap found by a real
  incident). The weekly review quantified the cost: 2 weeks of
  missing evidence. Registry extension is small, observe-only, and
  pinned by the F017 legal constraints (detail strings carry ages,
  counts, symbol names only).
- **Owner from here:** engineering
- **Linked feature spec (if any):** F017 (registry extension, D127)

## Amendment (2026-07-28, D133)

The proposed 5 h/9 h thresholds were miscalibrated: `last_bar_times`
stores bar OPEN labels, so a healthy tape's newest label ages 4–8 h
between closes, and 5 h sits inside that band — the very first live
pass warned at 7.1 h on a tape ingested an hour earlier, and steady
state would have warned ~3 of every 4 hours (transition-alert spam).
Recalibrated to warn > 9 h (one missed close) / alarm > 13 h (two),
measured against the open labels.

## Closure notes

Shipped 2026-07-28 evening. The VM completed runbook 7b.9 (three
scheduled tasks: SquadLiveRuntime restart-loop, OpsWatchdog
`--loop 300`, PlatformServer), the squad runtime reconnected to live
MT5 (I019 fix) and ingested the 12:00 UTC bar, and the first live
watchdog pass after the D133 threshold recalibration read
`[ok] squad_tape_freshness — newest bars 7.4h old (worst: EURUSD)`
with `overall: ok`. Note the check's first-ever live reading was a
false warn (7.1 h) that exposed the D133 calibration bug — see the
amendment above. Residual measurement: the next weekly bundle
(w/c 2026-08-04) should show 0 silent weekdays and ~90 bars.
