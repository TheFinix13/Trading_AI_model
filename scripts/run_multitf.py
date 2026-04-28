"""Multi-timeframe backtest. Runs the strategy across {M5, M15, H1, H4, D1} simultaneously
and aggregates trades into a single one-position-at-a-time portfolio.

This is the realistic test: the bot in production would watch all enabled TFs and open
the first valid setup it sees. Higher TFs add macro context, lower TFs add frequency.

Usage:
  python scripts/run_multitf.py --use-cache-only
  python scripts/run_multitf.py --tfs M5 M15 H1 H4 D1 --years 5
  python scripts/run_multitf.py --analyze-losses
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

from agent.analysis.losses import analyze, format_report
from agent.backtest.metrics import compute_metrics
from agent.backtest.multi_tf import run_multi_tf
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.journal.db import Journal
from agent.model.scorer import SetupScorer
from agent.types import Bar, Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run_multitf")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--tfs", nargs="+", default=["M15", "H1", "H4", "D1"],
                        help="timeframes to run; M5 added when its data is cached")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--use-cache-only", action="store_true")
    parser.add_argument("--analyze-losses", action="store_true",
                        help="print loss diagnostics on the merged trade stream")
    parser.add_argument("--initial-balance", type=float, default=None)
    parser.add_argument("--journal", action="store_true",
                        help="write every signal/trade/skip to the SQLite journal "
                             "for later querying with scripts/journal_query.py")
    parser.add_argument("--journal-path", type=str, default=None,
                        help="custom journal DB path (default: cfg.journal_db)")
    parser.add_argument("--reset-journal", action="store_true",
                        help="delete and recreate the journal DB before this run")
    parser.add_argument("--htf-bias", choices=["off", "advisory", "strict"], default=None,
                        help="override config: 'strict' filters LTF setups against D1/H4 trend; "
                             "'advisory' just tags them so the ML model can learn from them")
    parser.add_argument("--block-days", nargs="*", default=None,
                        help="day names to block from trading (e.g. --block-days Wed Fri). "
                             "Useful after journal analysis identifies bad days.")
    parser.add_argument("--scorer-path", type=str, default=None,
                        help="path to a trained SetupScorer (joblib). When supplied, only "
                             "setups with predicted probability >= --score-threshold are taken.")
    parser.add_argument("--score-threshold", type=float, default=0.55,
                        help="min predicted probability to take a setup (used with --scorer-path)")
    args = parser.parse_args()

    cfg = load_config()
    if args.initial_balance is not None:
        cfg.backtest.initial_balance = args.initial_balance
    if args.htf_bias is not None:
        cfg.rules.htf_bias_mode = args.htf_bias
        log.info("HTF bias mode override: %s", args.htf_bias)
    if args.block_days is not None:
        cfg.session.no_trade_days = args.block_days
        log.info("Blocking trading on: %s", args.block_days)
    symbol = args.symbol or cfg.symbol
    loader = BarLoader(cache_root=cfg.data_dir)

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.years * 365)

    bars_by_tf: dict[Timeframe, list[Bar]] = {}
    for tf_str in args.tfs:
        try:
            tf = Timeframe(tf_str)
        except ValueError:
            log.warning("Skipping unknown timeframe: %s", tf_str)
            continue

        if args.use_cache_only:
            df = loader.cache.load(symbol, tf)
        else:
            df = loader.get(symbol, tf, start, end)
            if df.empty:
                df = loader.cache.load(symbol, tf)

        if df.empty:
            log.warning("No data cached for %s %s; skipping", symbol, tf.value)
            continue

        bars = df_to_bars(df, tf)
        log.info("Loaded %d bars %s %s", len(bars), symbol, tf.value)
        bars_by_tf[tf] = bars

    if not bars_by_tf:
        log.error("No data loaded for any timeframe")
        sys.exit(1)

    journal = None
    if args.journal:
        journal_path = args.journal_path or cfg.journal_db
        if args.reset_journal:
            from pathlib import Path as _Path
            _p = _Path(journal_path)
            if _p.exists():
                _p.unlink()
                log.info("Reset journal at %s", journal_path)
        journal = Journal(journal_path)
        log.info("Journaling enabled: %s", journal_path)

    scorer = None
    if args.scorer_path:
        scorer = SetupScorer.load(args.scorer_path)
        log.info("Loaded scorer from %s (threshold=%.2f)", args.scorer_path, args.score_threshold)

    result = run_multi_tf(cfg, bars_by_tf, journal=journal,
                           scorer=scorer, score_threshold=args.score_threshold)

    print()
    print("MULTI-TIMEFRAME BACKTEST")
    print("=" * 60)
    for tf_value, trades in result.per_tf_trades.items():
        n_win = sum(1 for t in trades if t.pnl > 0)
        n_loss = len(trades) - n_win
        wr = (100 * n_win / len(trades)) if trades else 0.0
        pnl = sum(t.pnl for t in trades)
        print(f"  {tf_value:>4s}: {len(trades):4d} trades  W:{n_win:3d} L:{n_loss:3d}  "
              f"({wr:5.1f}% win)  pnl=${pnl:+.2f}")

    print()
    print("MERGED PORTFOLIO (one position at a time, chronological)")
    print("-" * 60)
    m = result.metrics
    print(f"# trades        : {m.n_trades}")
    print(f"Win rate        : {m.win_rate*100:.1f}%")
    print(f"Profit factor   : {m.profit_factor:.2f}")
    print(f"Expectancy/trade: ${m.expectancy:.2f}")
    print(f"Max drawdown    : {m.max_drawdown_pct*100:.1f}%")
    print(f"Total return    : {m.total_return_pct*100:.1f}%")
    print(f"Final balance   : ${m.final_balance:.2f} (start ${result.initial_balance:.2f})")
    print(f"Sharpe          : {m.sharpe:.2f}")

    gate = cfg.backtest_gate
    print()
    print("GATE CHECKS")
    print("-" * 60)
    checks = {
        f"profit_factor>={gate.profit_factor_min}": m.profit_factor >= gate.profit_factor_min,
        f"max_dd<={gate.max_dd_pct*100:.0f}%": m.max_drawdown_pct <= gate.max_dd_pct,
        f"n_trades>={gate.min_trades}": m.n_trades >= gate.min_trades,
    }
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    if args.analyze_losses:
        print()
        print(format_report(analyze(result.trades, n_worst=15)))


if __name__ == "__main__":
    main()
