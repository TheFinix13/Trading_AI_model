# Week Review — 2026-07-28 → 2026-08-03 (v1 live agent, 3 pairs)

> Post-mortem of one live week on the Exness demo, from the VM weekly
> bundle (`weekly_report_2026-07-26_to_2026-08-04.zip`). Sources: the
> bundle's REPORT.md, per-symbol daily logs, vault events.jsonl, state
> sidecars, and a fresh Dukascopy H4/D1 pull (through Aug 3 20:00 UTC)
> for the near-miss resolver pass. Per `WEEKLY_LEDGER.md` protocol the
> new-information window is Jul 28 15:25 UTC → Aug 3 14:07 UTC; the
> Jul 26–28 overlap was used as a cross-check only and matches the
> prior ledger row.

---

## Headline

| Metric | Value |
|---|---|
| Realized P&L (window) | **+34.34 USD** (5 closes) |
| Balance | 969.54 → **1003.88** (+3.54%) — first close above $1,000 since the ledger began |
| New entries this window | **3/3 winners** (+1.50R, +1.49R, +1.73R = +4.72R) |
| Carried pre-window positions | 2/2 losers (−1.34R, −1.17R = −2.51R), both soft-SL exits |
| Sum of R (realized) | **+2.21R** |
| External/unexplained P&L | **0.00** — clean bookkeeping, no phantom closes (I016 fix holding) |
| Open at window end | **None** — flat book since Jul 31 11:56 UTC |
| Incident | Aug 3 VM outage (network death 10:26 UTC → full VM death ~14:07 UTC), agent code blameless |

The user's read is confirmed by the ledger math: every trade the agent
*entered* this week hit take-profit; the only losses were the two
orphaned longs carried in from before the window (Jul 21 / Jul 24
entries), which the restart-adoption logic closed at their inferred
soft stops exactly as the prior review predicted.

## The five closes

| Pair / ticket | Dir | Entry → Exit | R | Read |
|---|---|---|---|---|
| GBPUSD 3000652586 (carried, Jul 24) | long 1.33365 → 1.32871 | −1.34R | Adopted at the Jul 28 17:59 restart with inferred soft 1.32995; first H4 close below it (20:00 UTC) exited. Exactly the "expected behaviour at restart" forecast in the Jul 28 review. |
| USDCAD 2987854368 (carried, Jul 21) | long 1.40992 → 1.40358 | −1.17R | Same adoption path, inferred soft 1.40450, exited Jul 30 00:00 UTC. MAE 75.9p — the soft stop saved ~29p vs the catastrophe SL. |
| GBPUSD 3016057905 | long 1.32864 → 1.33055 (TP) | **+1.50R** | Entered Jul 29 00:00 UTC, four hours after the carried long died (the 20:00 re-fire was PLG-blocked, see below). TP in 7.6h, +19p. |
| GBPUSD 3021464942 | long 1.33463 → 1.34686 (TP) | **+1.49R** | Entered Jul 29 20:00 UTC with an 82p stop; rode the leg to TP in 20h. **+122.3p — biggest pip win of the live run.** MFE 121.8p, essentially zero giveback. |
| EURUSD 3026429701 | short 1.15224 → 1.14857 (TP) | **+1.73R** | Entered Jul 30 16:00 UTC. **First EURUSD trade of the entire live run** — the htf-neutral dead zone finally cleared. BE move at 1R, TP next day, +36.7p (MFE 36.6p). |

Pattern note (third window running): the mean-reversion book keeps
paying on the re-entry after the first attempt stops out. Also note
both GBPUSD winners and the EURUSD winner exited at TP with MFE ≈
pnl — no "winner exited too early" pain this week; TP placement was
at the actual extent of the move.

## Sequencing detail worth keeping (Jul 28, GBPUSD)

At the 20:00 UTC H4 close the carried long soft-stopped (−1.34R) and
the SAME close produced a fresh long signal, which the just-armed
post-loss cooldown (60 min) blocked. The signal re-fired at the next
H4 close (Jul 29 00:00) and became ticket 3016057905 (+1.50R). So the
PLG cost nothing this week — entry deferred 4h, same outcome. The
resolver scores the blocked 20:00 attempt +1.50R (a win), consistent.

Also verified at the 17:59 restart: `[STATE LOADED] post_loss_guard
state is from 2026-07-27 — discarded` — the I015 phantom-loss
pollution (USDCAD ×0.5 sizing) cleaned itself up via day-scoping, as
designed.

