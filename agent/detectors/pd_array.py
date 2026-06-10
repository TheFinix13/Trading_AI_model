"""PD Array / Draw on Liquidity targeting.

Finds the nearest *unswept* liquidity level on the opposite side of the
market for take-profit placement.  If entering LONG (after a sellside sweep
retest), the TP targets the nearest unswept buyside level (PDH, PWH, swing
highs, equal highs).  If entering SHORT, targets sellside levels below.

A level counts as "swept" if price wicked through it in the last
`swept_lookback_bars` bars.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.detectors.daily_levels import DailyLevels
from agent.types import Bar, Direction, Swing

PIP = 0.0001


@dataclass
class PDArrayTarget:
    """An unswept liquidity level that price is likely targeting."""
    label: str
    price: float
    side: Literal["buyside", "sellside"]
    distance_pips: float
    already_swept: bool


def _is_swept(price: float, bars: list[Bar], at_index: int, lookback: int, side: str) -> bool:
    """Check if a level has been swept (wicked through) in the recent window."""
    start = max(0, at_index - lookback)
    for i in range(start, at_index + 1):
        bar = bars[i]
        if side == "buyside" and bar.high > price + PIP:
            return True
        if side == "sellside" and bar.low < price - PIP:
            return True
    return False


def find_draw_on_liquidity(
    bars: list[Bar],
    at_index: int,
    direction: Direction,
    *,
    daily_levels: DailyLevels | None = None,
    swings: list[Swing] | None = None,
    swept_lookback_bars: int = 50,
) -> PDArrayTarget | None:
    """Find the nearest unswept liquidity target in the given direction.

    - If LONG: find nearest unswept buyside target (PDH, PWH, swing highs, equal highs)
    - If SHORT: find nearest unswept sellside target (PDL, PWL, swing lows, equal lows)
    """
    if at_index < 0 or at_index >= len(bars):
        return None

    current_price = bars[at_index].close
    candidates: list[PDArrayTarget] = []

    if direction == Direction.LONG:
        # Target buyside liquidity above current price
        if daily_levels is not None:
            for lbl, price in daily_levels.levels_dict().items():
                if lbl in ("PDM", "PWM"):
                    continue
                if price > current_price:
                    swept = _is_swept(price, bars, at_index, swept_lookback_bars, "buyside")
                    candidates.append(PDArrayTarget(
                        label=lbl, price=price, side="buyside",
                        distance_pips=(price - current_price) / PIP,
                        already_swept=swept,
                    ))
        if swings:
            for s in swings:
                if s.is_high and s.price > current_price and s.bar_index < at_index:
                    swept = _is_swept(s.price, bars, at_index, swept_lookback_bars, "buyside")
                    candidates.append(PDArrayTarget(
                        label="swing_high", price=s.price, side="buyside",
                        distance_pips=(s.price - current_price) / PIP,
                        already_swept=swept,
                    ))
    else:
        # Target sellside liquidity below current price
        if daily_levels is not None:
            for lbl, price in daily_levels.levels_dict().items():
                if lbl in ("PDM", "PWM"):
                    continue
                if price < current_price:
                    swept = _is_swept(price, bars, at_index, swept_lookback_bars, "sellside")
                    candidates.append(PDArrayTarget(
                        label=lbl, price=price, side="sellside",
                        distance_pips=(current_price - price) / PIP,
                        already_swept=swept,
                    ))
        if swings:
            for s in swings:
                if not s.is_high and s.price < current_price and s.bar_index < at_index:
                    swept = _is_swept(s.price, bars, at_index, swept_lookback_bars, "sellside")
                    candidates.append(PDArrayTarget(
                        label="swing_low", price=s.price, side="sellside",
                        distance_pips=(current_price - s.price) / PIP,
                        already_swept=swept,
                    ))

    # Filter to unswept only, then pick nearest
    unswept = [c for c in candidates if not c.already_swept]
    if not unswept:
        return None

    return min(unswept, key=lambda c: c.distance_pips)


def collect_opposite_liquidity_levels(
    bars: list[Bar],
    at_index: int,
    direction: Direction,
    *,
    daily_levels: DailyLevels | None = None,
    swings: list[Swing] | None = None,
    swept_lookback_bars: int = 50,
) -> list[tuple[str, float]]:
    """Collect all unswept opposite-side liquidity levels as (label, price) pairs.

    Used by `check_retest_entries` for TP targeting: provides the full set
    of valid targets so the entry logic can pick the best one.
    """
    if at_index < 0 or at_index >= len(bars):
        return []

    current_price = bars[at_index].close
    results: list[tuple[str, float]] = []

    if direction == Direction.LONG:
        if daily_levels is not None:
            for lbl, price in daily_levels.levels_dict().items():
                if lbl in ("PDM", "PWM"):
                    continue
                if price > current_price:
                    if not _is_swept(price, bars, at_index, swept_lookback_bars, "buyside"):
                        results.append((lbl, price))
        if swings:
            for s in swings:
                if s.is_high and s.price > current_price and s.bar_index < at_index:
                    if not _is_swept(s.price, bars, at_index, swept_lookback_bars, "buyside"):
                        results.append(("swing_high", s.price))
    else:
        if daily_levels is not None:
            for lbl, price in daily_levels.levels_dict().items():
                if lbl in ("PDM", "PWM"):
                    continue
                if price < current_price:
                    if not _is_swept(price, bars, at_index, swept_lookback_bars, "sellside"):
                        results.append((lbl, price))
        if swings:
            for s in swings:
                if not s.is_high and s.price < current_price and s.bar_index < at_index:
                    if not _is_swept(s.price, bars, at_index, swept_lookback_bars, "sellside"):
                        results.append(("swing_low", s.price))

    return results
