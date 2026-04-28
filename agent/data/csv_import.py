"""Import OHLCV CSVs from arbitrary sources into the parquet cache.

Supports:
  - **MT5 export** (Tools -> History Center -> Export, or a script's File.WriteCSV):
      Headers like: Date, Time, Open, High, Low, Close, Volume
      or:           DateTime, Open, High, Low, Close, Volume[, Spread]
  - **HistData.com** ASCII format (semicolon-delimited):
      YYYYMMDD HHMMSS;Open;High;Low;Close;Volume
  - **TradingView export**: time,open,high,low,close,Volume,Volume MA
  - **Generic**: any CSV with at least time, open, high, low, close columns
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from agent.data.source import ParquetCache
from agent.types import Timeframe

log = logging.getLogger(__name__)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    rename = {
        "date": "_date",
        "time": "_time",
        "datetime": "datetime",
        "timestamp": "datetime",
        "<dtyyyymmdd>": "_date",
        "<time>": "_time",
        "<open>": "open",
        "<high>": "high",
        "<low>": "low",
        "<close>": "close",
        "<vol>": "volume",
        "tickvol": "volume",
        "vol": "volume",
        "spread": "spread",
    }
    df = df.rename(columns=rename)
    return df


def _parse_datetime(df: pd.DataFrame) -> pd.DataFrame:
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    elif "_date" in df.columns and "_time" in df.columns:
        df["datetime"] = pd.to_datetime(
            df["_date"].astype(str) + " " + df["_time"].astype(str), utc=True, errors="coerce"
        )
    elif "_date" in df.columns:
        df["datetime"] = pd.to_datetime(df["_date"], utc=True, errors="coerce")
    elif "time" in df.columns:
        df["datetime"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    else:
        raise ValueError(f"Could not infer datetime column from: {list(df.columns)}")
    return df.dropna(subset=["datetime"]).set_index("datetime").sort_index()


def detect_format(path: Path) -> str:
    with open(path) as f:
        first = f.readline().strip()
    if ";" in first and " " in first.split(";")[0]:
        return "histdata"
    return "csv"


def load_csv(path: Path) -> pd.DataFrame:
    fmt = detect_format(path)
    if fmt == "histdata":
        df = pd.read_csv(
            path, sep=";", header=None,
            names=["datetime", "open", "high", "low", "close", "volume"],
        )
        df["datetime"] = pd.to_datetime(df["datetime"], format="%Y%m%d %H%M%S", utc=True, errors="coerce")
        df = df.dropna(subset=["datetime"]).set_index("datetime").sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    df = pd.read_csv(path, sep=None, engine="python")
    df = _normalize_columns(df)
    df = _parse_datetime(df)
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"CSV missing required column '{col}'; got {list(df.columns)}")
    if "volume" not in df.columns:
        df["volume"] = 0
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def import_csv_to_cache(
    path: Path | str,
    symbol: str,
    timeframe: Timeframe,
    cache_root: Path | str,
    merge: bool = True,
) -> int:
    """Read `path`, normalize, and upsert into the parquet cache.
    Returns the number of bars after merge."""
    cache = ParquetCache(Path(cache_root))
    df = load_csv(Path(path))
    log.info("Loaded %d bars from %s", len(df), path)
    if merge:
        merged = cache.upsert(symbol, timeframe, df)
    else:
        cache.save(symbol, timeframe, df)
        merged = df
    return len(merged)