## Near-miss counterfactuals (resolver, fresh Dukascopy data — hypothesis-generating only)

| Pair | Reason | n | W/L (open) | win% | avg R |
|---|---|---|---|---|---|
| EURUSD | htf_gate | 10 | 3/5 (2) | 38% | −0.06 |
| GBPUSD | htf_gate | 14 | 1/11 (2) | 8% | −0.79 |
| GBPUSD | risk_manager (max_positions) | 4 | 4/0 | 100% | +1.50 |
| GBPUSD | post_loss_guard | 1 | 1/0 | 100% | +1.50 |
| USDCAD | htf_gate | 9 | 1/4 (4) | 20% | −0.50 |

Verdicts, second consecutive window:

1. **The HTF gate earned its keep again.** All three htf_gate buckets
   are net negative; GBPUSD's is brutally so (1/12 resolved, −0.79R
   avg). No throughput complaint survives contact with the resolver.
2. **max_positions blocks are now 6/6 winners (+1.50R avg) across two
   windows.** Last week's review said "if it recurs, it goes through
   the research lane as a pre-registered E0xx." It recurred: all four
   blocks were long re-fires while capital sat in the doomed carried
   long. This is now a chartered research-lane candidate: relaxing
   `max_open_positions=1` (or queue-replacement of a losing ticket by
   a fresh same-direction signal). n=6 is still tiny; it earns a
   pre-registration, not a config change.

## Incident — Aug 3 outage (the healthcheck DOWN alerts)

Timeline (UTC; note the VM logs in UK local = UTC+1, see finding 2):

| Time (UTC) | Event |
|---|---|
| 10:11 | Last successful healthcheck ping (all three symbols healthy). |
| 10:26 | First `getaddrinfo failed` (Errno 11001) on all three processes simultaneously — **VM lost internet/DNS**. Agents keep running; heartbeats continue on MT5's cached account data. |
| ~10:46 | healthchecks.io grace expires → Telegram DOWN alerts for EURUSD/USDCAD/GBPUSD ("Last Ping: Success, 35 minutes ago" — matches 10:11 exactly). **The dead-man's-switch worked precisely as designed.** |
| 12:00 close | H4 evaluation silently skipped — the broker-disconnected terminal never formed the 12:00 bar (see finding 1). |
| 13:57–13:58 | Last heartbeats (balance $1,003.88, 0 open positions, all three symbols). |
| 14:07 | `IPC send failed` — MT5 terminal gone. Logs end abruptly ~14:07:30, no SIGTERM, no shutdown lines → **hard VM death** (freeze/reboot/power), not a process crash. |
| — | No self-restart afterward: the Task Scheduler watchdog setup (docs/08) has never been executed on the VM. |
| ~01:37 Aug 4 | VM back up (user ran `weekly_report.py`), agents not restarted, then user powered down pending this review. |

Diagnosis: **two-stage host-level failure — network died first, the
whole VM followed 3.7 hours later.** This is the recurring "VM freezes
every ~3 days" OS-level pattern from the v0.25 review (Windows Update
auto-reboot the leading suspect; a VMware/host issue is the
alternative). Nothing implicates the agent or MT5: all three processes
stayed healthy through 3.5h of dead network, kept logging, retried
pings 3× per heartbeat, and skipped account-read cycles on IPC failure
without fabricating balances — no phantom DD halt, no kill.txt (the
I015 hardening held).

Exposure during the outage: **zero.** The book had been flat since
Jul 31 and balance was static at $1,003.88 throughout. The real cost
is coverage: the agent was signal-blind from 10:26 UTC Aug 3 until
whenever it is restarted (the 12:00/16:00/20:00 Aug 3 and all Aug 4
H4 closes went unevaluated).

### Secondary findings (observation-only, intake candidates)

