# 08 — Live Trading & Deployment

> **Current (2026-06-10).** This doc reflects the v2 router-based live loop.
> What trades live, and the evidence behind it, is in
> [CHECKPOINT.md](CHECKPOINT.md); the path that got here is
> [00-journey.md](00-journey.md).

The live agent trades the **validated zone strategy** (`zone_d1_against` — H4
supply/demand zone touch faded against the D1 trend) through the deployment
router. There is no strategy selection at the CLI: the routing table
(`agent/alphas/zone_routing.py`) decides what a symbol trades, on which
timeframe, and at what risk scale — or refuses to trade it at all.

The live `MetaTrader5` Python package is **Windows-only**, so MT5/Exness
execution needs Windows (VM, VPS, or native); paper trading and all research
run anywhere.

**Progression: paper → demo → live.** Always validate on paper, then demo,
before risking real capital.

---

## 08.1 How the live loop is wired

```
ROUTING_TABLE (zone_routing.py)          evidence-gated deployments
        │  survivors() only — skip cells never leak
        ▼
build_live_routes(symbol)  (agent/live/router_wiring.py)
        │  alpha + timeframe + risk_scale per cell
        │  unknown symbol → UndeployedSymbolError (hard startup failure)
        ▼
scripts/run_live.py  --alpha router      one process per symbol
        ▼
SignalLoop ── PositionSizer (risk band × risk_scale) ── risk guards ── broker
```

Key facts:

- **`run_live.py` defaults to the router** (`--alpha router`). The routing
  table fixes the timeframe (H4 for every deployed cell today); a `--timeframe`
  override is ignored with a warning, because changing the TF silently changes
  the strategy away from what was validated.
- **Undeployed symbols refuse to start.** There is deliberately no fallback
  alpha — trading anything the validation pipeline didn't sign off is worse
  than not trading.
- **`risk_scale` flows into sizing.** Each routed cell's risk multiplier
  (EURUSD 1.0, GBPUSD 0.5, USDCAD 0.5) scales the conviction-band risk before
  the `PositionSizer` computes lots. Half-risk cells are frozen-cross-pair
  deployments awaiting live confirmation.
- **`--alpha reaction` is an escape hatch**, not a mode: it runs the
  UNVALIDATED/experimental `ReactionAlpha`. Never use it on a funded account.
- The v1 `--mode anticipation|reaction|hybrid` flag, ML scorers, and the
  dashboard no longer exist.

## 08.2 Multi-symbol deployment: one process per pair

The portfolio is three processes, each pinned to one symbol via the `SYMBOL`
environment variable (or config):

```bash
# macOS/dev: paper trading, one terminal per symbol
SYMBOL=EURUSD PYTHONPATH=. .venv/bin/python scripts/run_live.py --broker paper
SYMBOL=GBPUSD PYTHONPATH=. .venv/bin/python scripts/run_live.py --broker paper
SYMBOL=USDCAD PYTHONPATH=. .venv/bin/python scripts/run_live.py --broker paper
```

Each process loads only its own symbol's routed cells, so a failure in one pair
can't take down the others. The shared account-level guards (3% daily-DD halt,
kill switch) still protect the account as a whole.

> **Correlation caveat:** the three pairs are USD-correlated — EURUSD long +
> GBPUSD long + USDCAD short is roughly one "USD down" bet (~4% worst-case
> combined risk under today's per-trade caps). A portfolio-level USD-exposure
> manager is on the roadmap ([CHECKPOINT.md](CHECKPOINT.md)); until then the
> bound is per-trade caps + the daily-DD account guard.

## 08.3 Sizing and the small-account caveat

Sizing is risk-based: conviction interpolates within a **0.5%–2.0%** band of
live balance, multiplied by the cell's `risk_scale`, then clamped to broker lot
step / min / max and free margin (see
[05 — Position Sizing & Risk](05-position-sizing-and-risk.md)).

> **$100-account caveat (H4 reality).** H4 structural stops are wide. At the
> broker minimum lot (0.01), the dollar risk of an H4 stop can exceed the
> entire 0.5–2% risk band on a $100 balance — in that case the sizer **skips
> the trade** rather than oversize it. On a half-risk pair (GBPUSD/USDCAD) the
> band is effectively 0.25–1%, making skips more likely still.
> **Recommendation: run the demo with $500+** so minimum-lot H4 trades fit
> inside the risk band and the live distribution actually matches the backtest.

## 08.4 Windows / VM setup

| Requirement | Details |
|---|---|
| **Windows machine** | VMware/Parallels VM, Windows VPS ($10–20/mo), or native Win 10/11 |
| **MetaTrader 5** | Installed and logged into your Exness account |
| **Python 3.11+** | Auto-installed by the deploy script if missing |
| **Git** | Auto-installed by the deploy script if missing |

```powershell
# Option A — one-liner (Run PowerShell as Administrator)
irm https://raw.githubusercontent.com/TheFinix13/Trading_AI_model/main/scripts/deploy_windows.ps1 | iex

# Option B — manual clone then run
git clone https://github.com/TheFinix13/Trading_AI_model.git "$HOME\Documents\GitHub\multi-pair-trading-agent"
cd "$HOME\Documents\GitHub\multi-pair-trading-agent"
.\scripts\deploy_windows.ps1
```

### Running 24/5: Task Scheduler + autologon, NOT a Windows service

> **Do not use NSSM / a Windows service for this.** `MetaTrader5`'s Python
> API talks to the MT5 terminal over local IPC that only works within the
> terminal's own interactive desktop session. Windows Services (NSSM
> included) run isolated in "Session 0" and cannot reach that desktop, so a
> real service will likely fail to connect to MT5 at all, or connect to the
> wrong/no terminal instance. This is a well-documented MT5 automation
> gotcha, not specific to this repo. The reliable pattern is: Windows
> Autologon (so an interactive desktop exists after a reboot with nobody
> physically logging in) + MT5 in the Startup folder + a Task Scheduler task
> per symbol running as that logged-on user, wrapped in a self-restarting
> loop (`scripts\watchdog_agent.ps1`) so a process crash — not just a
> reboot — also self-heals.

