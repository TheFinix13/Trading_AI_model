# Week Review — 2026-07-15 → 2026-07-28 (v1 live agent, 3 pairs)

> Post-mortem of two live weeks on the Exness demo, from the VM weekly
> bundle (`weekly_report_2026-07-15_to_2026-07-28.zip`). Sources: the
> bundle's REPORT.md, per-symbol daily logs, vault events.jsonl, state
> sidecars, and a fresh Dukascopy H4/D1 pull for the counterfactual
> replay. Companion intake item: I016 (orphaned-position soft-stop gap).

---

## Headline (corrected for the Jul 24 phantom closes)

| Metric | Bundle REPORT.md | Corrected |
|---|---|---|
| Realized P&L | +17.91 (6 closes) | **+20.57 (4 real closes)** |
| Win rate | 50% (3/6) | **75% (3/4)** |
| Sum of R (realized) | — | **+3.83R** (+1.96 +1.49 +1.40 −1.02) |
| "External/unexplained" P&L | +2.66 | **0** — it is exactly the two phantom closes |
| Open at window end | — | GBPUSD 3000652586 long (~−58p), USDCAD 2987854368 long (~+8p) |
| Worst realized loss | −3.14 (−1.02R) | same |
| Balance | 948.97 → 969.54 (+2.2%) | same |

## Scope note — new-information window is Jul 20 → Jul 28

The zip spans 14 days but Jul 11–20 was already analyzed in the Jul 20
session (see `docs/reviews/WEEKLY_LEDGER.md`). The overlap (Jul 15–19)
was used as a cross-check only and matches the prior analysis. **Last
week proper (Mon Jul 20 → Tue Jul 28): realized +14.83** — GBPUSD
2969136564 short TP'd Jul 20 (+7.96, +1.49R, carried in from the prior
window) and USDCAD 2981476697 long TP'd Jul 21 (+6.87, +1.40R). Two
new entries (USDCAD Jul 21 16:00, GBPUSD Jul 24 08:00) are both still
open and both are the subject of the phantom-close/orphan finding
below. Balance Mon open 954.71 → 969.54 = +14.83 exactly.

The two `CLOSED (cause unconfirmed) / manual` rows in the bundle
(GBPUSD −1.89 / −0.50R, USDCAD −0.77 / −0.20R, both 2026-07-24 ~13:25
log time) are **not real closes**. They are bookkeeping artifacts of
the I015 account-contention incident: the V2 broker probe switched the
terminal to the "V2 Platform" account, v1's tickets "vanished", the
monitor journalled phantom manual closes, the phantom $500 balance
tripped the 48.4% "daily DD" cascade (kill.txt on all three symbols,
1.3h halt), and when the account was restored both positions
reappeared — still open through the end of the window. The account
math confirms it: balance delta +20.57 equals the four real closed
trades exactly.

## The four real trades

| Pair | Dir | Entry → Exit | R | Read |
|---|---|---|---|---|
| GBPUSD 2966547972 | short 1.35351 → 1.35055 | +1.96R | Faded the Jul 15 +160p spike day at its top. Model trade. |
| GBPUSD 2969136564 | short 1.35060 → 1.34264 | +1.49R | Re-fade Jul 16; rode the post-spike bleed 4 days to TP. Best trade of the fortnight. |
| USDCAD 2963842103 | long 1.40700 → 1.40259 | −1.02R | Fade-the-downtrend long, 2 days early. Soft-stop did its job (−44p vs −93p catastrophe). |
| USDCAD 2981476697 | long 1.40367 → 1.40851 | +1.40R | Same thesis re-entered Jul 20 at the actual double bottom (1.4005/1.4003). TP next day. |

Classic mean-reversion book: first fade attempt stops, re-entry pays.
The `htf_against` cell design (fade D1 alignment) matched this tape.

## The two still-open trades (both entered Jul 21/24)

- **GBPUSD 3000652586 long 0.01 @ 1.33365** (Jul 24 08:00): long at a
  demand zone directly below a broken 1.3300s shelf in a trending-down
  market. MFE +26.8p (Jul 27 00:00 high), then the Monday dump took it
  to −63.6p MAE. **Its soft stop (1.32987) was crossed Jul 27 ~16:00
  UTC and did not fire — see I016.** Only the catastrophe SL 1.32440
  protects it.
- **USDCAD 2987854368 long 0.01 @ 1.40992** (Jul 21 16:00): chased the
  third leg of the Jul 20 reversal; drew down 42p to Jul 23, now ~+8p
  with the pair trending up. Same orphan state, but its inferred soft
  level was never threatened.