1. **Silent H4-close skip.** When the terminal has no fresh bar at a
   scheduled H4 close, the signal loop advances its "next close"
   pointer without logging anything (12:56 heartbeat says "next
   ~12:00", 13:12 says "next ~16:00", nothing in between). One WARNING
   line ("H4 close 12:00 skipped — no fresh bar from terminal") would
   have made the blind window visible in the log itself.
2. **Log-timestamp convention.** The VM writes log timestamps in UK
   local time (UTC+1): "H4 close 08:00 UTC: evaluated" is stamped
   09:00:03 while `state.json.saved_at` records 08:00:03Z for the same
   event. `weekly_report.py` labels the merged heartbeat timeline as
   UTC, so every bundle time is +1h skewed. Harmless this week, but it
   cost real minutes during this incident reconstruction.

## Recommendations

1. **Turn the VM back on and restart the three agents — safe to do
   now.** No kill files, no halted state; the PLG state sidecars are
   from Aug 3 and will be discarded as stale-day on load. The book is
   flat, so restart-adoption has nothing to adopt.
2. **Execute the self-healing setup this week** (Windows autologon +
   MT5 in Startup + three Task Scheduler `AtLogOn` watchdog tasks per
   `docs/08-live-trading-and-deployment.md`). Pending since Jul 6;
   this is the second consecutive window where a VM death required
   manual recovery, and it is now the top operational priority. While
   in there, check Windows Update active-hours/reboot policy — the
   likely root cause of the freezes.
3. **File the max_positions relaxation as a pre-registered research
   study** (research repo E0xx lane): 6/6 counterfactual winners
   blocked across two windows while a losing carried ticket held the
   slot. No production config change from n=6.
4. **Intake the two observability findings** (silent H4-close skip
   WARNING; weekly_report timezone normalization). Both are
   observation-tooling, not live-path.

## Addendum — manual chart read, Jul 27–31 (trader-vs-agent, hindsight-tainted by construction)

Independent read of the fresh Dukascopy H4/D1 tape for the three
pairs, compared bar-by-bar against the agent's actual book. Honest
scoring: every "I would have" below is exposed to hindsight bias; the
only claims allowed to graduate are ones the resolver or a
pre-registered study can carry.

1. **GBPUSD — parity, and the exit was near-optimal.** Both agent
   longs are trades a discretionary trader takes (second touch of the
   1.3280s demand shelf after basing; the 20:00 breakout bar). Holding
   trade 2 past its 1.34686 TP was NOT better: rung 1 (1.34807) was
   only touched a full day later (+12p more) after a −69p pullback to
   1.34000, and rung 2 (1.35266) never printed through Aug 1. MFE ≈
   realized pips on all three wins this week — the "winners exit too
   early" pain from the Jul 11–20 window did not recur.
2. **EURUSD — the machine beat my discretion on the short.** No
   discretionary trader shorts 1.15224 into a two-day +200p breakout;
   I would have skipped it and missed +1.73R. The against-D1 fade
   design monetized the retracement with 1.5R asymmetry and got out
   11 minutes before the trend resumed (price was back at 1.1547 by
   20:00 the same day). Point to the design.
3. **EURUSD/USDCAD — the real gap is with-trend entries, and it is a
   new-alpha question, not a gate tweak.** The trades I genuinely
   wanted that the agent structurally cannot take: the EURUSD
   breakout long Jul 29 16:00 → Jul 30 12:00 (1.1448 → 1.1537,
   ~+1.5–2R managed) and the USDCAD breakdown short Jul 29 16:00
   (1.4057 → 1.4001, ~+1.1R). Both are WITH the D1 trend; the
   `htf_against` cell fades it by design. Crucially the resolver
   already scores naive unblocking as a wash-or-worse (EURUSD
   htf_gate −0.06R avg, USDCAD −0.50R): the money is only in a
   *selective* momentum/breakout entry, i.e. a separate with-trend
   cell through the full validation chain, not a looser gate.
4. **USDCAD carried long — discretion would have saved ~+1.4R of the
   damage** (exit into the Jul 28 lower-high retest at ~1.4110–1.4126
   instead of the −63p soft-stop). Recorded as an observation only:
   E020/E024/E026 all failed to validate mechanical early-exit rules,
   so this stays anecdote until a new pre-reg says otherwise.

Net: a hindsight-perfect discretionary week beats +2.21R, but every
durable improvement it points to is already queued — the
max_positions slot-blocking study (6/6 blocked winners) and a
with-trend cell as a research-lane candidate. Exit placement needs no
change on this week's evidence.

## Cross-check vs prior ledger row (Jul 26–28 overlap)

Balance start 969.54 matches the Jul 28 row's end. The two carried
tickets (GBPUSD 3000652586, USDCAD 2987854368) reconcile: open at the
prior window end, both closed this window at their inferred soft
stops, at the levels the prior review predicted (1.32995 / 1.40450).
The Jul 28 15:15–15:25 MT5-update outage and 17:59 restart appear in
this zip's logs exactly as recorded last week. No divergence.
