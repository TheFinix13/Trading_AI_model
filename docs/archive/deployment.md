# Deployment guide

This document covers running the agent for paper or live trading. Development can happen
on macOS, but **paper and live runs require Windows** because the official MetaTrader5
Python package is Windows-only.

## Hosting options


| Option                                                  | Cost                                                 | Best for                                         |
| ------------------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------ |
| **Windows VPS** (Contabo, Vultr, AWS EC2 Windows, etc.) | $5–10/mo                                             | 24/5 paper + live runs (recommended)             |
| **macOS + CrossOver/Parallels**                         | one-time CrossOver license or Parallels subscription | Dev iteration, occasional paper runs             |
| **Local Windows PC always-on**                          | free if you have one                                 | Same as VPS, but power outages will halt the bot |


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

---

## Docker (Linux / macOS / dashboard-only)

A `Dockerfile` and `docker-compose.yml` at the repo root run the
dashboard service in isolation. This is the path for users on
non-Windows hosts who only need to view the journal / metrics --
backtests and live trading still need a host with Python (and, for
live, MetaTrader5 on Windows).

### Quick start

```bash
# Build + run.
docker compose up --build

# Open the dashboard.
open http://localhost:8000

# Tail logs.
docker compose logs -f dashboard

# Stop.
docker compose down
```

### Configuration

All runtime knobs come from environment variables (or `.env` -- compose
auto-loads `.env` in the repo root). The compose file passes through:


| Var             | Default             | Purpose                                              |
| --------------- | ------------------- | ---------------------------------------------------- |
| `AGENT_MODE`    | `backtest`          | `backtest` / `paper` / `live`                        |
| `SYMBOL`        | `EURUSD`            | Trade symbol                                         |
| `JOURNAL_DB`    | `/app/journal.db`   | SQLite trade journal                                 |
| `DATA_DIR`      | `/app/data/parquet` | Parquet bar cache                                    |
| `MODEL_DIR`     | `/app/models`       | ML scorer joblibs                                    |
| `NEWS_FEED_URL` | (unset)             | Override the FF calendar URL (optional)              |
| `TG_BOT_TOKEN`  | (unset)             | Telegram bot token (`agent.notifications.telegram`)  |
| `TG_CHAT_ID`    | (unset)             | Telegram chat ID -- required to actually send alerts |


### Volumes

The compose file mounts four host paths into the container so a
re-create doesn't wipe trade history:


| Host           | Container         | Why                                          |
| -------------- | ----------------- | -------------------------------------------- |
| `./data`       | `/app/data`       | Parquet bars + cached news calendar          |
| `./models`     | `/app/models`     | Trained scorer joblibs                       |
| `./journal.db` | `/app/journal.db` | Trade journal -- survives container rebuilds |
| `./logs`       | `/app/logs`       | App logs                                     |


For a fresh checkout, create the touch points before bringing the
stack up:

```bash
touch journal.db
mkdir -p logs models data/parquet
```

### Health check

The image ships with a `HEALTHCHECK` that hits `GET /` every 30 s. The
service is reported healthy as soon as the dashboard returns 2xx. This
integrates cleanly with `docker compose ps` and external orchestrators
(Nomad, ECS, k8s) that read the OCI health field.

### What is NOT in the image

- `MetaTrader5` (Windows-only). For live trading keep using the
Windows VPS path above.
- `whisper` / `edge-tts` (voice round-trip; see `docs/voice_roadmap.md`).
- Big DB / parquet artefacts -- mount these in.

### Telegram alerts

To enable trade-event push notifications, set `TG_BOT_TOKEN` and
`TG_CHAT_ID` in `.env` and restart the stack. The notifier lives in
`agent/notifications/telegram.py`. For one-off pings:

```bash
python scripts/notify_telegram.py "deploy complete"
python scripts/notify_telegram.py --dry-run "preview only"
python scripts/notify_telegram.py --dd-halt --account live --dd-pct 0.06
```

The notifier fails *open* -- a broken network or missing creds logs a
warning but never crashes the trading loop.

### Production hardening (next session)

- Pin the base image SHA, not just `python:3.11-slim`.
- Add a non-root user and switch to `--read-only` rootfs.
- Wire the FastAPI app to `gunicorn -k uvicorn.workers.UvicornWorker -w 2`.
- Stand up a sidecar `cron` container that nightly retrains scorers
and posts the result via Telegram.

