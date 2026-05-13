"""Walk-forward validation of the trading edge.

Splits the bar history into rolling train/test windows. For each window:

  1. Train scorer on bars [t0..t1)
  2. Test on bars [t1..t2) with the trained scorer + same gates as production

This gives an honest out-of-sample picture: the scorer never sees the test
window during training. If the system makes money in every fold, the edge is
robust. If it only wins in one fold, we are curve-fitting.

Usage::

    python scripts/walk_forward.py --tf H1 --threshold 0.30 --folds 3
    python scripts/walk_forward.py --tf M15 --threshold 0.40 --folds 3 --train-years 1
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent.backtest.engine import Backtester
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.model.scorer import collect_training_data, train_scorer
from agent.types import Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("walk_forward")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="H1")
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--folds", type=int, default=3,
                    help="number of walk-forward folds (each fold trains on the prior train-years)")
    ap.add_argument("--train-years", type=float, default=1.5,
                    help="years of bars used for training in each fold")
    ap.add_argument("--test-years", type=float, default=0.5,
                    help="years of bars used for testing in each fold")
    ap.add_argument("--threshold", type=float, default=0.30,
                    help="probability threshold for taking a setup at test time")
    ap.add_argument("--end-date", type=str, default=None,
                    help="anchor date (YYYY-MM-DD) for the most-recent test window. "
                         "Defaults to last bar in cache.")
    args = ap.parse_args()

    cfg = load_config()
    symbol = args.symbol or cfg.symbol
    tf = Timeframe(args.tf)

    loader = BarLoader(cache_root=cfg.data_dir)
    df = loader.cache.load(symbol, tf)
    if df.empty:
        log.error("No cached %s data; run scripts/download_data.py first", tf.value)
        sys.exit(1)
    bars = df_to_bars(df, tf)
    log.info("Loaded %d bars %s %s [%s .. %s]",
             len(bars), symbol, tf.value, bars[0].time, bars[-1].time)

    # Bars per year (approximate; varies by TF)
    if tf == Timeframe.M15:
        bars_per_year = int(252 * 24 * 4)
    elif tf == Timeframe.H1:
        bars_per_year = int(252 * 24)
    elif tf == Timeframe.H4:
        bars_per_year = int(252 * 6)
    elif tf == Timeframe.D1:
        bars_per_year = 252
    elif tf == Timeframe.M5:
        bars_per_year = int(252 * 24 * 12)
    else:
        bars_per_year = int(252 * 24 * 60)

    train_n = int(args.train_years * bars_per_year)
    test_n = int(args.test_years * bars_per_year)
    log.info("Per fold: train=%d bars (~%.1fy), test=%d bars (~%.1fy)",
             train_n, args.train_years, test_n, args.test_years)

    # Anchor at end_date or latest bar
    if args.end_date:
        end_dt = datetime.fromisoformat(args.end_date).replace(tzinfo=timezone.utc)
        anchor_idx = next((i for i, b in enumerate(bars) if b.time >= end_dt), len(bars))
    else:
        anchor_idx = len(bars)

    # Walk back: most recent test window first, then earlier folds.
    folds = []
    cursor = anchor_idx
    for f in range(args.folds):
        test_end = cursor
        test_start = test_end - test_n
        train_end = test_start
        train_start = train_end - train_n
        if train_start < 200:
            log.warning("Fold %d would need bars before history; stopping", f + 1)
            break
        folds.append((train_start, train_end, test_start, test_end))
        cursor = test_start

    folds.reverse()
    print()
    print(f"WALK-FORWARD VALIDATION  symbol={symbol}  tf={tf.value}  threshold={args.threshold}")
    print("=" * 78)
    print(f"{'fold':>4}  {'train window':<28}  {'test window':<28}  {'trades':>6}  {'PF':>5}  {'WR':>6}  {'ret%':>7}  {'DD%':>5}")
    print("-" * 78)

    overall_trades = 0
    overall_pnl = 0.0
    overall_wins = 0
    fold_results = []

    for i, (ts0, ts1, te0, te1) in enumerate(folds, start=1):
        train_bars = bars[ts0:ts1]
        test_bars = bars[te0:te1]
        train_data = collect_training_data(cfg, train_bars)
        if len(train_data) < 30:
            log.warning("Fold %d: only %d training setups; skipping", i, len(train_data))
            continue
        scorer = train_scorer(train_data, calibrate=True)

        bt = Backtester(cfg, scorer=scorer, prob_threshold=args.threshold)
        res = bt.run(test_bars)
        m = res.metrics
        overall_trades += m.n_trades
        overall_pnl += sum(t.pnl for t in res.trades)
        overall_wins += sum(1 for t in res.trades if t.pnl > 0)

        train_label = f"{train_bars[0].time.date()}..{train_bars[-1].time.date()}"
        test_label = f"{test_bars[0].time.date()}..{test_bars[-1].time.date()}"
        print(f"{i:>4}  {train_label:<28}  {test_label:<28}  "
              f"{m.n_trades:>6d}  {m.profit_factor:>5.2f}  "
              f"{m.win_rate * 100:>5.1f}%  {m.total_return_pct * 100:>+6.1f}%  "
              f"{m.max_drawdown_pct * 100:>4.1f}%")
        fold_results.append({
            "fold": i, "train": train_label, "test": test_label,
            "n_trades": m.n_trades, "pf": m.profit_factor,
            "win_rate": m.win_rate, "ret_pct": m.total_return_pct,
            "dd_pct": m.max_drawdown_pct,
        })

    print("-" * 78)
    if overall_trades > 0:
        win_rate = overall_wins / overall_trades * 100
        avg_pnl = overall_pnl / overall_trades
        print(f"{'AGG':>4}  {'(all folds combined)':<28}  {'':<28}  "
              f"{overall_trades:>6d}  {'':>5}  {win_rate:>5.1f}%  "
              f"  total_pnl=${overall_pnl:+,.0f}  avg=${avg_pnl:+.2f}/trade")
    print()

    profitable_folds = sum(1 for r in fold_results if r["ret_pct"] > 0)
    print(f"Profitable folds : {profitable_folds} / {len(fold_results)}")
    if fold_results:
        consistent = profitable_folds == len(fold_results)
        verdict = "CONSISTENT EDGE — all folds positive" if consistent \
            else "MIXED RESULTS — edge not robust across all periods" if profitable_folds >= len(fold_results) // 2 \
            else "NO EDGE — most folds lost money"
        print(f"Verdict          : {verdict}")
    print()


if __name__ == "__main__":
    main()
