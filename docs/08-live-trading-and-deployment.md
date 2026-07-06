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
  cleanly; NSSM restarts it.

### Monitoring & kill switch

```powershell
# Kill switch (halts new trades; delete the file to resume)
echo halt > kill.txt
```

Telegram alerts (trade open/close, DD halt, kill switch) activate when
`TG_BOT_TOKEN` / `TG_CHAT_ID` are set in `.env`. The per-day journal
(markdown + JSONL) is the trade record; the v1 web dashboard was burned in the
reset ([09](09-dashboard.md)).

**Daily review ritual:** check overnight trades in the journal, confirm no DD
halt / kill fired, spot-check one trade's reasoning against the routed cell.

---

## 08.6 MT5 chart overlay EA (historical)

`mt5/TradingPartner_Overlay.mq5` visualised the v1 agent's analysis (LZI zones,
FVGs, fibs) by reading `agent_drawings.json`, which the burned v1
`chart_drawer.py` produced. **The current agent does not write that file**, so
the EA is inert — kept in-tree for reference only.
