# 07 — Backtesting

> ⚠️ **HISTORICAL — superseded by the v2 validation pipeline.** The backtesters
> described here (standard portfolio backtest, learning backtest, week
> simulation) and their scripts (`run_multitf.py`, `run_backtest.py`,
> `check_gate.py`, `analyze_losses.py`, `run_learning_backtest.py`,
> `simulate_week.py`) were **burned in the 2026-06-09 reset**, along with the ML
> scorers they plugged in. The "headline OOS performance" table below is the v1
> overfit result that Phase A later exposed as noise. What replaced all of this
> is the isolated-fill-model alpha backtest + ablation grid + holdout +
> walk-forward + frozen cross-pair pipeline — see
> [CHECKPOINT.md](CHECKPOINT.md) for the scripts of record. Section 07.0 (data
> sources via `scripts/download_data.py`) and the locked-split idea in 07.4
> (`EvalConfig`) remain valid; `scripts/evaluate.py` was rebuilt for v2.

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
setup's would-have outcome), `--timeframe`, `--conviction-threshold X` (the
gate-loosening sweep harness — see [05.6](05-position-sizing-and-risk.md)).

See [06 — Learning Journal](06-learning-journal.md) for how to read every field these
backtests produce.

---

## 07.3 Week simulation (human vs agent side-by-side)

**Code:** `scripts/simulate_week.py`.

Replays a single week through the **full** current stack — reaction engine, HTF
directional filter, adaptive sizing, the post-loss / no-revenge guard and the
synthetic soft stop ([05.5](05-position-sizing-and-risk.md)) — and prints it
**trade-by-trade against what the human actually did** (loaded from the broker
statement in [the week review](reviews/2026-06-01_week_review.md)). Built to answer
"given everything we now know, what would the agent have done this week?"

```bash
PYTHONPATH=. .venv/bin/python scripts/simulate_week.py \
    --start 2026-05-28 --end 2026-06-06 --start-balance 100 --leverage 1000
```

### Result — the week of May 28 → Jun 5, 2026

| | Human (actual) | Agent (this stack) |
|---|---|---|
| Net P/L | **−$50.60** | **−$5.49** |
| Trades | 11 (4 win) | 3 (0 win) |
| Stops set | 1 of 11 | 3 of 3 (every trade) |
| Biggest single loss | **−$124.00** (1.0 lot, naked) | **−$3.10** (0.01 lot, soft-stopped) |
| Max drawdown | account → $0 **twice** | 5.5% |
| Ending equity | $0 | $94.51 |

**The honest read:** the agent took roughly the *same* losing direction calls as
the human on Jun 2 and Jun 5 — but as 0.01-lot, soft-stopped **paper-cuts** instead
of account-killers. The HTF read genuinely **neutral** all week (a two-sided range
— both a double top *and* a double bottom printed), so the directional filter
correctly stayed off; this week's edge is **risk control, not direction-calling**.
That is the whole point of the post-mortem: the week was lost to risk behaviour,
and the agent fixes risk behaviour structurally.

---

## 07.4 Locked evaluation protocol (the honest out-of-sample read)

> This is the **Phase A** deliverable of the overfitting fix — see the plan of
> record in [10 — Quant Validation & Modular Overhaul](10-quant-validation-and-modular-overhaul.md).
> Every later change reports through this harness so keep/drop decisions are made
> on data we haven't fit to.

**Code:** `scripts/evaluate.py` · `agent/backtest/walkforward.py` (purged
walk-forward) · `agent/backtest/metrics.py` (`bootstrap_ci`, `Scorecard`). The
locked split lives in `EvalConfig` (`agent/config.py`).

| Piece | What it does | Why |
|-------|--------------|-----|
| **Locked split** (`eval.dev_*`, `eval.sealed_test_*`) | Dev span 2015→2025-12 for walk-forward; sealed window 2025-12→2026-06. | Decisions can't silently drift onto data we've seen. |
| **Purged walk-forward** (`embargo_days=2`) | Drops the bars straddling each train→test seam. | H1 bars are autocorrelated; without an embargo the model peeks across the seam and inflates OOS numbers. |
| **Bootstrap CIs** | Resamples trades to put a confidence interval on expectancy / PF / win-rate. | Tells **edge from noise** — kills the "100% WR over 6 trades" trap. An interval that straddles zero is not a demonstrable edge. |
| **Sealed test guard** | The 2025-12→2026-06 window is evaluated **only** with `--unseal-test`. | Looking at it burns it. We weight it lightly because recent data has been partially inspected. |

```bash
# Primary OOS read — safe to run repeatedly (never touches the sealed window):
PYTHONPATH=. .venv/bin/python scripts/evaluate.py --rules-only
PYTHONPATH=. .venv/bin/python scripts/evaluate.py            # with ML scorer (slower)

# FINAL sign-off only — burns the sealed test set:
PYTHONPATH=. .venv/bin/python scripts/evaluate.py --unseal-test
```

### Baseline read (rules-only, 36 folds, 2015→2025)

The first honest run is deliberately recorded here as the bar to beat:

| Metric | Value (95% CI) | Verdict |
|--------|----------------|---------|
| Trades | 1,900 | — |
| Expectancy / trade | +0.72 **[−4.82, +5.88]** | straddles 0 |
| Profit factor | 1.01 **[0.91, 1.12]** | straddles 1 |
| Win rate | 35.3% | — |
| Max drawdown | 20.9% | — |
| Sharpe (ann.) | 0.10 | — |
| **Overall** | | **noise — no demonstrable OOS edge** |

This is the point of Phase A: the tuned-looking backtest numbers do **not**
survive a purged, confidence-interval'd walk-forward. The modular-alpha work
(Phase B) is about finding which individual concepts *do* clear this bar.
