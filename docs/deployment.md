# Deployment guide

This document covers running the agent for paper or live trading. Development can happen
on macOS, but **paper and live runs require Windows** because the official MetaTrader5
Python package is Windows-only.

## Hosting options

| Option | Cost | Best for |
|--------|------|----------|
| **Windows VPS** (Contabo, Vultr, AWS EC2 Windows, etc.) | $5–10/mo | 24/5 paper + live runs (recommended) |
| **macOS + CrossOver/Parallels** | one-time CrossOver license or Parallels subscription | Dev iteration, occasional paper runs |
| **Local Windows PC always-on** | free if you have one | Same as VPS, but power outages will halt the bot |

**Recommendation:** rent a $5–10/mo Windows VPS once you reach Phase 4 (paper trading).
Reliability > cost.

## Recommended VPS providers (2026)

- **Contabo** Windows VPS S — ~$8/mo, 4 vCPU / 8 GB RAM (overkill, but cheap)
- **Vultr** Cloud Compute Windows — ~$10/mo, 1 vCPU / 2 GB RAM
- **AWS EC2 t3.small Windows** — ~$15/mo on-demand; free tier eligible for first year on micro
- **Hostwinds VPS Windows** — from $9/mo

Pick one with low latency to your Exness server's region (their MT5 servers are typically EU).

## VPS setup checklist (Windows Server 2022)

1. Install **Python 3.11** for all users from python.org. Tick "Add to PATH".
2. Install **MetaTrader 5** from the Exness Personal Area (do not use the generic MT5 from MetaQuotes; Exness's installer is preconfigured for their servers).
3. Log into your Exness demo (then later live) account inside the MT5 terminal. Verify EURUSD chart loads.
4. Clone the repo:

    ```powershell
    cd C:\
    git clone https://github.com/<you>/eurusd-ai-agent.git
    cd eurusd-ai-agent
    py -3.11 -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install -e ".[dev,mt5]"
    ```

5. Copy `.env.example` to `.env` and fill in your Exness credentials:

    ```env
    AGENT_MODE=paper
    MT5_LOGIN=12345678
    MT5_PASSWORD=...
    MT5_SERVER=Exness-MT5Trial14
    MT5_PATH=C:\Program Files\MetaTrader 5 Exness\terminal64.exe
    ```

6. Sanity check:

    ```powershell
    python -c "import MetaTrader5 as mt5; mt5.initialize(); print(mt5.account_info())"
    ```

7. Run smoke test:

    ```powershell
    python scripts\smoke_test.py
    ```

## Run the agent

### Backtest (always do this first):

```powershell
python scripts\download_data.py --symbol EURUSD --years 5
python scripts\check_gate.py
```

If the gate fails, fix rules and re-run. **Do not proceed to paper until the gate passes.**

### Train ML scorer:

```powershell
python scripts\train_model.py
python scripts\check_gate.py --use-ml
```

### Paper trading:

Set `AGENT_MODE=paper` in `.env`, then:

```powershell
python scripts\run_live.py
```

The dashboard runs separately:

```powershell
uvicorn agent.dashboard.app:app --port 8000
```

Open `http://<vps-ip>:8000`. Whitelist your IP first, or use SSH tunneling.

### Live trading:

**Only after the demo phase gate has passed** (account at $1,000 with sanity gates met).

1. Switch the MT5 terminal to your live Exness account login.
2. Update `.env`: `AGENT_MODE=live` and live credentials.
3. Restart the run loop.

## Running as a Windows service (24/5)

Use **NSSM** (Non-Sucking Service Manager) to run the agent loop and dashboard as services
that auto-restart on crash and after reboot.

```powershell
# Install NSSM from https://nssm.cc/download
nssm install eurusd-agent
# Path:        C:\eurusd-ai-agent\.venv\Scripts\python.exe
# Arguments:   scripts\run_live.py
# Startup dir: C:\eurusd-ai-agent

nssm install eurusd-dashboard
# Path:        C:\eurusd-ai-agent\.venv\Scripts\uvicorn.exe
# Arguments:   agent.dashboard.app:app --host 0.0.0.0 --port 8000
# Startup dir: C:\eurusd-ai-agent
```

## Weekly retraining

Schedule via Windows Task Scheduler:

- Trigger: weekly, Sunday 22:00 UTC
- Action: `C:\eurusd-ai-agent\.venv\Scripts\python.exe scripts\weekly_retrain.py`
- Start in: `C:\eurusd-ai-agent`

Alternative: use the `schedule` Python package inside `run_live.py` to fire the retrain
in-process — this is already wired to the journal and avoids shell setup, but means
the agent and retrainer share one Python process.

## Monitoring

- The dashboard at `http://<vps-ip>:8000` shows live equity, open positions, today's setups.
- Logs are written to `logs/agent.log` (rotating) — tail with `Get-Content -Wait`.
- Set up a Telegram bot or Discord webhook to ping you on:
  - Daily DD halt triggered
  - Order rejected by broker
  - Loss > X%
  - Demo balance milestones ($200, $500, $1,000)

A simple notifier is left as a small future improvement; the journal table makes it
trivial to add.

## Daily review ritual

Every morning during the demo phase and especially in live:

1. Open the dashboard. Check:
   - Did the kill switch trigger? Why?
   - Daily DD?
   - Open positions making sense?
2. Spot-check one trade: feature vector, model score, confluences. Does it match what you'd take by hand?
3. Equity curve trending up over rolling 30 days?
4. Any anomalies in spread/slippage vs backtest?

If the live behavior diverges materially from the demo (or the demo from the backtest),
**activate the kill switch** and investigate before resuming.

## Kill switch

Three ways to halt:

```powershell
# File-based (the bot polls this each loop)
echo halt > C:\eurusd-ai-agent\kill_switch

# Dashboard button
# Click "Kill switch" at http://<vps-ip>:8000

# Stop services
nssm stop eurusd-agent
```
