"""Download historical OHLCV data for the configured symbol/timeframes.
On Mac without MT5: uses yfinance (limited intraday history but daily is multi-decade).
On Windows with MT5: pulls from the active MT5 terminal's broker history."""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone

from agent.config import load_config
from agent.data.loader import BarLoader
from agent.types import Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("download_data")

# Yahoo Finance free tier limits intraday history. These caps include a safety margin
# so the requested window is strictly inside Yahoo's allowed range (otherwise it 403s).
YEARS_INTRADAY_LIMIT = {
    Timeframe.M1: 0.02,   # ~7 days (Yahoo: 1m capped at ~7 days)
    Timeframe.M5: 0.16,   # ~58 days (Yahoo: 5m capped at ~60 days)
    Timeframe.M15: 0.16,
    Timeframe.H1: 1.95,
    Timeframe.H4: 1.95,
    Timeframe.D1: 30.0,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, help="defaults to config.symbol")
    parser.add_argument("--years", type=int, default=6)
    parser.add_argument("--timeframes", nargs="+", default=["D1", "H4", "H1", "M15"])
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--source", default="auto",
                        choices=["auto", "dukascopy", "yfinance", "mt5"],
                        help="data source: auto picks the best available, dukascopy = free broker-grade deep history (recommended)")
    args = parser.parse_args()

    cfg = load_config()
    symbol = args.symbol or cfg.symbol
    loader = BarLoader(cache_root=cfg.data_dir, prefer=args.source)

    end = datetime.now(tz=timezone.utc)

    is_yfinance = args.source == "yfinance"

    for tf_str in args.timeframes:
        tf = Timeframe(tf_str)
        if is_yfinance:
            max_years = YEARS_INTRADAY_LIMIT.get(tf, args.years)
            years = min(args.years, max_years)
        else:
            years = args.years
        start = end - timedelta(days=int(years * 365))
        log.info("Fetching %s %s from %s (~%.1f years) via %s",
                 symbol, tf.value, start.date(), years, args.source)
        df = loader.get(symbol, tf, start, end, refresh=args.refresh)
        log.info("  -> %d bars cached for %s %s", len(df), symbol, tf.value)


if __name__ == "__main__":
    main()
