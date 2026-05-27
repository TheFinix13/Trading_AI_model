# Windows Deployment Guide — EURUSD AI Trading Agent

Deploy the EURUSD AI agent on a Windows machine (VMware, VPS, or native) connected
to an Exness MT5 demo account.

---

## 1. Prerequisites

| Requirement | Details |
|---|---|
| **Windows machine** | VMware Fusion/Parallels VM, Windows VPS, or native Windows 10/11 |
| **MetaTrader 5** | Installed and logged into your Exness demo account |
| **Internet connection** | Stable — the agent auto-reconnects, but frequent drops hurt fill quality |
| **Python 3.11+** | Auto-installed by the deploy script if missing |
| **Git** | Auto-installed by the deploy script if missing |

### Getting Exness demo credentials

1. Sign up at [exness.com](https://www.exness.com) (free, no deposit required for demo)
2. In **Personal Area → My Accounts**, create a new **Demo MT5** account
3. Note your **Login number**, **Password**, and **Server name** (e.g. `Exness-MT5Trial7`)
4. Download and install **MetaTrader 5** from the Exness Personal Area
5. Open MT5 and log in with those credentials — verify a EURUSD chart loads

---

## 2. Quick Start (5 minutes)

### Option A: One-liner (download and run)

Open **PowerShell as Administrator** and run:

```powershell
irm https://raw.githubusercontent.com/TheFinix13/Trading_AI_model/main/scripts/deploy_windows.ps1 | iex
```

This will:
- Install Python 3.11 and Git (if missing)
- Clone the repo to `~/Documents/Trading_AI_model`
- Create a virtual environment and install all dependencies
- Prompt you for your Exness MT5 credentials
- Test the MT5 connection
- Show next steps

### Option B: Manual clone → run script

```powershell
git clone https://github.com/TheFinix13/Trading_AI_model.git "$HOME\Documents\Trading_AI_model"
cd "$HOME\Documents\Trading_AI_model"
.\scripts\deploy_windows.ps1
```

---

## 3. Configuration

### The `.env` file

The deploy script creates this interactively. You can also edit it manually:

```env
MT5_LOGIN=12345678
MT5_PASSWORD=your_trading_password
MT5_SERVER=Exness-MT5Trial7

# Optional: path to MT5 terminal (auto-detected usually)
# MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe

# Optional: Telegram alerts
# TG_BOT_TOKEN=bot123456:ABC-DEF...
# TG_CHAT_ID=your_chat_id

# Optional: AI vision providers
# GEMINI_API_KEY=
# ANTHROPIC_API_KEY=
```

### Choosing lot size

| Account balance | Recommended lot | `--lot` flag |
|---|---|---|
| $100 | 0.01 | `--lot 0.01` |
| $300–$1,000 | 0.01–0.10 | `--lot 0.05` |
| $1,000+ | Per risk calculator | Omit `--lot` (auto) |

The agent enforces hard lot caps based on balance — it won't let you over-leverage
even if you pass a larger `--lot` value.

---

## 4. Running

### Step 1: Paper mode first (validates signals without trading)

```powershell
cd "$HOME\Documents\Trading_AI_model"
.\.venv\Scripts\Activate.ps1
python scripts/run_live.py --broker paper --timeframe H1 --lot 0.01
```

Paper mode runs the full signal detection pipeline but executes trades in-memory.
Use this to verify the agent is detecting setups correctly before risking demo money.

### Step 2: Demo mode (real demo account execution)

Make sure MetaTrader 5 is open and logged in, then:

```powershell
python scripts/run_live.py --broker mt5 --timeframe H1 --lot 0.01
```

### What to expect

- **1–3 signals per day** during London (08:00–12:00 UTC) and New York (13:00–17:00 UTC) sessions
- **No signals** during Asian session, weekends, or when the kill switch is active
- **Thursday/Friday**: elevated ML threshold (caution days) — fewer but higher-quality signals
- **Startup banner**: shows system state, connected account, loaded models, last bar time

### Command-line options

```
--broker {paper,mt5,exness}    Broker type (default: paper)
--timeframe {M15,H1,H4,D1}    Timeframe to monitor (can specify multiple)
--lot 0.01                     Fixed lot size (overrides risk calculator)
--score-threshold 0.55         ML score minimum for entry
--no-telegram                  Disable Telegram notifications
--verbose                      Debug logging
```

---

## 5. Monitoring

### Terminal output

The agent prints live signal detection to stdout:

```
2026-05-27 14:00:05 INFO     signal_loop: Setup detected on H1: long entry=1.08500 ...
2026-05-27 14:00:05 INFO     signal_loop: ML gate rejected: score=0.38 < threshold=0.55
```

### Dashboard (run on Mac or any browser)

On the Windows machine (or your Mac if it has the repo):

```powershell
python -m uvicorn agent.dashboard.app:app --host 0.0.0.0 --port 8000
```

Open `http://<windows-ip>:8000` from any browser. Shows:
- Live equity curve
- Open positions
- Trade history with full reasoning
- Signal detection log

### Telegram alerts (optional)

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather)
2. Get your chat ID via [@userinfobot](https://t.me/userinfobot)
3. Add to `.env`:
   ```
   TG_BOT_TOKEN=bot123456:ABC-DEF...
   TG_CHAT_ID=123456789
   ```
4. Restart the agent — you'll get alerts on trade open/close, breakeven moves,
   daily DD halt, and kill switch activation

### Kill switch

Three ways to halt trading immediately:

```powershell
# File-based (agent checks this every loop iteration)
echo halt > kill.txt

# Dashboard button (if running)
# Click "Kill Switch" at http://localhost:8000

# Terminal
# Press Ctrl+C
```

Delete `kill.txt` and restart the agent to resume.

---

## 6. Running 24/5 as a Windows Service

For unattended operation, use **NSSM** (Non-Sucking Service Manager):

```powershell
# Download NSSM from https://nssm.cc/download
nssm install eurusd-agent
# Path:         C:\Users\you\Documents\Trading_AI_model\.venv\Scripts\python.exe
# Arguments:    scripts\run_live.py --broker mt5 --timeframe H1 --lot 0.01
# Startup dir:  C:\Users\you\Documents\Trading_AI_model

nssm install eurusd-dashboard
# Path:         C:\Users\you\Documents\Trading_AI_model\.venv\Scripts\uvicorn.exe
# Arguments:    agent.dashboard.app:app --host 0.0.0.0 --port 8000
# Startup dir:  C:\Users\you\Documents\Trading_AI_model

# Start both
nssm start eurusd-agent
nssm start eurusd-dashboard
```

The services auto-restart on crash and survive reboots.

---

## 7. Troubleshooting

### "MT5 init failed"

The MetaTrader 5 terminal must be **open and logged in** on the same Windows machine.
The Python `MetaTrader5` package communicates with the running terminal via IPC — it
cannot work if the terminal is closed.

**Fix**: Open MetaTrader 5, log in to your Exness demo account, wait for the chart
to load, then restart the agent.

### "No signals firing"

This is **normal** outside of London (08:00–12:00 UTC) and New York (13:00–17:00 UTC)
sessions. The agent is designed to be selective — expect 1–3 signals per day maximum.

Also check:
- Is today Thursday or Friday? (caution days — higher threshold)
- Is the kill switch active? (`kill.txt` exists in the project folder)
- Are models loaded? (check the startup banner for `[!] No models found`)

### "Connection lost" / "Broker disconnected"

The agent auto-reconnects with exponential backoff (10s, 20s, 40s, ..., up to 5
attempts). If it fails all retries, it exits cleanly. NSSM will restart it automatically
if you've set it up as a service.

**If this happens frequently**: check your internet connection and MT5 terminal stability.

### "Order rejected: invalid stops"

The broker has a minimum stop distance. Increase `rules.stop_buffer_pips` in
`config/default.yaml` or use a wider timeframe (H4 instead of H1).

### "Models not found" warning

Models are trained on your data and stored in the `models/` directory. The agent works
in rules-only mode without ML models (all quality gates still apply). To train:

```powershell
python scripts/download_data.py --symbol EURUSD --years 2
python scripts/train_scorer.py
python scripts/train_lzi_scorer.py
```

---

## 8. Daily Review Ritual

Spend 5 minutes each morning:

1. **Check the dashboard** — equity curve trending up? Any anomalies?
2. **Review overnight trades** — `python scripts/journal_query.py --last 10`
3. **Check for kills** — did the kill switch or DD halt trigger?
4. **Spot-check one trade** — click through on the dashboard, verify the reasoning
   matches what you'd take manually
5. **Weekend**: run `python scripts/weekly_retrain.py` to refresh the ML scorer
   on the latest data
