# Live & Paper Trading Guide

This document walks through how to take the system from "tested in backtest" to
"making real demo trades today" to "live $100 account once the demo proves itself."

---

## The three phases

```
  ┌─────────────────────────┐    ┌──────────────────────────┐    ┌─────────────────────┐
  │ 1. Mac paper trading    │ →  │ 2. Demo on Windows VPS   │ →  │ 3. Live $100 acct   │
  │    (any data source)    │    │    (real MT5 demo $100)  │    │    (Exness MT5)     │
  └─────────────────────────┘    └──────────────────────────┘    └─────────────────────┘
       sanity-check the agent          24/5 paper trade with         only after demo hits
       end-to-end without risk         broker fills, slippage,       $1,000 (10x growth)
                                       spread, weekend gaps
```

You do **not** want to skip phase 2. The demo phase is what catches issues you can't
see in backtest: real broker spread, slippage, partial fills, weekend gaps, broker
holiday calendar, news halts, and the fact that your VPS sometimes loses connection
for 30 seconds.

---

## Phase 1 — Mac paper trading (today)

This runs the same agent loop the live system will run, but uses cached / fetched
historical bars and simulates fills in-memory. Useful for verifying the model and
configuration work end-to-end before paying for a VPS.

### One-time setup

```bash
cd ~/eurusd-ai-agent
source .venv/bin/activate

# Download fresh data
python scripts/download_data.py --symbol EURUSD --years 2 --source dukascopy \
    --timeframes M15 H1 H4 D1

# Train the scorer on D1 (the timeframe with the strongest edge)
python scripts/train_scorer.py --tf D1 --use-cache-only --threshold 0.55
```

### Run the paper agent

```bash
python scripts/run_paper.py --tf D1 --scorer-path models/scorer_EURUSD_D1.joblib
```

The agent will:
- Pull bars on a schedule (every 60s by default)
- Evaluate the rule engine + scorer at each bar close
- Open simulated trades when a setup is approved
- Write everything to the journal

Open the dashboard in another terminal to watch:

```bash
uvicorn agent.dashboard.app:app --reload --port 8000
# → http://localhost:8000
```

Each trade row is clickable and shows the full reasoning. **This is your real-time
explainability tool.**

---

## Phase 2 — Demo trading on a Windows VPS

The Python `MetaTrader5` package only works on Windows. Mac users must use a
Windows VPS for live MT5 connectivity.

### VPS choice

Cheap options that work fine for this:
- **Contabo** — €5–7/mo, 4–6 GB RAM, plenty for our agent
- **Vultr** — $6+/mo, billed hourly
- **AWS Lightsail** — $7+/mo, easiest if you're already on AWS

Choose Windows Server 2019 or 2022. 2 GB RAM minimum (4 GB recommended).

### VPS setup checklist

