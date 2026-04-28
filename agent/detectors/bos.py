"""Break of Structure detection.

A bullish BOS: price closes above the most recent confirmed swing high.
A bearish BOS: price closes below the most recent confirmed swing low.
We only register a NEW BOS when it represents a fresh structural break."""
from __future__ import annotations

from agent.detectors.swings import detect_swings
from agent.types import Bar, BreakOfStructure, Direction


def detect_bos(bars: list[Bar], swing_lookback: int = 5) -> list[BreakOfStructure]:
    swings = detect_swings(bars, lookback=swing_lookback)
    if not swings:
        return []

    breaks: list[BreakOfStructure] = []
    last_broken_high: float | None = None
    last_broken_low: float | None = None

    for i, bar in enumerate(bars):
        prior_highs = [s for s in swings if s.is_high and s.bar_index < i - swing_lookback]
        prior_lows = [s for s in swings if not s.is_high and s.bar_index < i - swing_lookback]

        if prior_highs:
            ref = prior_highs[-1]
            if bar.close > ref.price and (last_broken_high is None or ref.price > last_broken_high):
                breaks.append(
                    BreakOfStructure(
                        direction=Direction.LONG,
                        broken_swing_price=ref.price,
                        broken_at=bar.time,
                        broken_bar_index=i,
                    )
                )
                last_broken_high = ref.price

        if prior_lows:
            ref = prior_lows[-1]
            if bar.close < ref.price and (last_broken_low is None or ref.price < last_broken_low):
                breaks.append(
                    BreakOfStructure(
                        direction=Direction.SHORT,
                        broken_swing_price=ref.price,
                        broken_at=bar.time,
                        broken_bar_index=i,
                    )
                )
                last_broken_low = ref.price

    return breaks


def latest_bos(bos_list: list[BreakOfStructure], before_index: int | None = None) -> BreakOfStructure | None:
    if not bos_list:
        return None
    if before_index is None:
        return bos_list[-1]
    candidates = [b for b in bos_list if b.broken_bar_index <= before_index]
    return candidates[-1] if candidates else None
