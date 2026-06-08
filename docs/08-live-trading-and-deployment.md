# 08 — Live Trading & Deployment

> Part of the numbered docs — start at [00 — Overview](00-overview.md). Run the
> agent with the modes from [04 — Reaction Engine](04-reaction-engine.md) and the
> sizing/risk controls from [05 — Position Sizing & Risk](05-position-sizing-and-risk.md).

Deploy the EURUSD agent on a Windows machine (VMware, VPS, or native) connected to an
Exness MT5 account. The live `MetaTrader5` Python package is **Windows-only**, so live
trading needs Windows; everything else (backtests, dashboard) runs anywhere.

**Progression: paper → demo → live.** Always validate signals in paper, then on a
demo account, before risking real capital. Goal: grow a $100 demo to $1,000 first.

---

## 08.1 Windows / VM setup

### Prerequisites

| Requirement | Details |
|---|---|
| **Windows machine** | VMware/Parallels VM, Windows VPS ($10–20/mo), or native Win 10/11 |
| **MetaTrader 5** | Installed and logged into your Exness account |
| **Python 3.11+** | Auto-installed by the deploy script if missing |
| **Git** | Auto-installed by the deploy script if missing |

### Quick start (PowerShell)

```powershell
# Option A — one-liner (Run PowerShell as Administrator)
irm https://raw.githubusercontent.com/TheFinix13/Trading_AI_model/main/scripts/deploy_windows.ps1 | iex

# Option B — manual clone then run
git clone https://github.com/TheFinix13/Trading_AI_model.git "$HOME\Documents\Trading_AI_model"
cd "$HOME\Documents\Trading_AI_model"
.\scripts\deploy_windows.ps1
```

The script installs Python + Git if missing, clones the repo, creates a venv,
installs dependencies, prompts for Exness credentials, and tests the MT5 connection.

### Running 24/5 as a Windows service (NSSM)

```powershell
nssm install eurusd-agent
# Path:        ...\.venv\Scripts\python.exe
# Arguments:   scripts\run_live.py --broker mt5 --timeframe H1 --mode hybrid
# Startup dir: ...\Trading_AI_model

nssm install eurusd-dashboard
# Path:        ...\.venv\Scripts\uvicorn.exe
# Arguments:   agent.dashboard.app:app --host 0.0.0.0 --port 8000

nssm start eurusd-agent; nssm start eurusd-dashboard
```

Services auto-restart on crash and survive reboots.

---

## 08.2 Exness / MT5 connection

### Get demo credentials

1. Sign up at [exness.com](https://www.exness.com) (free, no deposit for demo).
2. Personal Area → **Open New Account** → MetaTrader 5, USD, leverage 1:100, **Demo**.
3. Note the **Login** (numeric), **Password**, and **Server** (e.g. `Exness-MT5Trial7`).
4. Install MT5 from the Exness Personal Area, log in, and confirm a EURUSD chart loads.

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
python scripts/run_live.py --broker paper --timeframe H1 --mode hybrid

# Step 2 — demo execution (MT5 must be open and logged in)
python scripts/run_live.py --broker mt5 --timeframe H1 --mode hybrid \
    --risk-min 0.005 --risk-max 0.02
```

**Key flags:** `--broker {paper,mt5,exness}`, `--timeframe`, `--mode
{anticipation,reaction,hybrid}`, `--risk-min/--risk-max` (sizing band),
`--lot` (upper cap on risk-based size), `--reset-journal`, `--no-telegram`,
`--verbose`. See [04](04-reaction-engine.md) and [05](05-position-sizing-and-risk.md).

**What to expect:** 1–3 signals/day during London (08–12 UTC) and NY (13–17 UTC);
no signals in Asia, weekends, or when the kill switch is active; higher threshold on
Thu/Fri.

### Troubleshooting

- **"MT5 init failed"** — the terminal must be open and logged in on the same machine
  (the package talks to it via IPC). Open MT5, log in, wait for the chart, restart.
- **"No signals firing"** — normal outside kill zones; check Thu/Fri threshold,
  `kill.txt`, and that models loaded.
- **"Connection lost"** — the agent auto-reconnects with exponential backoff (up to 5
  tries) then exits cleanly; NSSM restarts it.
- **"Order rejected: invalid stops"** — raise `rules.stop_buffer_pips` or use a wider
  TF.

### Monitoring & kill switch

```powershell
# Dashboard (open http://<windows-ip>:8000) — see 09
python -m uvicorn agent.dashboard.app:app --host 0.0.0.0 --port 8000

# Kill switch (any one halts new trades)
echo halt > kill.txt        # file-based, checked each loop
#  ...or click "Kill Switch" in the dashboard, or Ctrl+C
```

Telegram alerts (trade open/close, breakeven, DD halt, kill switch) activate when
`TG_BOT_TOKEN` / `TG_CHAT_ID` are set in `.env`.

**Daily review ritual:** check the dashboard equity curve, review overnight trades
(`python scripts/journal_query.py --last 10`), confirm no DD halt/kill fired, and
spot-check one trade's reasoning.

---

## 08.3 MT5 chart overlay EA

**Code:** `mt5/TradingPartner_Overlay.mq5` (see `mt5/README.md`).

The EA visualises the agent's analysis directly on your MT5 chart. The Python agent
writes `MQL5/Files/agent_drawings.json`; the EA reads it every ~5 s and redraws.

**Install:** copy the `.mq5` to MT5's `MQL5/Experts` folder (File → Open Data Folder),
compile in MetaEditor (F7), drag it onto a EURUSD chart, and enable "Allow Algo
Trading".

**It draws:** purple = LZI zones, blue = FVGs, orange = supply/demand zones, red =
resistance, green = support, gold dotted = fib levels, arrows = entry signals
(green buy / red sell), and a top-left label with current HTF bias + confidence.
Toggle elements, colours, and the update interval in EA settings. When the agent
stops, the EA shows the last known state; removing the EA clears all drawings.
