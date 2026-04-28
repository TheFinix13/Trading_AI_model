"""Fractal swing high/low detection."""
from __future__ import annotations

from agent.types import Bar, Swing


def detect_swings(bars: list[Bar], lookback: int = 5) -> list[Swing]:
    """A bar is a swing high if its high is the max of the surrounding 2*lookback+1 bars
    and a swing low if its low is the min. Last `lookback` bars are not yet confirmed."""
    swings: list[Swing] = []
    n = len(bars)
    if n < 2 * lookback + 1:
        return swings

    for i in range(lookback, n - lookback):
        window = bars[i - lookback : i + lookback + 1]
        center = bars[i]
        if center.high == max(b.high for b in window):
            swings.append(Swing(time=center.time, price=center.high, is_high=True, bar_index=i))
        if center.low == min(b.low for b in window):
            swings.append(Swing(time=center.time, price=center.low, is_high=False, bar_index=i))
    return swings


def last_swing(swings: list[Swing], is_high: bool, before_index: int | None = None) -> Swing | None:
    candidates = [s for s in swings if s.is_high == is_high]
    if before_index is not None:
        candidates = [s for s in candidates if s.bar_index < before_index]
    return candidates[-1] if candidates else None
