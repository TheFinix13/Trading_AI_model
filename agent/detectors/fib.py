"""Fib retracement auto-draw on the last completed impulse."""
from __future__ import annotations

from agent.detectors.swings import detect_swings
from agent.types import Bar, Direction, FibLevel


def auto_fib(
    bars: list[Bar],
    swing_lookback: int = 5,
    levels: list[float] = (0.382, 0.5, 0.618, 0.786),
) -> FibLevel | None:
    """Find the last impulse leg using the most recent two confirmed swings of opposite type
    and draw fibs over it."""
    swings = detect_swings(bars, lookback=swing_lookback)
    if len(swings) < 2:
        return None

    last = swings[-1]
    prev_opposite = next(
        (s for s in reversed(swings[:-1]) if s.is_high != last.is_high),
        None,
    )
    if prev_opposite is None:
        return None

    if last.is_high:
        # Up impulse: 0% at high (last), 100% at low (prev)
        start = prev_opposite.price
        end = last.price
        direction = Direction.LONG
    else:
        # Down impulse: 0% at low (last), 100% at high (prev)
        start = prev_opposite.price
        end = last.price
        direction = Direction.SHORT

    span = end - start  # positive for up impulse, negative for down
    level_prices = {lvl: end - lvl * span for lvl in levels}

    return FibLevel(
        impulse_start=start,
        impulse_end=end,
        direction=direction,
        levels=level_prices,
        created_at=last.time,
    )
