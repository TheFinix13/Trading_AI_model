"""Data source abstraction. MT5 if available, yfinance as a Mac/dev fallback, parquet as cache."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from agent.types import Timeframe

log = logging.getLogger(__name__)

TF_MAP_YF = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "H1": "60m",
    "H4": "60m",  # yfinance has no 4H; we resample from 60m
    "D1": "1d",
}

TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}


class DataSource(ABC):
    @abstractmethod
    def fetch_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Return OHLCV DataFrame indexed by UTC datetime with columns [open, high, low, close, volume]."""


class MT5DataSource(DataSource):
    """Reads bars from a logged-in MetaTrader5 terminal. Windows-only in practice."""

    def __init__(self, login: str = "", password: str = "", server: str = "", path: str = ""):
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "MetaTrader5 package not available. Install on Windows or use yfinance fallback."
            ) from e
        self.mt5 = mt5
        kwargs: dict = {}
        if path:
            kwargs["path"] = path
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if login and password and server:
            if not mt5.login(int(login), password=password, server=server):
                raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
        log.info("MT5 connected, account=%s", mt5.account_info())

    def shutdown(self) -> None:
        self.mt5.shutdown()

    def _tf_to_mt5(self, tf: Timeframe):
        m = {
            Timeframe.M15: self.mt5.TIMEFRAME_M15,
            Timeframe.H1: self.mt5.TIMEFRAME_H1,
            Timeframe.H4: self.mt5.TIMEFRAME_H4,
            Timeframe.D1: self.mt5.TIMEFRAME_D1,
        }
        return m[tf]

    def fetch_bars(self, symbol, timeframe, start, end):
        rates = self.mt5.copy_rates_range(symbol, self._tf_to_mt5(timeframe), start, end)
        if rates is None or len(rates) == 0:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        df = df.rename(columns={"tick_volume": "volume"})
        return df[["open", "high", "low", "close", "volume"]]


class YFinanceDataSource(DataSource):
    """Fallback for development on Mac without MT5. Free EURUSD daily/intraday data."""

    YF_SYMBOLS = {"EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X"}

    def fetch_bars(self, symbol, timeframe, start, end):
        import yfinance as yf

        yf_symbol = self.YF_SYMBOLS.get(symbol, f"{symbol}=X")
        interval = TF_MAP_YF[timeframe.value]

        # yfinance intraday limit ~730 days; for longer history we may need daily
        if timeframe == Timeframe.D1:
            df = yf.download(yf_symbol, start=start, end=end, interval="1d", progress=False, auto_adjust=False)
        else:
            df = yf.download(yf_symbol, start=start, end=end, interval=interval, progress=False, auto_adjust=False)

        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.lower)
        df.index = pd.to_datetime(df.index, utc=True)
        df = df[["open", "high", "low", "close", "volume"]]

        if timeframe == Timeframe.H4:
            df = self._resample(df, "4h")
        return df

    @staticmethod
    def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        return df.resample(rule, label="left", closed="left").agg(agg).dropna()


class ParquetCache:
    """Local parquet cache for OHLCV bars. Keyed by (symbol, timeframe)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str, tf: Timeframe) -> Path:
        return self.root / f"{symbol}_{tf.value}.parquet"

    def load(self, symbol: str, tf: Timeframe) -> pd.DataFrame:
        p = self._path(symbol, tf)
        if not p.exists():
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return pd.read_parquet(p)

    def save(self, symbol: str, tf: Timeframe, df: pd.DataFrame) -> None:
        df.to_parquet(self._path(symbol, tf))

    def upsert(self, symbol: str, tf: Timeframe, new: pd.DataFrame) -> pd.DataFrame:
        existing = self.load(symbol, tf)
        if existing.empty:
            merged = new
        else:
            merged = pd.concat([existing, new])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        self.save(symbol, tf, merged)
        return merged


def make_source(prefer: str = "auto") -> DataSource:
    """Pick a data source.

    `prefer` selects the strategy:
      - 'auto'      (default): MT5 if available (Windows + Exness), else Dukascopy, else yfinance.
      - 'mt5':      force MT5 (raises if unavailable).
      - 'dukascopy': force Dukascopy (free, broker-grade, deep history; recommended for Mac dev).
      - 'yfinance':  force yfinance (capped 730 days intraday; use only as a last resort).
    """
    if prefer == "mt5":
        from agent.config import load_config
        cfg = load_config()
        return MT5DataSource(cfg.mt5_login, cfg.mt5_password, cfg.mt5_server, cfg.mt5_path)

    if prefer == "dukascopy":
        from agent.data.dukascopy import DukascopySource
        return DukascopySource()

    if prefer == "yfinance":
        return YFinanceDataSource()

    # auto: try in order of preference
    try:
        import MetaTrader5  # noqa: F401
        from agent.config import load_config

        cfg = load_config()
        if cfg.mt5_login or cfg.mt5_path:
            return MT5DataSource(cfg.mt5_login, cfg.mt5_password, cfg.mt5_server, cfg.mt5_path)
    except (ImportError, RuntimeError) as e:
        log.info("MT5 unavailable (%s)", e)

    try:
        from agent.data.dukascopy import DukascopySource
        return DukascopySource()
    except (ImportError, RuntimeError) as e:
        log.info("Dukascopy unavailable (%s), falling back to yfinance", e)

    return YFinanceDataSource()
