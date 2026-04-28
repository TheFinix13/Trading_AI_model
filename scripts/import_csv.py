"""Import an OHLCV CSV from MT5 export, HistData, TradingView, or any standard CSV.

Examples:

    # MT5: in MT5 terminal, Tools -> History Center -> Save as CSV. Then:
    python scripts/import_csv.py path/to/EURUSD_H1.csv --symbol EURUSD --timeframe H1

    # HistData.com generic ASCII (semicolon delimited):
    python scripts/import_csv.py DAT_ASCII_EURUSD_M1_2024.csv --symbol EURUSD --timeframe M15

The bars are normalized and merged into data/parquet/<SYMBOL>_<TF>.parquet.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from agent.config import load_config
from agent.data.csv_import import import_csv_to_cache
from agent.types import Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("import_csv")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=str, help="Path to the CSV file")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True,
                        choices=["M1", "M5", "M15", "H1", "H4", "D1"])
    parser.add_argument("--replace", action="store_true", help="Replace cache rather than merge")
    args = parser.parse_args()

    cfg = load_config()
    n = import_csv_to_cache(
        path=args.path,
        symbol=args.symbol.upper(),
        timeframe=Timeframe(args.timeframe),
        cache_root=cfg.data_dir,
        merge=not args.replace,
    )
    log.info("Cache for %s %s now has %d bars", args.symbol, args.timeframe, n)


if __name__ == "__main__":
    sys.exit(main())