## Near-miss counterfactuals (resolver, fresh data — hypothesis-generating only)

| Pair | Reason | n | win% | avg R |
|---|---|---|---|---|
| EURUSD | htf_gate | 12 | 33% | −0.17 |
| GBPUSD | htf_gate | 8 | 38% | −0.06 |
| GBPUSD | risk_manager (max_positions) | 3 (2 resolved) | 100% | +1.50 |
| USDCAD | htf_gate | 8 | 14% | −0.64 |
| USDCAD | risk_manager | 5 (4 resolved) | 25% | −0.38 |

Honest verdict: **the HTF gate earned its keep this fortnight.** All
12 EURUSD blocks were `htf_bias=neutral` dead-zone blocks (zero EURUSD
trades in 10 trading days), and the eyeball instinct said "throughput
problem" — but the resolved counterfactuals are net negative in every
htf_gate bucket. The only money left on the table was GBPUSD
`max_positions` blocks while capital was tied up in the doomed Jul 24
long (2/2 winners, +1.5R avg, n=2). No gate change is proposed from
n≤12 counterfactuals; if the neutral dead-zone question recurs, it
goes through the research lane as a pre-registered E0xx.

## Incidents

1. **Jul 24 13:25 UTC — I015 account contention** (root-caused and
   fixed same day, D124 dual-terminal pin). Residue in this window:
   phantom closes (above), phantom DD-halt cascade (the only
   "downtime", 1.3h), and PostLossGuard pollution — USDCAD carries
   `consecutive_losses=1 / size_multiplier=0.5` from a loss that never
   happened, so its next entry will be undersized.
2. **NEW — I016 orphaned positions**: after a phantom close, a
   reappearing ticket is never re-adopted mid-run (`_initial_scan_done`
   gate); with `entry_ctx` popped, `_manage_soft_stop()` no-ops. Both
   open tickets have been running without the soft-stop layer since
   Jul 24 14:41. Filed as intake I016; touches `agent/live/monitor.py`
   so it needs a chartered integration slot, not a drive-by fix.
3. **Jul 28 15:15–15:25 — MT5 update/restart**: `IPC send failed` on
   all account reads for ~10 min, then operator SIGTERM. The I015
   hardening behaved exactly as designed: `Account read failed this
   cycle, skipping` + `implausible account reading — not halting` — no
   phantom balance, no kill.txt, clean shutdown. ~10 min blind window,
   positions protected by broker-side stops throughout.

## Expected behaviour at restart (verified against monitor code)

On the next start, the initial scan adopts both tickets with inferred
soft stops (catastrophe distance ÷ 2.5):

- GBPUSD: inferred soft ≈ 1.32995. If price is beyond it at restart →
  immediate `soft_sl_inferred_overshoot` close (correct behaviour — the
  exit the orphan bug missed on Jul 27). At the time of writing price
  bounced back to ~1.3306, i.e. just above the inferred level, so the
  ticket would instead be adopted and managed with soft 1.32995 — any
  H4 close back below it exits.
- USDCAD: inferred soft ≈ 1.40450; price ~1.4107 is safely above →
  adopted and managed normally (TP 1.41773 still working).

## Recommendations

1. Ship nothing to the live path from this review directly; I016 goes
   through triage → charter.
2. When I016 is built, include PostLossGuard reversal for phantom
   closes (USDCAD half-sizing is live right now).
3. Keep the weekly resolver pass (`scripts/resolve_near_misses.py`
   against the bundle) as a standing step — it flipped this review's
   gate conclusion from "too strict" to "protective" with evidence.

## Addendum (same day, user-directed): I016 fixed

The user overrode recommendation 1 and directed an immediate fix.
Shipped 2026-07-28 (see intake I016 history for detail): per-cycle
untracked-ticket sweep with a one-cycle adoption grace, phantom-close
reopen that restores the ORIGINAL entry context (persisted across
restarts), `PostLossGuard.revert_close()` + same-day day-pnl reversal,
`MT5Broker.reconnect()` with monitor auto-reinit after ~60s of failed
reads (kills the "restart PowerShell after every MT5 update" chore),
and `weekly_report.py` reverting phantom closes on `[REOPENED]` lines.
12 new tests; full suite 905 green. Recommendation 2 is thereby done;
the PostLossGuard revert fires automatically on reopen. Deploy to the
VM (git pull + restart the three agents) is the remaining step — on
that restart the two orphaned tickets are re-adopted with inferred
soft stops (original ctx was already lost before this fix existed).
