"""Fair Value Gap detection.

Bullish FVG: a 3-bar pattern where bar[i-2].high < bar[i].low (gap between bars 1 and 3).
Bearish FVG: a 3-bar pattern where bar[i-2].low > bar[i].high.

The middle bar's range covers the gap. Price often returns to fill these gaps."""
from __future__ import annotations

from agent.types import Bar, FVG, Direction
from agent.utils import to_pips


def detect_fvgs(bars: list[Bar], min_size_pips: float = 5.0) -> list[FVG]:
    fvgs: list[FVG] = []
    if len(bars) < 3:
        return fvgs

    for i in range(2, len(bars)):
        b0, b1, b2 = bars[i - 2], bars[i - 1], bars[i]

        if b0.high < b2.low:
            size = to_pips(b2.low - b0.high)
            if size >= min_size_pips:
                fvgs.append(
                    FVG(
                        direction=Direction.LONG,
                        top=b2.low,
                        bottom=b0.high,
                        created_at=b1.time,
                        created_bar_index=i - 1,
                        size_pips=size,
                    )
                )
        elif b0.low > b2.high:
            size = to_pips(b0.low - b2.high)
            if size >= min_size_pips:
                fvgs.append(
                    FVG(
                        direction=Direction.SHORT,
                        top=b0.low,
                        bottom=b2.high,
                        created_at=b1.time,
                        created_bar_index=i - 1,
                        size_pips=size,
                    )
                )

    _mark_filled(fvgs, bars)
    return fvgs


def _mark_filled(fvgs: list[FVG], bars: list[Bar]) -> None:
    for fvg in fvgs:
        for j in range(fvg.created_bar_index + 1, len(bars)):
            b = bars[j]
            if fvg.direction == Direction.LONG and b.low <= fvg.bottom:
                fvg.filled = True
                fvg.filled_at = b.time
                break
            if fvg.direction == Direction.SHORT and b.high >= fvg.top:
                fvg.filled = True
                fvg.filled_at = b.time
                break


def unfilled_fvgs(fvgs: list[FVG], at_index: int) -> list[FVG]:
    return [
        f for f in fvgs
        if f.created_bar_index < at_index and (not f.filled or (f.filled_at is not None and False))
    ]
