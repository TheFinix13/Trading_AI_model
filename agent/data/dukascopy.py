"""Dukascopy historical data source. Free, broker-grade, deep history (back to ~2003).

Uses the official `dukascopy-python` package which fetches Dukascopy's public datafeed.
No account, no API key, no rate-limit headaches. Pulls bid candles by default.

Note: Dukascopy data is sourced from a Swiss bank's liquidity pool. It will not be
identical to Exness's feed (different LPs, different spreads), but for backtesting
zone/FVG/structure logic it's well within tolerance. Live trading uses MT5 + Exness.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from agent.data.source import DataSource
from agent.types import Timeframe

log = logging.getLogger(__name__)

_FX_PAIR_MAP: dict[str, str] = {}
_INTERVAL_MAP: dict[Timeframe, str] = {}


def _lazy_init():
    """Defer the dukascopy_python import until first use; package is optional."""
    global _FX_PAIR_MAP, _INTERVAL_MAP
    if _FX_PAIR_MAP:
        return
    import dukascopy_python
    from dukascopy_python.instruments import (
        INSTRUMENT_FX_MAJORS_EUR_USD,
        INSTRUMENT_FX_MAJORS_GBP_USD,
        INSTRUMENT_FX_MAJORS_USD_JPY,
        INSTRUMENT_FX_MAJORS_USD_CAD,
        INSTRUMENT_FX_MAJORS_USD_CHF,
        INSTRUMENT_FX_MAJORS_AUD_USD,
        INSTRUMENT_FX_MAJORS_NZD_USD,
    )
    _FX_PAIR_MAP.update({
        "EURUSD": INSTRUMENT_FX_MAJORS_EUR_USD,
        "GBPUSD": INSTRUMENT_FX_MAJORS_GBP_USD,
        "USDJPY": INSTRUMENT_FX_MAJORS_USD_JPY,
        "USDCAD": INSTRUMENT_FX_MAJORS_USD_CAD,
        "USDCHF": INSTRUMENT_FX_MAJORS_USD_CHF,
        "AUDUSD": INSTRUMENT_FX_MAJORS_AUD_USD,
        "NZDUSD": INSTRUMENT_FX_MAJORS_NZD_USD,
    })
    _INTERVAL_MAP.update({
        Timeframe.M1: dukascopy_python.INTERVAL_MIN_1,
        Timeframe.M5: dukascopy_python.INTERVAL_MIN_5,
        Timeframe.M15: dukascopy_python.INTERVAL_MIN_15,
        Timeframe.H1: dukascopy_python.INTERVAL_HOUR_1,
        Timeframe.H4: dukascopy_python.INTERVAL_HOUR_4,
        Timeframe.D1: dukascopy_python.INTERVAL_DAY_1,
    })


class DukascopySource(DataSource):
    def __init__(self, side: str = "bid"):
        try:
            import dukascopy_python  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "dukascopy-python not installed; pip install dukascopy-python"
            ) from e
        _lazy_init()
        import dukascopy_python
        self.duka = dukascopy_python
        self.side = (
            dukascopy_python.OFFER_SIDE_BID if side == "bid" else dukascopy_python.OFFER_SIDE_ASK
        )

    def fetch_bars(self, symbol, timeframe, start, end):
        instrument = _FX_PAIR_MAP.get(symbol.upper())
        if instrument is None:
            raise ValueError(f"Symbol {symbol} not mapped for Dukascopy")
        interval = _INTERVAL_MAP.get(timeframe)
        if interval is None:
            raise ValueError(f"Timeframe {timeframe} not supported by Dukascopy connector")

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        log.info("Dukascopy fetch: %s %s %s -> %s", symbol, timeframe.value, start.date(), end.date())
        df = self.duka.fetch(
            instrument=instrument,
            interval=interval,
            offer_side=self.side,
            start=start,
            end=end,
            max_retries=3,
        )
        if df is None or df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        # dukascopy-python returns columns: open, high, low, close, volume; index is datetime
        df.columns = [c.lower() for c in df.columns]
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        df.index.name = "time"
        if "volume" not in df.columns:
            df["volume"] = 0
        return df[["open", "high", "low", "close", "volume"]]
