# EURUSD AI Trading Agent

A self-learning AI trading agent for **EURUSD on Exness MT5** that codifies a personal
discretionary trading style — **supply/demand zones with break-of-structure confirmation,
support/resistance trendlines, Fair Value Gaps, Fibonacci 50/61.8 retracements, and
liquidity wicks** — into a fully audited, backtestable, ML-augmented system.

The system is designed to take a $100 demo account to $1,000 before any live capital
is risked. It is **not** a black box: every trade it takes can be opened up and
explained in plain English, with the exact confluences, market state at entry, ML
scoring rationale, and outcome.

---

## Table of contents

1. [Trading philosophy](#trading-philosophy)
2. [System architecture](#system-architecture)
3. [Installation](#installation)
4. [Quick start](#quick-start)
5. [Data sources](#data-sources)
6. [Running backtests](#running-backtests)
7. [Trade journal & explainability](#trade-journal--explainability)
8. [The ML layer](#the-ml-layer)
9. [Anti-hallucination defenses](#anti-hallucination-defenses)
10. [Web dashboard](#web-dashboard)
11. [Going live (paper → demo → live)](#going-live)
12. [Project structure](#project-structure)
13. [Risk management](#risk-management)
14. [FAQ / common errors](#faq)

---

## Trading philosophy

Every entry must satisfy **at least one supply/demand zone** plus an additional
confluence (break of structure, FVG, fib level, trendline, or liquidity wick). The
system is designed to wait for the kind of multi-signal area that a human top-down
trader would identify, and only then commit risk.

| Confluence | What it means | Where it's detected |
|---|---|---|
| **Zone (S/D)** | Fresh demand/supply zone formed by a strong impulse leg, retested by price | `agent/detectors/zones.py` |
| **BOS** | Break of recent swing high/low confirming directional bias | `agent/detectors/bos.py` |
| **FVG** | Fair Value Gap — three-bar imbalance unfilled by price | `agent/detectors/fvg.py` |
| **Fib** | Price tagging the 38.2 / 50 / 61.8 / 78.6% retracement of the most recent swing | `agent/detectors/fib.py` |
| **Trendline** | Diagonal line connecting recent swings, currently being tested | `agent/detectors/trendlines.py` |
| **Liquidity wick** | Long-wick candle that grabbed liquidity beyond a recent swing | `agent/detectors/liquidity.py` |

On top of this, the system supports **higher-timeframe (HTF) bias filtering** — when
trading M15/H1 setups, it can require alignment with D1 EMA20 trend direction, exactly
how top-down analysis works in practice.

---

## System architecture

```
                ┌──────────────────────────────────────────────────────┐
                │                  Bar data feed                        │
                │   (MT5 / Dukascopy / yfinance / CSV import)           │
                └────────────────────┬─────────────────────────────────┘
                                     │
                                     ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                         Detectors                                  │
   │   zones · BOS · FVG · fib · trendlines · liquidity wicks · ATR    │
   └────────────────────┬───────────────────────────────────────────┬─┘
                        │                                           │
                        ▼                                           ▼
                ┌────────────────┐                      ┌──────────────────────┐
                │   Rule engine  │                      │ HTF bias computer    │
                │   (confluence) │◄─────────────────────┤ (D1/H4 trend+zones)  │
                └────────┬───────┘                      └──────────────────────┘
                         │ Setup
                         ▼
                ┌────────────────┐    ┌───────────────────────────────────┐
                │   ML scorer    │    │ Pattern discoverer (alternative)  │
                │ (rule features │    │  XGBoost/sklearn on raw bar       │
                │  → win prob)   │    │  features. Calibrated.            │
                └────────┬───────┘    └───────────────────────────────────┘
                         │ score
                         ▼
                ┌────────────────┐
                │  Risk manager  │  pct_target/pct_floor sizing, daily DD halt,
                │                │  no-trade days/windows, max-positions
                └────────┬───────┘
                         │ approved order
                         ▼
                ┌────────────────────────────────────────┐
                │  Backtester  /  Live executor (MT5)    │
                │  → Journal (SQLite) every signal/trade │
                └────────────────────────────────────────┘
                         │
                         ▼
                ┌────────────────────────────────────────┐
                │ FastAPI dashboard + journal CLI        │
                │  /trade/{id} narrative · explain.py    │
                └────────────────────────────────────────┘
```

**Two ML paths:**
- **Setup scorer** (`agent/model/scorer.py`) — ranks rule-engine setups by win
  probability. Trained on labeled (features, win/loss) pairs from a no-scorer
  backtest. The reliable layer.
- **Pattern discoverer** (`agent/model/discoverer.py`) — learns its own patterns
  from raw bar features (returns, ATR, RSI, EMAs, candle morphology, time-of-day).
  Independent signal generator. The exploratory layer.

Both wrap gradient-boosted classifiers with **isotonic probability calibration**
so predicted probabilities actually match observed win rates.

---

## Installation

Requires **Python 3.11**.

```bash
# Clone and enter the project
git clone <your-repo-url> eurusd-ai-agent
cd eurusd-ai-agent

# Set up the virtual environment
python3.11 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# Install in editable mode with dev tools
pip install -e ".[dev]"

# Optional: enable MetaTrader5 (Windows only)
pip install -e ".[mt5]"
```

The default ML backend is scikit-learn (no native dependencies). If you want
XGBoost on macOS, install libomp first:

```bash
# macOS (one-time)
brew install libomp
```

---

## Quick start

```bash
# 1. Download 5 years of EURUSD history (multiple TFs) from Dukascopy
python scripts/download_data.py --symbol EURUSD --years 5 \
    --source dukascopy --timeframes M5 M15 H1 H4 D1

# 2. Run a multi-timeframe backtest with journaling
python scripts/run_multitf.py --use-cache-only --journal --reset-journal \
    --tfs M15 H1 H4 D1 --analyze-losses

# 3. Train the ML scorer on D1 (where the rules-based edge actually lives)
python scripts/train_scorer.py --tf D1 --use-cache-only --threshold 0.55

# 4. Re-run the backtest WITH the scorer
python scripts/run_multitf.py --use-cache-only --tfs D1 \
    --scorer-path models/scorer_EURUSD_D1.joblib --journal --reset-journal

# 5. Open the dashboard to inspect every trade
uvicorn agent.dashboard.app:app --reload
# → http://localhost:8000
```

---

## Data sources

| Source | Pros | Cons | When to use |
|---|---|---|---|
| **Dukascopy** | Broker-grade, free, deep history (10+ years), all TFs | Slower download | Primary source for backtesting |
| **MetaTrader5** | Matches what the live agent will see | Windows-only, requires terminal running | Match live execution conditions |
| **yfinance** | Easy, no setup | 730-day cap on intraday TFs, FX feed is rough | Quick experiments only |
| **CSV import** | Use any broker's exported history | Manual export step | When MT5 history isn't accessible |

```bash
# Dukascopy (recommended)
python scripts/download_data.py --source dukascopy --years 5 --timeframes M5 M15 H1 H4 D1

# MT5 CSV export
python scripts/import_csv.py --file MyExport.csv --symbol EURUSD --timeframe H1

# yfinance (only D1 reliably gives 5+ years)
python scripts/download_data.py --source yfinance --years 5 --timeframes D1
```

---

## Running backtests

### Single-TF gate check

```bash
python scripts/check_gate.py --timeframe D1 --use-cache-only
```

Pass criteria are configured under `backtest_gate` in `config/default.yaml`:
profit factor ≥ 1.3, max drawdown ≤ 20%, ≥ 100 trades.

### Multi-TF (recommended)

Runs each TF independently and merges trades into a single one-position-at-a-time
portfolio.

```bash
python scripts/run_multitf.py --use-cache-only --tfs M15 H1 H4 D1 --analyze-losses
```

Useful flags:
- `--journal` writes every signal/trade/skip to SQLite for inspection
- `--start-date YYYY-MM-DD` runs only on bars from that date onward — **critical for
  out-of-sample validation** when a scorer was trained on earlier data
- `--htf-bias strict` rejects LTF setups against D1 trend
- `--block-days Wed Fri` blocks specific weekdays the journal flagged as bad
- `--scorer-path PATH --score-threshold 0.55` plugs in a trained ML scorer
- `--bias-only-tfs H4 D1` marks higher TFs as bias-providing only (no entries)

### Recommended OOS validation

After training the scorer on data ending 2024-10-27, run a leakage-free check:

```bash
python scripts/run_multitf.py --use-cache-only \
  --tfs M15 H1 H4 D1 \
  --htf-bias advisory \
  --journal --reset-journal \
  --start-date 2024-10-28 \
  --scorer-path models/scorer_EURUSD_D1.joblib
```

The `--start-date` flag ensures the scorer is only applied to bars it has never seen
during training. Numbers reported by this run are the honest performance you can expect
on fresh data — typically lower than in-sample numbers. **The H4 timeframe is bias-only
by default** (entries come from M15/H1, with H4 supplying top-down trend context),
matching the workflow most discretionary traders actually use.

### Loss diagnostics

```bash
python scripts/analyze_losses.py --timeframe D1 --use-cache-only
```

Categorises every loser into one of:
- `spike_out` — went strongly favorable, then reversed same-bar to hit stop
- `reversal` — went mildly favorable, then reversed
- `stopped_on_retrace` — barely moved up, stopped on the way down
- `never_worked` — never moved in our favor at all

---

## Trade journal & explainability

Every backtest run with `--journal` writes a queryable SQLite database
(`journal.db` by default).

### Query CLI

```bash
# Last 20 trades
python scripts/journal_query.py --last 20

# Group losses by hour-of-day
python scripts/journal_query.py --losers --by hour

# Group all trades by day-of-week (this is how Wed was identified as a problem)
python scripts/journal_query.py --last 1000 --by day

# Full narrative for a specific trade
python scripts/journal_query.py --explain 14

# Why was this signal rejected?
python scripts/journal_query.py --skipped --reason skip_risk_too_high
```

### Explainer CLI

```bash
# Explain by journal id
python scripts/explain.py --trade-id 14

# Re-run rule engine at a specific timestamp to see what fired
python scripts/explain.py --replay --time 2025-04-05T14:00 --tf H1
```

### Web dashboard

Each trade row on the dashboard is clickable → `/trade/{id}` shows the full plain-English
narrative, confluences highlighted, top features at entry, MAE/MFE, and outcome.

---

## The ML layer

### Setup scorer (recommended)

```bash
python scripts/train_scorer.py --tf D1 --use-cache-only --threshold 0.55
```

The scorer trains a calibrated XGBoost/sklearn classifier on rule-engine setups
labeled by their actual outcome. It does NOT generate signals; it RANKS them.

In testing on D1, the scorer flipped strategy performance from PF 0.92 (losing) to
PF 1.16 (winning) by filtering out the bottom-quality rule setups.

### Pattern discoverer (exploratory)

```bash
python scripts/iterate.py --tfs H1 --use-cache-only --max-iters 15
```

Walk-forward training loop:
1. Train on a sliding window
2. Evaluate on out-of-sample validation
3. **Reject champion if calibration check flags overconfidence**
4. Save winning models to `models/discoverer_*/`

In testing, the discoverer with raw-bar features alone consistently failed the
calibration check. **This is the framework working correctly** — most "AI trading
bots" never check calibration and ship overfit models confidently.

---

## Anti-hallucination defenses

The system has multiple layers preventing it from "trusting itself" wrongly:

| Defense | Where | What it does |
|---|---|---|
| Walk-forward validation | `agent/model/walkforward.py`, `iterate.py` | Trained on past, tested on never-seen future |
| Out-of-sample year holdout | `scripts/check_gate.py` | A whole year set aside, never trained on |
| Limited model capacity | `discoverer.py`, `scorer.py` | Max depth 4, 300 trees max — can't memorise |
| Isotonic probability calibration | Both ML modules | Predicted prob → observed win rate alignment |
| Brier score / ECE check | `agent/analysis/calibration.py` | Refuses to crown overconfident champions |
| Hard risk caps | `agent/risk/manager.py` | Daily DD halt, max positions, lot caps |
| Kill switch | dashboard + `agent/risk/manager.py` | Instant stop file at any time |

Run `scripts/iterate.py` and watch the `calibration LONG/SHORT` lines — if the
"hallucinating" flag is true, the model is rejected automatically.

---

## Web dashboard

```bash
uvicorn agent.dashboard.app:app --reload
```

Routes:
- `/` — overview, balance, recent trades (clickable rows), kill switch
- `/trade/{id}` — full reasoning narrative
- `/api/equity`, `/api/trades`, `/api/health` — JSON API
- `POST /api/kill`, `POST /api/resume` — kill switch toggle

---

## Going live

### Phase 1: Mac paper trading (now)

You can paper-trade on Mac using yfinance/Dukascopy as the bar feed:

```bash
python scripts/run_paper.py --tf H1 --scorer-path models/scorer_EURUSD_D1.joblib
```

This is a simulation — no real broker connection. Useful for sanity-checking the
system end-to-end.

### Phase 2: Demo account on Windows VPS

Live MT5 integration needs Windows because the `MetaTrader5` Python package only runs
on Windows. Recommended setup:

1. Get a Windows VPS (Vultr/Linode/Contabo, $10–20/mo).
2. Install Exness MT5 + open a demo account.
3. Clone the project on the VPS and `pip install -e ".[mt5]"`.
4. Set `.env`:
   ```
   MT5_ACCOUNT=...your demo number...
   MT5_PASSWORD=...
   MT5_SERVER=...your server name from MT5...
   AGENT_MODE=paper
   ```
5. Run:
   ```bash
   python scripts/run_live.py
   ```

The agent will connect, watch the configured TFs, take rule-engine setups (filtered
by the scorer if loaded), and write everything to the journal for nightly review.

**Goal**: grow the demo from $100 → $1,000 before any live capital.

### Phase 3: Live $100 account

Same setup, change `AGENT_MODE=live` and supply live MT5 credentials. The risk
manager is calibrated for $100 (3% pct_floor, lot=0.01) so the bot will size
appropriately. Daily DD halt at 3% will protect against runaway losses.

See [docs/live_trading.md](docs/live_trading.md) for the full step-by-step guide.

---

## Project structure

```
eurusd-ai-agent/
├── agent/                          # core package
│   ├── analysis/                   # explainability + diagnostics
│   │   ├── explain.py              # plain-English trade narratives + SHAP
│   │   ├── losses.py               # MAE/MFE-based loss categorisation
│   │   └── calibration.py          # Brier/ECE anti-hallucination check
│   ├── backtest/                   # event-driven backtester
│   │   ├── engine.py               # core simulator + journal hook
│   │   ├── multi_tf.py             # multi-TF aggregator
│   │   └── discoverer_runner.py    # backtest using discoverer signals
│   ├── data/                       # data loading
│   │   ├── source.py               # MT5/yfinance/Dukascopy abstraction
│   │   ├── dukascopy.py            # Dukascopy fetcher
│   │   ├── csv_import.py           # MT5 CSV → parquet cache
│   │   └── loader.py               # parquet cache + range queries
│   ├── dashboard/                  # FastAPI dashboard
│   │   ├── app.py                  # routes
│   │   └── templates/              # index.html + trade.html
│   ├── detectors/                  # one file per technical concept
│   │   ├── zones.py, bos.py, fvg.py, fib.py, trendlines.py, liquidity.py
│   │   └── atr.py, swings.py
│   ├── features/                   # feature extraction for ML
│   ├── journal/                    # SQLite audit log
│   │   └── db.py                   # signals, trades, equity, model_versions
│   ├── live/                       # MT5 broker bridge (Windows)
│   ├── model/                      # ML
│   │   ├── scorer.py               # rule-setup scorer (recommended)
│   │   ├── discoverer.py           # raw-bar pattern discoverer
│   │   └── walkforward.py          # walk-forward training utilities
│   ├── risk/                       # risk manager
│   ├── rules/                      # confluence rule engine + filters
│   │   ├── engine.py               # the brain
│   │   ├── htf_bias.py             # higher-TF trend/zone filter
│   │   └── filters.py              # session, day-of-week, no-trade windows
│   ├── config.py                   # pydantic config models
│   └── types.py                    # core domain types
├── config/
│   └── default.yaml                # tunable parameters
├── data/                           # parquet cache (gitignored)
├── docs/
│   ├── data_sources.md
│   └── live_trading.md
├── models/                         # trained scorers/discoverers (gitignored)
├── scripts/                        # CLIs
│   ├── download_data.py            # fetch bars
│   ├── import_csv.py               # import MT5 CSV
│   ├── run_multitf.py              # multi-TF backtest
│   ├── check_gate.py               # gate check on a single TF
│   ├── train_scorer.py             # train ML scorer
│   ├── iterate.py                  # walk-forward train discoverer
│   ├── analyze_losses.py           # loss diagnostics
│   ├── journal_query.py            # query SQLite trade journal
│   ├── explain.py                  # plain-English trade explainer
│   ├── run_live.py                 # live MT5 agent
│   └── run_paper.py                # paper agent (no broker)
├── tests/                          # 50+ unit tests
├── pyproject.toml
└── README.md
```

---

## Risk management

- **Per-trade risk**: 1% of equity by default. Floors to 3% on accounts < $300 so the
  minimum 0.01 lot is still tradable.
- **Daily DD halt**: stops trading when balance drops 3% below day's open.
- **Max positions**: 1 (no martingale, no scaling in).
- **Lot scaling**: $100 → 0.01 lot. $300 → 0.10 lot cap. $1000+ → 1.0 lot cap.
- **Max stop**: ATR-aware bound, optional `enforce_live_stop_cap` for tiny accounts.
- **Kill switch**: any user can write to `kill.txt` (or click in the dashboard) to
  immediately halt new trades.

All of these are configurable in `config/default.yaml`.

---

## FAQ

**Q: I get `xgboost can't load on this system` on Mac.**
A: Install libomp: `brew install libomp`. Or just don't — the system uses sklearn
by default which has no native dependencies.

**Q: My yfinance H1 download fails with a "730 days" error.**
A: Yahoo enforces a 730-day cap on intraday data. Use Dukascopy instead:
`--source dukascopy`.

**Q: The backtest finds 0 trades.**
A: Check `--use-cache-only` is pointing at actual cached data
(`ls data/parquet/`). If empty, run `download_data.py` first. The default
`rules.min_confluences` is **2** (zone + at least one other) — to be more permissive
for testing, lower it to 1 in `config/default.yaml`.

**Q: Profit factor is below 1 — strategy is losing money?**
A: Yes, the rules-only strategy without ML filtering has positive expectancy on
some TFs (D1) and negative on others (H4). The ML scorer is what tips it positive
across the board. Train one with `train_scorer.py`.

**Q: Can I trade other pairs?**
A: Yes, change `symbol: EURUSD` in `config/default.yaml`. Detector thresholds may
need re-tuning per pair (different volatility ranges).

---

## License

MIT.
