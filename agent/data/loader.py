"""High-level loader: returns Bar lists for detectors, or DataFrames for vectorized ops."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from agent.data.source import DataSource, ParquetCache, make_source
from agent.types import Bar, Timeframe


def df_to_bars(df: pd.DataFrame, timeframe: Timeframe) -> list[Bar]:
    bars: list[Bar] = []
    for ts, row in df.iterrows():
        bars.append(
            Bar(
                time=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0)),
                timeframe=timeframe,
            )
        )
    return bars


class BarLoader:
    def __init__(self, cache_root: Path, source: DataSource | None = None, prefer: str = "auto"):
        self.cache = ParquetCache(cache_root)
        self.source = source
        self.prefer = prefer

    def _ensure_source(self) -> DataSource:
        if self.source is None:
            self.source = make_source(prefer=self.prefer)
        return self.source

    def get(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        refresh: bool = False,
    ) -> pd.DataFrame:
        cached = self.cache.load(symbol, timeframe)
        start_ts = pd.Timestamp(start, tz="UTC") if start.tzinfo is None else pd.Timestamp(start)
        end_ts = pd.Timestamp(end, tz="UTC") if end.tzinfo is None else pd.Timestamp(end)

        if not refresh and not cached.empty:
            if cached.index.min() <= start_ts and cached.index.max() >= end_ts:
                return cached.loc[start_ts:end_ts]

        try:
            source = self._ensure_source()
            fresh = source.fetch_bars(symbol, timeframe, start, end)
        except Exception:
            fresh = pd.DataFrame()

        if fresh.empty:
            # Source unavailable or refused. Return whatever cached overlap we have.
            if cached.empty:
                return cached
            slice_start = max(start_ts, cached.index.min())
            slice_end = min(end_ts, cached.index.max())
            if slice_start > slice_end:
                return cached  # cache is outside requested window; return all of it
            return cached.loc[slice_start:slice_end]

        merged = self.cache.upsert(symbol, timeframe, fresh)
        slice_start = max(start_ts, merged.index.min())
        slice_end = min(end_ts, merged.index.max())
        if slice_start > slice_end:
            return merged
        return merged.loc[slice_start:slice_end]

    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        refresh: bool = False,
    ) -> list[Bar]:
        df = self.get(symbol, timeframe, start, end, refresh=refresh)
        return df_to_bars(df, timeframe)
