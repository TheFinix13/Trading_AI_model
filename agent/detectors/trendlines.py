"""Trendline fitter on confirmed swings.

Bullish trendline: a line connecting the last 2+ confirmed swing lows with positive slope.
Bearish trendline: connecting last 2+ confirmed swing highs with negative slope.
A trendline is invalidated by 2 closes through it."""
from __future__ import annotations

from agent.detectors.swings import detect_swings
from agent.types import Bar, Direction, Trendline


def fit_trendlines(bars: list[Bar], swing_lookback: int = 5) -> list[Trendline]:
    swings = detect_swings(bars, lookback=swing_lookback)
    lows = [s for s in swings if not s.is_high]
    highs = [s for s in swings if s.is_high]

    lines: list[Trendline] = []

    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if b.price > a.price:  # higher low: bullish trendline
            slope = (b.price - a.price) / max(1, b.bar_index - a.bar_index)
            intercept = a.price - slope * a.bar_index
            tl = Trendline(slope=slope, intercept=intercept, anchors=[a, b], direction=Direction.LONG)
            tl.valid = _validate(tl, bars)
            lines.append(tl)

    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if b.price < a.price:  # lower high: bearish trendline
            slope = (b.price - a.price) / max(1, b.bar_index - a.bar_index)
            intercept = a.price - slope * a.bar_index
            tl = Trendline(slope=slope, intercept=intercept, anchors=[a, b], direction=Direction.SHORT)
            tl.valid = _validate(tl, bars)
            lines.append(tl)

    return lines


def _validate(tl: Trendline, bars: list[Bar], tolerance_pips: float = 5.0) -> bool:
    """Trendline is invalid if 2 closes have crossed through it (with tolerance)."""
    tol = tolerance_pips * 0.0001
    breaks = 0
    start_idx = tl.anchors[-1].bar_index + 1
    for i in range(start_idx, len(bars)):
        line_price = tl.price_at(i)
        b = bars[i]
        if tl.direction == Direction.LONG and b.close < line_price - tol:
            breaks += 1
        elif tl.direction == Direction.SHORT and b.close > line_price + tol:
            breaks += 1
        if breaks >= 2:
            return False
    return True
