"""Synthetic OHLCV generator for offline tests / CI smoke runs.

Produces a realistic-ish EURUSD-style price series with mean reversion + occasional impulses
so the rule engine has structures to find. NEVER use this for actual decisions; it's only for
plumbing tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from agent.types import Timeframe


def generate(
    symbol: str = "EURUSD",
    timeframe: Timeframe = Timeframe.H1,
    n_bars: int = 5000,
    seed: int = 42,
    start: datetime | None = None,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if start is None:
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)

    minutes = timeframe.minutes
    times = [start + timedelta(minutes=minutes * i) for i in range(n_bars)]

    base = 1.10
    drift = 0.0
    price = base
    closes = []
    highs = []
    lows = []
    opens = []
    vols = []

    for i in range(n_bars):
        # Slow regime drift
        if i % 500 == 0:
            drift = rng.normal(0, 0.00002)
        # Occasional impulse bars
        impulse = 0.0
        if rng.random() < 0.003:
            impulse = rng.choice([-1, 1]) * rng.uniform(0.0030, 0.0080)
        step = rng.normal(drift, 0.0007) + impulse - 0.05 * (price - base) * 0.001

        o = price
        c = price + step
        wick_up = abs(rng.normal(0, 0.0005))
        wick_dn = abs(rng.normal(0, 0.0005))
        h = max(o, c) + wick_up
        lo = min(o, c) - wick_dn
        v = max(rng.normal(1000, 200), 100)

        opens.append(o)
        highs.append(h)
        lows.append(lo)
        closes.append(c)
        vols.append(v)
        price = c

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=pd.DatetimeIndex(times, tz="UTC", name="time"),
    )
    return df
