"""Trendline fitter on confirmed swings.

Bullish trendline: a line connecting the last 2+ confirmed swing lows with positive slope.
Bearish trendline: connecting last 2+ confirmed swing highs with negative slope.

``fit_trendlines`` returns the *geometry* of the line plus its anchors. Validity
(whether the line has been broken) is intentionally evaluated **per-bar** by
:func:`is_valid_at`, so callers that fit once and then check at multiple bars
cannot accidentally see the future. The legacy ``tl.valid`` field is left at its
default and is now ignored by the v2 harnesses; rely on ``is_valid_at`` instead.
"""
from __future__ import annotations

from agent.detectors.swings import detect_swings
from agent.types import Bar, Direction, Trendline


def fit_trendlines(bars: list[Bar], swing_lookback: int = 5) -> list[Trendline]:
    """Return trendline geometry. Does NOT pre-compute validity."""
    swings = detect_swings(bars, lookback=swing_lookback)
    lows = [s for s in swings if not s.is_high]
    highs = [s for s in swings if s.is_high]

    lines: list[Trendline] = []

    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if b.price > a.price:
            slope = (b.price - a.price) / max(1, b.bar_index - a.bar_index)
            intercept = a.price - slope * a.bar_index
            lines.append(Trendline(
                slope=slope, intercept=intercept, anchors=[a, b], direction=Direction.LONG,
            ))

    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if b.price < a.price:
            slope = (b.price - a.price) / max(1, b.bar_index - a.bar_index)
            intercept = a.price - slope * a.bar_index
            lines.append(Trendline(
                slope=slope, intercept=intercept, anchors=[a, b], direction=Direction.SHORT,
            ))

    return lines


def is_valid_at(
    tl: Trendline,
    bars: list[Bar],
    at_index: int,
    tolerance_pips: float = 5.0,
) -> bool:
    """Causal validity check: True iff fewer than 2 closes have broken ``tl``
    between its last anchor and ``at_index`` (inclusive). Uses no future bars."""
    tol = tolerance_pips * 0.0001
    breaks = 0
    start_idx = tl.anchors[-1].bar_index + 1
    end_idx = min(at_index, len(bars) - 1)
    for i in range(start_idx, end_idx + 1):
        line_price = tl.price_at(i)
        b = bars[i]
        if tl.direction == Direction.LONG and b.close < line_price - tol:
            breaks += 1
        elif tl.direction == Direction.SHORT and b.close > line_price + tol:
            breaks += 1
        if breaks >= 2:
            return False
    return True