1. **Connect via Remote Desktop** (Mac: Microsoft Remote Desktop from the App Store)
2. **Install Python 3.11**: download from [python.org](https://www.python.org/downloads/) — check "Add to PATH"
3. **Install Git for Windows**
4. **Install Exness MT5**: download from Exness, log in to your demo account
5. **Clone this repo**:
   ```cmd
   git clone <your-repo-url>
   cd eurusd-ai-agent
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e ".[dev,mt5]"
   ```
6. **Configure `.env`** in the project root:
   ```
   MT5_ACCOUNT=12345678
   MT5_PASSWORD=your_password
   MT5_SERVER=ExnessReal-Server-Name   # exact value shown in MT5 → Tools → Options → Server
   AGENT_MODE=paper                    # 'paper' = log trades but don't actually send orders
   AGENT_SYMBOL=EURUSD
   ```
7. **Copy your trained scorer** from your Mac to the VPS via Remote Desktop's
   shared clipboard, or rerun `train_scorer.py` on the VPS.

### Start the agent

```cmd
python scripts\run_live.py
```

The agent will:
- Connect to MT5
- Subscribe to EURUSD ticks
- Build rolling bar series in-memory (or pull cached history at startup)
- Run the rule engine + scorer at each bar close
- **In `paper` mode**: log trades to the journal but don't send orders to the broker
- **In `live` mode**: place real orders via `mt5.order_send`

### Keeping it running 24/5

Two reliable approaches on Windows:

**Option A: Task Scheduler (simplest)**

1. Create a `start_agent.bat` in the project folder:
   ```bat
   @echo off
   cd /d C:\path\to\eurusd-ai-agent
   call .venv\Scripts\activate
   python scripts\run_live.py
   ```
2. Open Task Scheduler → Create Task
   - **Trigger**: At log on
   - **Action**: Run `start_agent.bat`
   - **Settings**: "If task fails, restart every 1 minute, up to 5 times"
   - **Conditions**: uncheck "Start only if AC power"

**Option B: NSSM (more robust)**

[NSSM](https://nssm.cc/) wraps any command into a Windows Service. Use this if
you want the agent to run even when nobody is logged in.

```cmd
nssm install EURUSD-Agent
# Set Path: C:\path\to\.venv\Scripts\python.exe
# Set Arguments: scripts\run_live.py
# Set Startup directory: C:\path\to\eurusd-ai-agent
nssm set EURUSD-Agent AppRestartDelay 60000
nssm start EURUSD-Agent
```

Now the agent restarts itself if it ever crashes or the VPS reboots.

### Monitoring from your Mac

- Bind the dashboard to `0.0.0.0` and open the firewall on port 8000:
  ```cmd
  uvicorn agent.dashboard.app:app --host 0.0.0.0 --port 8000
  ```
  Then visit `http://VPS_IP:8000` from your Mac.
- Or use SSH tunneling if you have OpenSSH on the VPS:
  ```bash
  ssh -L 8000:localhost:8000 user@VPS_IP
  ```

### Daily review routine

Each morning (or whenever you want to check on the bot), spend 5 minutes:

```bash
# Most recent trades — what did the bot do overnight?
python scripts/journal_query.py --last 30

# Any losses I should investigate?
python scripts/journal_query.py --losers --by hour

# Why was this signal rejected?
python scripts/journal_query.py --skipped --reason skip_risk_too_high

# Click through to the dashboard for full narratives
```

This is the loop that lets you understand and trust the bot.

---

## Phase 3 — Going live with real $100

**Only do this when the demo has proven itself**:
- Demo grew from $100 → $1,000 (10x), AND
- It happened over at least 3 months (not 3 lucky days), AND
- The ML scorer's calibration check still passes on recent data, AND
- You've actually opened a Trade in the journal explorer and understood why the bot took it.

When all four are true:

1. Open a real **$100 Exness account**.
2. Edit `.env` on the VPS:
   ```
   AGENT_MODE=live
   MT5_ACCOUNT=...your live number...
   MT5_PASSWORD=...
   MT5_SERVER=...
   ```
3. Restart the agent. It now sends real orders.
4. Check the dashboard daily. Use the kill switch (top right of dashboard or
   `touch kill.txt` from CLI) at the first sign of unexpected behaviour.

---

## Important live-trading guardrails

| Guardrail | Default | Where to change |
|---|---|---|
| Per-trade risk | 1% (3% floor under $300) | `config/default.yaml` → `risk.pct_target` |
| Daily DD halt | 3% | `risk.daily_dd_halt_pct` |
| Max positions | 1 | `risk.max_open_positions` |
| Lot caps | 0.01 / 0.10 / 1.0 by balance | `risk.lot_hard_cap_*` |
| Block bad days | none by default | `session.no_trade_days: ["Wed"]` |
| ML score threshold | 0.55 | `--score-threshold` flag or per-call |
| Kill switch file | `kill.txt` in project root | `kill_switch_file` config |

---

## Troubleshooting

**"MT5 connection failed"** — check that the MT5 terminal is running on the VPS
and you're logged in to the right account. The Python package piggybacks on the
running terminal.

**"Order rejected: invalid stops"** — the broker uses a "stop level" minimum
distance from the current price. Increase `rules.stop_buffer_pips` in config.

**"Bot stopped placing trades for 24h"** — check the journal:
`python scripts/journal_query.py --skipped --last 50` will show why every recent
signal was rejected. Common: daily DD halt fired and never reset.

**"Slippage is much worse than backtest"** — adjust `backtest.slippage_pips` to
match what you observe live, then re-run training/validation. The model may
need retraining with realistic slippage.
