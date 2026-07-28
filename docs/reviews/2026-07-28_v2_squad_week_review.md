# Week Review — v2 squad, 2026-07-15 → 2026-07-28 (shadow paper)

> PROVENANCE: shadow-paper activity from the v2 squad on a demo data
> feed — no orders sent to any broker, NOT investment performance.
> Source data: the D126 `weekly_squad_report.py` bundle generated on
> the VM 2026-07-28T14:34:28Z (`REPORT.md`, `events_window.jsonl`,
> `state.json`, `poll_heartbeat.txt`). The v2 counterpart of the v1
> weekly ritual; v1's own week is reviewed separately.

---

## Headline

| Metric | Value |
|--------|-------|
| Shots (proposals) | **0** |
| Sentinel tackles / opens / resolved trades | 0 / 0 / 0 |
| Net pips / net R / mean TQS | +0.0 / — / — |
| Symbol-bars evaluated | **6** (of ~180 expected) |
| Days with any tape | **2** of 10 weekdays (Jul 20, Jul 24) |
| Runtime duty cycle (bar-coverage proxy) | **~3.3%** |
| Silent weekdays | Jul 15–17, 21–23, 27–28 (8 of 10) |
| Per-player equity ledger | all 7 at 100.0 — untouched, correct for n=0 |

**The finding this week is operational, not strategic.** There is no
strategy evidence to read — zero proposals over six bars is exactly
what a selective H4 zones ensemble should do on mid-range bars — but
the squad runtime was effectively not running. The shadow clock
(D095 step 2) has not started; every action item below is ops.

---

## 1. What the tape actually shows

Six `tick_summary` rows and nothing else — no proposals, no Sentinel
blocks, no closes, and notably **no `system_status` rows**, which
means the runtime never lived long enough to complain about anything.

| Tick(s) | Bar close (UTC) | Symbols | Outcome |
|---|---|---|---|
| 1–3 | Mon Jul 20, 19:00 | EURUSD, GBPUSD, USDCAD | all players abstained, clean reasons |
| 4–6 | Fri Jul 24, 07:00 | EURUSD, GBPUSD, USDCAD | all players abstained; Karasu advisory (below) |

Two facts fall out of the gaps:

- **Each run observed exactly one H4 close.** The grid closes at
  03/07/11/15/19/23 UTC; a process that survived 4 more hours would
  have evaluated the next bar. So the window contained two short
  manual runs, not a polling service.
- **Tick numbering is continuous (1–6) across the two runs** and
  `state.json` carries `tick_id: 6` — state persistence across
  restarts is working (tick counter, equity, publish counts all
  carried over).

Expected coverage for the window: 10 weekdays × 6 H4 closes × 3
symbols = **~180 symbol-bars**. On tape: **6**.

## 2. Why the runtime was down (the checklist answer)

The bundle's own checklist asks "was the runtime down?" for 8
weekdays. Yes — and the reasons are on the decision ledger, not
mysterious:

- This window absorbed the **VM cutover + I015 MT5 account-contention
  incident** (D124/D125, Jul 24): the v2 broker probe switched the
  VM's single terminal to the V2 account, v1 saw a phantom drawdown
  and correctly wrote kill.txt. The dual-terminal pin fix and v1
  recovery consumed the cutover day.
- **`run_watchdog.py --loop` was never wired into Task Scheduler**
  (runbook 7b.8/7c step, still the open item in ai_context's next
  goal). With no scheduled supervisor, the squad only runs when a
  human starts it, and it dies with the session.

So the silent weekdays are an omission (scheduling never finished),
not a crash signature. No crash fingerprints, no kill.txt events, no
feed errors on tape.

## 3. The plumbing that did run looks healthy

Small n, but everything observable behaved to spec:

- **Roster routing is exactly right.** Rin appeared only on EURUSD
  ticks (EURUSD-only precision specialist), Barou only on USDCAD,
  Chigiri on EURUSD+GBPUSD, and the generalists (Bachira, Isagi,
  Nagi, Reo) on all three pairs. Workspace publish counts match
  evaluated ticks one-for-one (6/6/6/6 generalists + Karasu, 4
  Chigiri, 2 Rin, 2 Barou).
- **Abstentions carry machine-readable reasons** (`no_zone_touch`,
  `no_breakout`, no peer tag+coord overlap, D1-counter alignment)
  with confidence 0.0 across the board — no spurious conviction on
  bars nobody should trade.
- **Karasu's news read is a live timezone corroboration.** On the
  Jul 24 07:00 EURUSD tick it flagged "medium-impact EUR event
  ('French Flash Manufacturing PMI' in +15 min) — advisory blackout".
  French Flash PMI publishes 07:15 UTC in summer — the +15-minute
  lead is exact, a third independent anchor for the A004/I007
  calendar-timezone verdict (alongside Claims 12:30 and Flash PMI
  13:45).
- **The Phase AE gate is holding:** `sae_enabled: false` in state,
  zero Sae rows on tape. Correct — Sae stays benched (D111).

## 4. One open question from the Jul 28 boot

The heartbeat shows a single sample (`tick=6` at 14:32:08Z), state
was saved at 14:32:26Z, and the report generated at 14:34:28Z — a
fresh boot minutes before the bundle was made. In that snapshot:

- `last_bar_times` for all three pairs sit at **Jul 24 07:00 UTC** —
  4 days stale at boot time (latest closed H4 on Jul 28 14:32 should
  be Jul 28 11:00). This is either (a) persisted state the fresh
  process hadn't updated yet in its first ~20 seconds, which is
  benign, or (b) **terminal B's read-only bar feed serving stale
  data**, which is not. One check distinguishes them: after two poll
  intervals, `last_bar_times` must advance past Jul 24 07:00.
- `burn_in_remaining: 2` on all pairs: the D110 warm-up design burns
  two live H4 closes (~8 h) after every restart before players
  evaluate. Under manual stop-start operation this is a standing tax
  — another argument for continuous scheduled running, and worth
  remembering when reading next week's bar counts.

## 4b. Post-review addendum (same day): the /v2 countdown is on the wrong grid

Cross-checking the bundle against a live /v2 screenshot (2026-07-28
14:59 UTC) surfaced one more defect: the "Next bar close" countdown
said 16:00 UTC when the real next close was 15:00 UTC — the panel's
`nextH4CloseMs()` assumes the 00/04/08/12/16/20 UTC grid, while the
tape's closes (19:00, 07:00; pinned as true wall-clock moments by
Karasu's +15-minute PMI advisory) sit on 03/07/11/15/19/23 UTC.
Display-only: the runtime polls at least every 60 seconds, so bars
are evaluated on time regardless. Filed as intake I018 and shipped
the same day (D128) — the countdown now anchors to the tape's own
`tick_summary` timestamps, keeping the midnight grid only as a
no-tape fallback.

## 4c. Post-review addendum (same day): the real root cause was a frozen feed, not just downtime

Section 2 attributed the silent weekdays to the runtime only running
when a human started it. Downtime was real but **secondary**: the Jul
28 manual restart with `--feed mt5` still pinned `last_bar_times` at
Jul 24 07:00, which led to the deeper find. `_connect_mt5` in
`run_squad_live.py` built a bare `LiveConfig()`, whose `broker_type`
defaults to `"paper"` — and `PaperBroker` memoizes the parquet cache
once at boot and never serves a newer bar. Every "live" session
therefore evaluated the newest *cached* bar once (that's Bachira's
0.75-conviction EURUSD fade burst) and then starved. Even perfect
24/5 Task Scheduler uptime would have produced the same silent tape.
Filed as **I019 (P0 — blocks the shadow clock)** and shipped the same
day (D129): the feed now attaches a real MT5 broker with `.env`
credentials, mirroring v1's `run_live.py`, and raises loudly rather
than degrading to a frozen snapshot. Four regression tests pin it.

Two clarifications this investigation nailed down:

- **Bar labels are OPEN times.** The tape's 07:00 / 19:00 UTC stamps
  are H4 opens on the 03/07/11/15/19/23 grid; evaluation happens at
  the close, four hours later. The Section 3 narrative ("evaluated
  the 19:00 / 07:00 bars") stands, but read those as open labels.
- **That labeling has a semantics consequence for Karasu**: his
  ±15-min window is checked at the open label, ~4 h before the real
  entry moment. The Jul 24 "PMI in +15 min" advisory was imminent
  relative to the label but ~3 h 45 m stale relative to the decision.
  Whether the window should protect the just-closed bar or the
  upcoming entry is now a pre-registered research question — intake
  I020, M001 Phase AD.2 draft in the research repo (D130). The live
  path deliberately stays as-is until that study reports.

## 5. Recommendations (prioritized)

1. **Finish the shadow-clock wiring — this is already the declared
   next goal, now with a measured cost attached.** Run the runbook
   7b.8 redeploy checks and 7c ceremony, and wire
   `run_watchdog.py --loop` into Task Scheduler so the runtime
   survives logouts/reboots. Success metric for the next bundle:
   0 silent weekdays, ~90 symbol-bars per 5-day week.
2. **Verify the bar feed advanced after the Jul 28 boot** (Section 4
   check). If `last_bar_times` stays pinned at Jul 24 07:00, inspect
   the dedicated v2 terminal's login/market-watch state before
   anything else.
3. **Candidate intake item: a watchdog check for squad-tape
   freshness** ("no tick_summary within N hours during market
   hours" and/or "last_bar_times older than 2 grid closes"). The
   F017 watchdog is the natural home; this week's 8 silent weekdays
   would have been caught on day one. File through the normal R&D
   intake, not as a drive-by patch.
4. **Keep the weekly bundle cadence.** The D126 tool did its job on
   its first real outing — the auto-flagged checklist surfaced the
   real issue (silent weekdays) with zero analyst effort.

## 6. One-paragraph verdict

The v2 squad's first weekly window produced no strategy evidence and
was never going to: the runtime ran for two brief manual sessions
(one bar-close each) in a fortnight dominated by the VM cutover and
the I015 terminal-contention incident, and the Task Scheduler wiring
that would keep it alive was never completed. What did run behaved
exactly to spec — correct specialist routing, reasoned abstentions,
a to-the-minute Karasu news advisory that independently corroborates
the calendar-timezone audit, and the Sae bench gate holding. Start
the shadow clock properly and confirm the fresh boot's bar feed is
advancing; until there are full weeks on tape, weekly reviews of v2
will keep grading the ops layer rather than the players.
