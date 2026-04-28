"""Run a backtest and print full loss diagnostics to stdout.

Usage:
  python scripts/analyze_losses.py --timeframe H1 --use-cache-only
  python scripts/analyze_losses.py --timeframe M15 --years 3
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

from agent.analysis.losses import analyze, format_report
from agent.backtest.engine import Backtester
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.types import Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("analyze_losses")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--use-cache-only", action="store_true")
    parser.add_argument("--n-worst", type=int, default=15)
    args = parser.parse_args()

    cfg = load_config()
    symbol = args.symbol or cfg.symbol
    tf = Timeframe(args.timeframe)
    loader = BarLoader(cache_root=cfg.data_dir)

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.years * 365)

    if args.use_cache_only:
        df = loader.cache.load(symbol, tf)
    else:
        df = loader.get(symbol, tf, start, end)
        if df.empty:
            df = loader.cache.load(symbol, tf)

    if df.empty:
        log.error("No bars cached for %s %s", symbol, tf.value)
        sys.exit(1)

    bars = df_to_bars(df, tf)
    log.info("Backtest on %d bars %s %s", len(bars), symbol, tf.value)

    bt = Backtester(cfg)
    result = bt.run(bars)
    report = analyze(result.trades, n_worst=args.n_worst)

    print(format_report(report))


if __name__ == "__main__":
    main()
