# Quickstart

This is the shortest path from a fresh checkout to running the agent.

## 0. Requirements

- Python 3.11
- macOS for development is fine; **Windows required for paper/live runs** (MT5 limitation)
- An Exness demo account (free, takes 2 min on `exness.com`)

## 1. Install

```bash
git clone <this repo> eurusd-ai-agent
cd eurusd-ai-agent
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
# Add MT5 (Windows only):
# pip install -e ".[dev,mt5]"
```

Copy the env template:

```bash
cp .env.example .env
# Edit .env and set MT5_LOGIN/PASSWORD/SERVER once you have a demo account
```

## 2. Smoke test (works offline, no network needed)

```bash
python scripts/smoke_test.py
```

Confirms detectors → rules → backtester → ML training → journal all wire correctly.

## 3. Download historical data

```bash
python scripts/download_data.py --symbol EURUSD --years 5
```

This uses MT5 if available (Windows), else falls back to yfinance. Bars are cached in
`data/parquet/`.

## 4. Run the rules-only backtest

```bash
python scripts/run_backtest.py --rules-only
```

Shows trades, win rate, profit factor, max DD. **Goal:** positive expectancy across 5
years of EURUSD.

## 5. Strict gate

```bash
python scripts/check_gate.py
```

Returns exit 0 only if all gate criteria pass:
- profit factor >= 1.3
- max drawdown <= 20%
- >= 100 trades
- out-of-sample year profitable
- both trending and ranging years profitable

If it fails, **iterate on the rules in `agent/rules/engine.py`** and `config/default.yaml`
until it passes. Do not move to ML or paper trading until this passes.

## 6. Train the ML scorer

```bash
python scripts/train_model.py
python scripts/check_gate.py --use-ml
```

This trains XGBoost on the labeled trades from the rules-only backtest, registers the
model in the journal as the active scorer, and re-runs the gate with ML on (using
walk-forward).

## 7. Compare rules-only vs rules+ML

```bash
python scripts/run_backtest.py --compare
```

Output shows both side by side. **Keep ML only if it adds expectancy without inflating
drawdown.** If ML hurts, revert to rules-only.

## 8. Visual sanity (optional but recommended)

```bash
python scripts/visual_sanity.py --timeframe D1 --days 180
open reports/sanity_check.png
```

Compare against your hand-drawn analysis. The detectors should mostly find the same
zones, FVGs, BOSes, fibs, and trendlines. If they wildly disagree, fix the detectors.

## 9. Paper trading on Exness demo

(Requires Windows.)

1. Open MT5 (Exness build), log into your demo account, leave it running.
2. In `.env`: `AGENT_MODE=paper`, MT5 credentials set.
3. Open one terminal:
   ```powershell
   python scripts\run_live.py
   ```
4. Open another for the dashboard:
   ```powershell
   uvicorn agent.dashboard.app:app --port 8000
   ```
5. Visit `http://localhost:8000`.

## 10. Going live

**Only after** the demo phase gate is met (account $1,000, max DD <= 25%, no single trade
> 15% of profit, >= 200 trades).

Then:
1. Switch MT5 terminal login to live account.
2. `.env`: `AGENT_MODE=live`.
3. Same `run_live.py`.

The agent will use the same code path, but with real money. The 0.01-lot hard cap stays
on until the live account reaches $300.

## 11. Weekly retraining

Schedule `python scripts/weekly_retrain.py` to run every Sunday 22:00 UTC. See
`docs/deployment.md` for Windows Task Scheduler instructions.

## 12. Kill switch

If anything looks wrong, halt the bot immediately:

```bash
touch kill_switch
```

Or click "Kill switch" in the dashboard. Resume:

```bash
rm kill_switch
```
