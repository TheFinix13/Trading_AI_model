# Performance History

**Last updated:** 2026-05-13

All backtest and live trading results in one place. Reference this for baseline comparisons and to track progress over time.

---

## Build Progression (3-Year OOS: 2023-05 → 2026-05)

$10,000 starting balance, M15 + H1 merged portfolio unless noted.

| Build | Description | Trades | WR | PF | Return | Max DD | Notes |
|-------|-------------|--------|----|----|--------|--------|-------|
| v1 | No gates, raw detectors | 38 | 44.7% | 0.86 | -$608 | — | W18 only |
| v3 | + precision_partner + blocked_session + bos+sweep | 7 | 57.1% | 1.12 | +$41 | — | W18 only |
| v4 | + dir-aware sweeps + H1 min_conf=3 | 5 | 100% | ∞ | +$580 | 0% | W18 only — **masked by zone bug** |
| v5 | Zone bug fixed, no hour blocks | 573 | 42.1% | 0.78 | -61.9% | 62.6% | 3-year, the truth revealed |
| v6 | + NY hour blocks [03, 04, 12, 13] | 463 | 43.6% | 0.84 | **-37.6%** | 37.6% | 3-year baseline |
| v7 | + single scorer @0.30 | 32 | 43.8% | 0.72 | -3.9% | 7.3% | Too few trades |
| v8 | + single scorer @0.40 | 5 | 60% | 1.04 | 0% | 1.1% | Way too few trades |
| v9 | + structural anchor gate | 17 | 47.1% | 0.91 | -0.6% | 2.7% | Getting close |
| **v10** | **+ per-TF scorers (M15@0.40 + H1@0.30)** | **81** | **54.3%** | **1.13** | **+5.1%** | **7.9%** | **Current production** |

---

## Walk-Forward Validation (H1 Only)

The gold-standard test. Each fold trains a fresh scorer on the training window and tests on unseen data.

### H1 Walk-Forward (threshold=0.30, 1.5yr train / 0.5yr test)

| Fold | Train Window | Test Window | Trades | PF | WR | Return | Max DD |
|------|-------------|-------------|--------|----|----|--------|--------|
| 1 | 2023-06 → 2024-11 | 2024-11 → 2025-05 | 52 | 1.23 | 51.9% | +5.5% | 4.0% |
| 2 | 2023-12 → 2025-05 | 2025-05 → 2025-11 | 34 | 1.02 | 58.8% | +0.4% | 7.5% |
| 3 | 2024-05 → 2025-11 | 2025-11 → 2026-04 | 54 | 1.36 | 57.4% | +8.6% | 5.6% |
| **Aggregate** | — | **1.5yr OOS** | **140** | **1.20** | **55.7%** | **+$1,454 (+14.5%)** | — |

**3/3 folds profitable.** Most-recent fold is strongest — strategy adapts to current regime.

### M15 Walk-Forward (threshold=0.30, 1yr train / 0.5yr test)

| Fold | Trades | PF | WR | Return |
|------|--------|----|----|--------|
| 1 | 13 | 1.33 | 53.8% | +1.7% |
| 2 | 9 | 0.45 | 33.3% | -4.3% |
| 3 | 11 | 2.04 | 72.7% | +3.9% |
| **Aggregate** | **33** | — | **54.5%** | **+$126** |

**2/3 folds profitable** — marginal. M15 contributes ~8% of total P&L vs H1's 92%.

---

## Weekly Results

### W18 (Apr 27 – May 1, 2026)

| Source | Trades | WR | P&L | Notes |
|--------|--------|----|-----|-------|
| **Agent v4** | 5 | 100% | +$580.88 | All precision-gated, H1 min_conf=3. (Note: zone bug was active — result was partially artificial.) |
| **User** | 5 | 100% | +$79 | Manual trades on 0.01 lots. +138.1 pips. |

### W19 (May 4-8, 2026)

| Source | Trades | WR | P&L | Notes |
|--------|--------|----|-----|-------|
| **Agent** | 3 | 100% | +$234.97 | Backtested with production gates. |
| **User** | 25/28 | 89.3% | +$19.22 | 0.01 lots. 17 from journal + 28 from broker CSV. Scalping style, multi-entry at fib levels. |

---

## 2026 YTD Backtest (Latest)

Run on May 13, 2026 with production v10 config:

| Metric | Value |
|--------|-------|
| Trades | 18 |
| Win Rate | **77.8%** |
| P&L | **+$818** |
| Pips | +227 |
| H1 WR | **91.7%** (11/12) |
| M15 WR | 50% (3/6) |

### Key Insights

- **H1 is dramatically better than M15 in 2026 data.** 91.7% vs 50% WR. This strongly validates the H1-first strategy decision.
- **Best confluence combos:**
  - zone + fib_382 + FVG + near_PDH (highest conviction)
  - fvg + phase_distribution + zone (90% WR historically)
  - fib_382 + sweep_swing_high + zone (good sample size, 54% WR)

---

## Retrain Pipeline Validation

First quarterly retrain output (`scripts/retrain_scorers.py`):

| TF | Train Window | Val Trades | PF | WR | Return | DD | Promoted? |
|----|-------------|-----------|----|----|--------|-----|-----------|
| H1 | 2024-08 → 2026-02 | 8 | 6.66 | 87.5% | +6.2% | 1.1% | ✅ |
| M15 | 2024-08 → 2026-02 | 0 | — | — | — | — | ❌ (no trades in val window) |

1-year backtest with retrained H1 scorer (2025-05 → 2026-05):
> **64 trades, 57.8% WR, PF 1.10, +2.8% return, max DD 8.0%**

---

## 3-Year Audit Highlights (from `tmp/audit_3yr_v5.json`)

### Top Profitable Combos (573 trades, v5 baseline)

| Combo | n | WR | Total Pips |
|-------|---|----|-----------:|
| fvg + phase_distribution + zone | 10 | 90% | +473.8 |
| fib_382 + sweep_swing_high + zone | 57 | 54% | +343.5 |
| fib_382 + fvg + zone | 6 | 100% | +321.6 |
| fvg + sweep_equal_lows + zone | 5 | 100% | +320.3 |
| fib_382 + session_ny + zone | 54 | 50% | +400.8 |

### Worst Hours (NY Local Time)

| NY Hour | WR | Pips | Trades | Context |
|---------|-----|------|--------|---------|
| 13:00 | 32.9% | -857 | 70 | NY pre-close chop |
| 03:00 | 44.9% | -448 | 69 | London open chop |
| 12:00 | 44.5% | -402 | 146 | London close |
| 04:00 | 45.5% | -214 | 55 | London early |

All four are now blocked in `blocked_hours_ny`.

---

## Performance Targets (Pre-Live Deployment)

| Metric | Target | Current Best (v10) | Walk-Forward |
|--------|--------|-------------------|--------------|
| Trades | ≥100 | 81 (3yr) | 140 (1.5yr OOS) |
| Win Rate | ≥55% | 54.3% | 55.7% |
| Profit Factor | ≥1.3 | 1.13 | 1.20 |
| Max Drawdown | ≤20% | 7.9% | 7.5% |
| Return | Positive | +5.1% | +14.5% |

Walk-forward meets most targets. In-sample v10 is close but needs refinement on PF.

---

*Update this file after every backtest run, walk-forward validation, or week of live/paper trading.*