**1. Enable autologon** (Microsoft [Sysinternals Autologon](https://learn.microsoft.com/en-us/sysinternals/downloads/autologon)) for the
Windows account MT5 runs under. Without this, a reboot leaves the machine
sitting at the lock screen with no desktop session for MT5 or the agent to
run in.

**2. Auto-start MT5**: put a shortcut to the MT5 terminal executable in the
Startup folder (`Win+R` → `shell:startup`) so it launches and reconnects on
logon, before the agent tries to attach to it.

**3. Register one scheduled task per symbol**, running as the interactive
user (adjust `$RepoDir` if your clone lives elsewhere):

```powershell
$RepoDir = "$HOME\Documents\GitHub\multi-pair-trading-agent"
$symbols = @("EURUSD", "GBPUSD", "USDCAD")

foreach ($sym in $symbols) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RepoDir\scripts\watchdog_agent.ps1`" -Symbol $sym" `
        -WorkingDirectory $RepoDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $trigger.Delay = "PT45S"   # give MT5 time to fully log in first
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
        -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName "TradingAgent-$sym" -Action $action `
        -Trigger $trigger -Settings $settings -Principal $principal -Force
}
```

`watchdog_agent.ps1` runs `run_live.py` in an infinite loop, so a crash,
kill-switch halt, or MT5 disconnect restarts that symbol's process on its
own (15s backoff) without waiting for the next reboot. The Task Scheduler
trigger only needs to fire once per logon session — the loop does the rest.

Verify by rebooting (or logging off/on): MT5 should reappear, and within
~1 minute you should get three `Agent ONLINE` messages on Telegram with no
one touching a keyboard.

### The one thing this still can't catch: a genuine VM freeze

Every alert above (Telegram included) is sent *by the agent process*. If
the whole VM hard-freezes, there's no code left running to send anything —
it just goes silent, watchdog and all. The only way to catch that is an
**external** dead-man's-switch: something outside the VM that expects a
periodic ping and raises its own alarm when one goes missing.

`agent/notifications/healthcheck.py` pings such a service (any provider
compatible with [healthchecks.io](https://healthchecks.io)'s simple
GET-to-URL contract; free tier is generous and has a built-in Telegram
integration) once per heartbeat (every 15 min) — no code change needed,
just set the URL:

1. Create a free account at [healthchecks.io](https://healthchecks.io),
   add one check per symbol (Period ≈ 20 min, Grace ≈ 15 min — tolerates
   one missed ping before alerting, catches two in a row within ~35–50 min
   of the freeze starting).
2. Add each check's ping URL to the VM's `.env`:
   ```env
   HEALTHCHECK_URL_EURUSD=https://hc-ping.com/<eurusd-check-uuid>
   HEALTHCHECK_URL_GBPUSD=https://hc-ping.com/<gbpusd-check-uuid>
   HEALTHCHECK_URL_USDCAD=https://hc-ping.com/<usdcad-check-uuid>
   ```
3. Under each check's Integrations tab, add Telegram (or email) so a missed
   heartbeat pages you the same way a halt already does.
4. Smoke-test before trusting it: `python scripts/ping_healthcheck.py
   --symbol EURUSD` (exit code doubles as pass/fail, same contract as
   `notify_telegram.py`).

An emergency close (daily-DD halt or kill switch) sends an immediate
**success** ping annotated with the halt reason (not a `/fail` ping), so
healthchecks.io stays **UP** while the process is alive-but-halted. A
`/fail` ping is reserved for genuine process death (consecutive fatal
errors). Telegram still pages you on the halt via the `TRADING HALTED`
message.

Note: an *intentional* stop (e.g. Ctrl+C to pull new code) will also trip
the check if you don't restart within the grace window — that's a correct,
if slightly noisy, "yes it's actually down" alert, not a bug.

### Healthcheck accuracy (2026-07-13 tuning)

The July 11–12 false "DOWN" flaps (checks red for ~9–10 min while the
agents were alive) were caused by the combination of: a 15-min ping
cadence against a 20-min check period (only 5 min of slack), the VM's
occasional DNS blips (`Healthcheck ping failed: getaddrinfo failed`,
2026-07-11 03:12 UTC), and no retry — so a single dropped ping blew the
window. Three behaviours now prevent that:

1. **Retry on transient failure.** Each ping retries up to 3 attempts
   with a short linear backoff (2s, 4s) before giving up; still
   fail-open (a broken watchdog ping can never crash the loop). One
   DNS blip no longer costs a whole 15-min heartbeat slot.
2. **Halted ≠ dead.** The heartbeat ping fires even while the kill
   switch is active (the process IS alive — `_maybe_heartbeat` runs at
   the top-level loop, outside the kill-skip path), and while halted the
   ping carries a body like `EURUSD HALTED by kill switch (kill.txt) -
   process alive`, visible in the check's event log. Intentional risk
   halts (daily-DD, kill switch) also send an immediate annotated
   **success** ping — never `/fail` — so healthchecks.io does not mark
   the check DOWN for a pause that is not a crash.
3. **Settings to apply in the healthchecks.io web UI** (per check):
   **Period = 20 min, Grace = 15 min.** With pings every 15 min, the
   worst healthy gap after one fully-failed ping (all retries lost) is
   30 min — inside the 35-min alert threshold (period + grace) — so a
   single missed ping never pages, and a VM reboot's typical ~9-min gap
   is absorbed too. Two consecutive missed pings (a real problem) still
   alert within ~35 min. Don't go wider (e.g. period 30/grace 10 has a
   40-min blind spot for a genuine freeze with no better false-alarm
   behaviour).

## 08.5 Exness / MT5 connection

### Get demo credentials

1. Sign up at [exness.com](https://www.exness.com) (free, no deposit for demo).
2. Personal Area → **Open New Account** → MetaTrader 5, USD, **Demo** —
   fund it **$500+** (see the small-account caveat above).
3. Note the **Login** (numeric), **Password**, and **Server** (e.g. `Exness-MT5Trial7`).
4. Install MT5 from the Exness Personal Area, log in, confirm charts load for
   EURUSD, GBPUSD, USDCAD.

### Configure `.env`

```env
MT5_LOGIN=12345678
MT5_PASSWORD=your_trading_password
MT5_SERVER=Exness-MT5Trial7

# Optional: explicit terminal path (usually auto-detected)
# MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe

# Optional: Telegram alerts
# TG_BOT_TOKEN=bot123456:ABC-DEF...
# TG_CHAT_ID=123456789

# Optional: external dead-man's-switch heartbeat (catches a VM freeze)
# HEALTHCHECK_URL_EURUSD=https://hc-ping.com/<eurusd-check-uuid>
```

### Run

```powershell
.\.venv\Scripts\Activate.ps1

# Step 1 — paper mode (full pipeline, in-memory fills; validate signals first)
$env:SYMBOL="EURUSD"; python scripts/run_live.py --broker paper

# Step 2 — demo execution (MT5 must be open and logged in)
$env:SYMBOL="EURUSD"; python scripts/run_live.py --broker mt5
```

**Key flags:** `--broker {paper,mt5,exness}`, `--alpha {router,reaction}`
(default router), `--interval` (poll seconds), `--balance` (paper starting
balance), `--no-revenge-guard` (NOT recommended), `--no-telegram`,
`--kill-switch {on,off}`, `--verbose`.

**What to expect:** H4 cells trade on H4 candle closes that touch a daily zone
counter to the D1 trend — roughly 66 trades/yr on EURUSD (~1–2/week), any
session, so days with no signal are normal. Startup logs print each routed
cell: `Routed cell: EURUSD/H4/all mode=htf_against risk_scale=1.00 ...`.

### Troubleshooting

- **"Symbol 'X' has no deployed cells"** — by design: the symbol isn't in the
  routing table. Deployments are earned through the validation pipeline, not
  config.
- **"MT5 init failed"** — the terminal must be open and logged in on the same
  machine (the package talks to it via IPC). Open MT5, log in, restart.
- **Sizer skips every trade** — balance too small for H4 min-lot risk (see
  08.3). Increase the demo balance.
- **"Connection lost"** — the agent auto-reconnects with backoff then exits
  cleanly; the Task Scheduler watchdog loop (§ above) restarts it.

### Monitoring & kill switch

```powershell
# Kill switch (halts new trades; delete the file to resume)
echo halt > kill.txt
```

Telegram alerts (trade open/close, DD halt, kill switch) activate when
`TG_BOT_TOKEN` / `TG_CHAT_ID` are set in `.env`. The external healthcheck
heartbeat (catches a VM freeze that Telegram can't) activates when
`HEALTHCHECK_URL_<SYMBOL>` is set — see 08.4 above. The per-day journal
(markdown + JSONL) is the trade record; the v1 web dashboard was burned in the
reset ([09](09-dashboard.md)).

### Telegram message format (2026-07-13 revision)

All three symbol processes post into ONE shared group, so **every message
now leads with the symbol**: first line is `SYMBOL | <event>` (bold), e.g.
`GBPUSD | Trade OPENED`. Builders live in
`agent/notifications/telegram.py` (`build_*` functions, pure and
unit-tested in `tests/test_telegram_notifier.py`). Current formats:

- **Trade OPENED** — side, alpha, ticket, entry, lots, soft/catastrophe
  SL, TP annotated with its R multiple, risk as % *and* $ amount, live
  balance, plus the extension-ladder note.
- **Trade CLOSED** — WIN/LOSS, P&L $ and pips, **R vs the original
  entry-time risk** (a breakeven move no longer collapses it to a
  confusing `+0.00R`; instead the message appends "risk-free after BE"),
  time held, exit cause in plain words (`take-profit hit`, `soft stop
  (bar closed beyond level)`, …), balance after.
- **BE Move / Soft stop exit / Partial scale-out** — symbol + ticket +
  a one-line meaning.
- **TRADING HALTED** (was "EMERGENCY CLOSE") — symbol of the *reporting
  process*, plain-words halt reason, explicit note that the agent is still
  running (delete `kill.txt` to resume), positions closed on that symbol,
  balance/equity. Because all three processes share one account, an
  account-level event (daily-DD halt → kill file) fires in each process;
  the close action always runs, but each process rate-limits its halt
  *notifications* (Telegram + annotated healthcheck ping) to one per
  10 minutes, so the 2026-07-10 six-message burst is now at most one
  message per process, each tagged with its symbol.

**Daily review ritual:** check overnight trades in the journal, confirm no DD
halt / kill fired, spot-check one trade's reasoning against the routed cell.

### Weekly review bundle

Once a week, run ONE command on the VM (from the repo root) and send the
single zip it prints:

```powershell
python scripts\weekly_report.py --days 7
```

The zip lands in `C:\Users\Fiyin\Documents\TradingAgentLogs\reviews\`
as `weekly_report_<start>_to_<end>.zip` and contains everything a reviewer
needs — no more hand-collecting per-symbol files:

- `REPORT.md` — executive summary (weekly P&L, trade count, win rate,
  downtime %, incidents), per-symbol sections (trade table, signals vs
  rejections with reason breakdown, near-miss vault metadata, H4 coverage,
  downtime windows with kill.txt reasons, balance curve), a cross-symbol
  account view (merged balance/equity timeline, external/manual equity
  moves the agent's own trades don't explain, agent-vs-external P&L split,
  kill-switch cascades), the active parameter snapshot (routed cells,
  risk %, DD limit, post-loss-guard settings), and an auto-flagged review
  checklist (oversized risk, downtime > 12 h, broker rejects, ...).
- Raw daily `.log` files for the window, per symbol.
- The window's near-miss / loss / ladder `events.jsonl` records and their
  chart PNGs (date-filtered, not the whole vault history).
- `state.json` and any `kill.txt`, per symbol.

Useful variants: `--start 2026-07-01 --end 2026-07-07` for an exact window,
`--symbols EURUSD,GBPUSD` to restrict pairs (default: every symbol found
under the log root), `--log-root`/`--out` to override paths. The script is
observation-only and never touches trading state; missing days/symbols/
vault folders appear as MISSING notes instead of crashing.
(`scripts/compile_review_bundle.py` remains for ad-hoc single-symbol
deep-dives; `scripts/daily_summary.py` remains the daily ritual tool.)

---

## 08.6 MT5 chart overlay EA (historical)

`mt5/TradingPartner_Overlay.mq5` visualised the v1 agent's analysis (LZI zones,
FVGs, fibs) by reading `agent_drawings.json`, which the burned v1
`chart_drawer.py` produced. **The current agent does not write that file**, so
the EA is inert — kept in-tree for reference only.
