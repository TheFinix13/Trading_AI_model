# Exness Demo Account Setup Guide

This guide walks you through setting up your Exness demo account, configuring MT5 credentials, and running the live trading agent.

## Table of Contents
1. [Create an Exness Demo Account](#1-create-an-exness-demo-account)
2. [Get MT5 Credentials](#2-get-mt5-credentials)
3. [Configure the .env File](#3-configure-the-env-file)
4. [Running on macOS (Cross-Platform Options)](#4-running-on-macos)
5. [Start Paper Trading (Recommended First)](#5-start-paper-trading)
6. [Progression: Paper → Demo → Live](#6-progression-paper--demo--live)

---

## 1. Create an Exness Demo Account

1. Go to [Exness.com](https://www.exness.com) and register
2. Verify your email and complete basic profile
3. In the Personal Area, click **"Open New Account"**
4. Select:
   - Account type: **Standard** (or Pro for tighter spreads)
   - Platform: **MetaTrader 5**
   - Currency: **USD**
   - Leverage: **1:100** (recommended for demo)
   - **Demo** (not Real)
5. Set a password for the trading account
6. Note down the credentials shown:
   - **Login** (numeric, e.g., `12345678`)
   - **Password** (the one you set)
   - **Server** (e.g., `Exness-MT5Trial4`)

## 2. Get MT5 Credentials

Your demo account will have three pieces of information:

| Field | Example | Where to find it |
|-------|---------|------------------|
| Login | `81234567` | Personal Area → My Accounts → click the account |
| Password | `YourPass123!` | Set during account creation (or reset in PA) |
| Server | `Exness-MT5Trial4` | Shown in account details |

### Finding your server name

If you're unsure of the server:
1. Open MetaTrader 5 (on Windows/VPS)
2. File → Login to Trade Account
3. The server dropdown shows all Exness servers
4. Common demo servers: `Exness-MT5Trial`, `Exness-MT5Trial2` through `Exness-MT5Trial7`

## 3. Configure the .env File

Create or edit `.env` in the project root:

```bash
# Broker connection
MT5_LOGIN=81234567
MT5_PASSWORD=YourPass123!
MT5_SERVER=Exness-MT5Trial4
MT5_PATH=                          # Leave empty unless custom install path

# Agent mode
AGENT_MODE=paper                   # Start with paper, change to 'live' when ready

# Telegram notifications (optional but recommended)
TG_BOT_TOKEN=123456:ABC-DEF...    # From @BotFather on Telegram
TG_CHAT_ID=-1001234567890         # Your chat/group ID

# Risk overrides (optional)
RISK_PCT=0.01                      # 1% risk per trade
DAILY_DD_HALT_PCT=0.03             # 3% daily drawdown halt
```

## 4. Running on macOS

The MetaTrader5 Python package (`MetaTrader5`) **only works on Windows**. Here are your options for running on macOS:

### Option A: Paper Trading (No broker needed) ✅ Recommended to start

```bash
python scripts/run_live.py --broker paper --timeframe H1
```

This runs entirely locally using cached parquet data or yfinance. No MT5 or Windows required.

### Option B: Windows VPS ($5-10/month) ✅ Best for production

Cheapest path to a real MT5 connection:

1. **Get a Windows VPS** — Recommended providers:
   - [Contabo](https://contabo.com) — Windows VPS from $6.99/month
   - [ForexVPS.net](https://forexvps.net) — Optimized for trading, ~$20/month
   - [Vultr](https://vultr.com) — Windows Server from $24/month
   - [Amazon Lightsail](https://aws.amazon.com/lightsail/) — Windows from $12/month

2. **On the VPS, install:**
   ```powershell
   # Install Python 3.11+
   winget install Python.Python.3.11
   
   # Install MT5
   # Download from https://www.metatrader5.com/en/download
   
   # Clone your repo
   git clone https://github.com/YOUR_USER/eurusd-ai-agent.git
   cd eurusd-ai-agent
   
   # Set up venv
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   
   # Run
   python scripts/run_live.py --broker exness --timeframe H1
   ```

3. **Keep it running** with a Windows Task Scheduler or `nssm` (Non-Sucking Service Manager)

### Option C: Docker Bridge (Silicon MetaTrader5)

For Apple Silicon Macs, there's a Docker-based solution:

```bash
# Install Colima with x86_64 emulation
brew install colima
colima start --arch x86_64 --memory 4

# Use silicon-metatrader5 Docker image
# See: https://github.com/bahadirumutiscimen/silicon-metatrader5
pip install siliconmetatrader5
```

> **Note:** This has higher latency than native Windows. Fine for H1 trading, not recommended for M1/M5.

### Option D: Remote Bridge (rpyc)

Run MT5 on Windows, connect from Mac via network:

1. On Windows VPS, run an rpyc server that wraps MT5 calls
2. On Mac, connect to the rpyc server
3. This is the most complex setup — only use if you need real-time development on Mac while trading live

### Comparison

| Option | Cost | Latency | Setup Effort | Best For |
|--------|------|---------|-------------|----------|
| Paper | Free | N/A | 0 min | Development & testing |
| Windows VPS | $5-25/mo | <1ms | 30 min | Production trading |
| Docker Bridge | Free | 50-200ms | 1 hour | Apple Silicon dev |
| rpyc Bridge | $5-25/mo | 10-50ms | 2 hours | Advanced dev workflow |

## 5. Start Paper Trading

Paper trading lets you validate the full signal loop without risking money:

```bash
# Basic paper trading on H1
python scripts/run_live.py --broker paper --timeframe H1

# Paper with custom balance
python scripts/run_live.py --broker paper --balance 100 --timeframe H1

# Paper with fixed lot size
python scripts/run_live.py --broker paper --lot 0.01 --timeframe H1

# Multiple timeframes
python scripts/run_live.py --broker paper -t H1 -t M15

# Verbose logging
python scripts/run_live.py --broker paper -t H1 --verbose
```

### What to watch for in paper mode:
- Signals are detected and logged
- Risk manager approves/rejects correctly
- Position monitor moves stops to breakeven
- Telegram notifications fire (use `--no-telegram` to disable)

## 6. Progression: Paper → Demo → Live

### Phase 1: Paper Trading (1-2 weeks)
```bash
python scripts/run_live.py --broker paper --timeframe H1
```
- Validate signal quality matches backtest
- Confirm risk manager works correctly
- Test kill switch (`touch kill.txt` to halt, `rm kill.txt` to resume)
- Monitor via Telegram

### Phase 2: Exness Demo (2-4 weeks)
```bash
# On Windows VPS:
python scripts/run_live.py --broker exness --timeframe H1
```
- Real market data and execution
- Verify fills, spreads, and slippage
- Compare paper results vs demo results
- Run during London + NY sessions only

### Phase 3: Live Trading (when demo is profitable)

**Prerequisites before going live:**
- [ ] 200+ demo trades taken
- [ ] Profit factor > 1.3 on demo
- [ ] Max drawdown < 15% on demo
- [ ] Risk manager tested (daily DD halt works)
- [ ] Kill switch tested
- [ ] Telegram alerts working

```bash
# Change .env:
AGENT_MODE=live

# On Windows VPS:
python scripts/run_live.py --broker exness --timeframe H1 --lot 0.01
```

**Safety features always active:**
- Daily drawdown halt (3% default)
- Kill switch file (`kill.txt`)
- Max 1 open position
- Telegram alerts on every trade

---

## Exness API Notes

As of 2026, Exness provides several API access methods:

| API Type | Purpose | Access |
|----------|---------|--------|
| **MT5 Trading** | Execute trades, get data | Via MetaTrader5 Python package |
| **FIX API** | Low-latency institutional access | Contact account manager |
| **Partner API** | Affiliate/IB statistics | Partner dashboard |
| **Web Terminal API** | Account management | OAuth token |

For algorithmic retail trading, **MT5 is the primary interface**. The FIX API is available for high-volume professional accounts but requires coordination with Exness support.

There is no public REST API for retail trade execution — all execution goes through MT5.

---

## Troubleshooting

### "MetaTrader5 package not available"
You're on macOS/Linux. Use `--broker paper` or set up a Windows environment (see Option B/C above).

### "Login failed"
- Double-check login number (numeric only)
- Verify password (case-sensitive)
- Confirm server name matches exactly (e.g., `Exness-MT5Trial4` not `Exness-MT5Trial`)
- Ensure the demo account hasn't expired (Exness demo accounts may expire after 30 days of inactivity)

### "No tick data"
- Market might be closed (forex is closed Sat-Sun)
- Symbol might need to be added in MT5: Right-click Market Watch → Symbols → find EURUSD → Show

### Kill switch
```bash
# Emergency stop:
echo "manual halt" > kill.txt

# Resume trading:
rm kill.txt
```
