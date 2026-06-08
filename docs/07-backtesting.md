# 07 — Backtesting

> Part of the numbered docs — start at [00 — Overview](00-overview.md). Two
> backtesters live here: the **standard portfolio backtest** (07.1) for the
> anticipation strategy stack, and the **learning backtest** (07.2) that mirrors the
> live reaction + sizing + memory loop over history.

---

## 07.0 Data sources

All backtests read `data/parquet/<SYMBOL>_<TF>.parquet`. Three feeds converge there:

| Source | Free | History | Quality | When to use |
|--------|------|---------|---------|-------------|
| **Dukascopy** | yes | 2003+ | broker-grade | Default for backtesting on Mac |
| **MT5 export (Exness)** | yes | as deep as the Exness server | broker-exact | Closest to live; do once you have an Exness account |
| **yfinance** | yes | 5y D1 / 730d intraday | retail-grade | Quick smoke test only |

```bash
# Dukascopy (recommended) — bid candles across D1/H4/H1/M15
python scripts/download_data.py --symbol EURUSD --years 5 --source dukascopy --timeframes M5 M15 H1 H4 D1

# MT5 CSV export (View → History Center → Export, one CSV per TF)
python scripts/import_csv.py path/to/EURUSD_H1.csv --symbol EURUSD --timeframe H1

# yfinance (fallback; 730-day intraday cap)
python scripts/download_data.py --symbol EURUSD --years 5 --source yfinance --timeframes D1
```

Dukascopy and Exness mids sit within ~0.1 pip in liquid hours; since our stops are
30+ pips structural and the backtester models its own spread + slippage, the source
doesn't matter for entry/exit simulation. Switch to MT5-exported Exness data only if
you build an M15-or-tighter strategy.

---

## 07.1 Standard portfolio backtest

**Code:** `agent/backtest/` (`engine.py`, `multi_tf.py`, `walkforward.py`,
`metrics.py`). Runner: `scripts/run_multitf.py` (single-TF: `scripts/run_backtest.py`).

`run_multitf.py` runs each timeframe independently and merges trades into a single
**one-position-at-a-time** portfolio with spread/commission/slippage and breakeven
management.

```bash
python scripts/run_multitf.py --use-cache-only --tfs M15 H1 H4 D1 --analyze-losses
```

Useful flags:

- `--journal` / `--reset-journal` — write every signal/trade/skip to SQLite.
- `--start-date YYYY-MM-DD` — **critical for out-of-sample validation** (only score
  bars the model never trained on).
- `--htf-bias advisory|strict` — D1 trend filtering.
- `--scorer-path PATH --score-threshold 0.55` — plug in a trained ML scorer.
- `--bias-only-tfs H4 D1` — higher TFs provide context only, no entries.

### Single-TF gate check

```bash
python scripts/check_gate.py --timeframe D1 --use-cache-only
```

Pass criteria (in `backtest_gate`, `config/default.yaml`): profit factor ≥ 1.3, max
drawdown ≤ 20%, ≥ 100 trades.

### Recommended OOS validation

```bash
python scripts/run_multitf.py --use-cache-only \
  --tfs M15 H1 H4 D1 --htf-bias advisory \
  --journal --reset-journal \
  --start-date 2024-10-28 \
  --scorer-path models/scorer_EURUSD_D1.joblib
```

`--start-date` guarantees the scorer only sees bars unseen in training — the honest
numbers you can expect on fresh data.

### Loss diagnostics

```bash
python scripts/analyze_losses.py --timeframe D1 --use-cache-only
```

Categorises every loser as `spike_out`, `reversal`, `stopped_on_retrace`, or
`never_worked`.

### Headline OOS performance (2024–2026)

| Metric | Value |
|--------|-------|
| Trades | 92 |
| Win rate | 33.7% |
| Profit factor | 1.12 |
| Sharpe | 0.72 |
| Max drawdown | 13.1% |
| Return | +10.4% ($100 → $110.40) |
| Avg R:R (LZI) | 4.37:1 |

Best days are Monday/Tuesday; Thursday/Friday are caution days (elevated threshold).
The development trajectory was v6 −37.6% → v7 −9.6% → v8 +10.4%.

---

## 07.2 Learning backtest

**Code:** `scripts/run_learning_backtest.py`.

This mirrors the **live** agent over history: the reaction engine
([04](04-reaction-engine.md)) drives entries, the `PositionSizer`
([05](05-position-sizing-and-risk.md)) sizes by risk % of the *current* equity
(conviction-scaled — a leverage mindset, not fixed lots), and the performance memory
([06](06-learning-journal.md)) updates trade-by-trade so **each day's results feed
the next day's conviction.**

```bash
PYTHONPATH=. .venv/bin/python scripts/run_learning_backtest.py \
    --years 2 --start-balance 100 --leverage 1000 --reset
```

It writes the full enriched layer day-by-day into `data/journal/backtest/` (distinct
from the live logs): per-trade attribution + counterfactual, declined setups **with
would-have outcomes**, and a daily roll-up with conviction calibration + the
anticipated-vs-reactive scorecard. The printed summary includes the equity curve, a
per-signature expectancy table, an attribution breakdown, a calibration verdict, and
a declined-setups total ("would have won: N") — the over-strict-filter signal.

Useful flags: `--max-bars N` (faster smoke runs), `--risk-min/--risk-max`,
`--max-hold` (time-stop in bars), `--decline-lookahead N` (bars to score a declined
setup's would-have outcome), `--timeframe`.

See [06 — Learning Journal](06-learning-journal.md) for how to read every field these
backtests produce.
