"""ATR helper for volatility-aware sizing and feature engineering."""
from __future__ import annotations

from agent.types import Bar


def atr(bars: list[Bar], period: int = 14) -> float:
    """Compute ATR over the last `period` bars (Wilder's smoothing)."""
    if len(bars) < 2:
        return 0.0
    period = min(period, len(bars) - 1)
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0.0
    return sum(trs[-period:]) / period
