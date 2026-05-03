"""Liquidity sweep detector — the *tagged* version of liquidity wicks.

The existing :func:`agent.detectors.liquidity.detect_liquidity_wicks` finds
long-wick stop-hunt bars but doesn't say *what* level was swept. That matters
because a sweep of "PDH" at NY open is a wildly stronger signal than a sweep
of an arbitrary local high.

A "liquidity sweep" here is:

  1. A bar's wick pierces a tagged level (PDH / PDL / PWH / PWL / equal-highs
     / equal-lows / recent swing).
  2. The bar closes back inside the level (failed breakout).
  3. The next 1-3 bars confirm the rejection by moving in the opposite
     direction by at least `confirm_pips`.

Rule (3) is the key separator from a "real" breakout. A legitimate breakout
will continue running; a sweep reverses immediately because it was a
liquidity grab, not a directional move.

Output is a list of :class:`LiquiditySweep` events with the tagged level so
the narrative can say "swept PDH at 1.17680 then reversed".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from agent.detectors.daily_levels import DailyLevels, compute_daily_levels
from agent.detectors.swings import detect_swings
from agent.types import Bar, Direction

SweepSide = Literal["buyside", "sellside"]


@dataclass
class LiquiditySweep:
    side: SweepSide              # buyside = took out highs, sellside = took out lows
    direction: Direction         # the resulting trade direction (LONG after sellside, SHORT after buyside)
    swept_label: str             # "PDH", "PDL", "swing_high", "equal_highs", ...
    swept_price: float
    sweep_bar_index: int
    sweep_time: datetime
    sweep_high: float
    sweep_low: float
    sweep_close: float
    confirm_bar_index: int       # index of the bar that confirmed reversal
    confirm_pips: float          # distance from sweep close to confirm close, in pips
    rr_estimate: float | None = None


def _equal_levels(swings, n: int = 3, tol_pips: float = 5.0) -> list[tuple[str, float, int]]:
    """Find clusters of swing highs/lows within `tol_pips`. Used to detect
    'equal highs/lows' that pool stops underneath retail orders."""
    out = []
    tol = tol_pips * 0.0001
    highs = [s for s in swings if s.is_high]
    lows = [s for s in swings if not s.is_high]
    for group, label in ((highs, "equal_highs"), (lows, "equal_lows")):
        if len(group) < 2:
            continue
        for i, s in enumerate(group):
            cluster = [s]
            for t in group[i + 1 :]:
                if abs(t.price - s.price) <= tol:
                    cluster.append(t)
                if len(cluster) >= n:
                    break
            if len(cluster) >= 2:
                avg = sum(c.price for c in cluster) / len(cluster)
                out.append((label, avg, max(c.bar_index for c in cluster)))
    return out


def detect_liquidity_sweeps(
    bars: list[Bar],
    *,
    swing_lookback: int = 5,
    pierce_buffer_pips: float = 1.0,
    confirm_pips: float = 5.0,
    confirm_max_bars: int = 3,
    use_daily_levels: bool = True,
) -> list[LiquiditySweep]:
    """Walk bars and emit sweep events. See module docstring for criteria."""
    if len(bars) < swing_lookback * 2 + 2:
        return []

    swings = detect_swings(bars, lookback=swing_lookback)
    daily_levels = compute_daily_levels(bars) if use_daily_levels else [None] * len(bars)
    equal_clusters = _equal_levels(swings)

    pip = 0.0001
    buf = pierce_buffer_pips * pip
    out: list[LiquiditySweep] = []

    # Iterate every bar except the very last (which can never be confirmed).
    # _wait_for_reverse handles its own end-of-list bounds, so this is safe.
    for i in range(len(bars) - 1):
        bar = bars[i]

        # ---- collect candidate levels visible at bar i (no look-ahead) ------
        upper_targets: list[tuple[str, float]] = []
        lower_targets: list[tuple[str, float]] = []

        dl = daily_levels[i] if use_daily_levels else None
        if dl is not None:
            for lbl, price in dl.levels_dict().items():
                # Levels above current bar's body are buyside targets, below are sellside.
                ref = max(bar.open, bar.close)
                if price >= ref:
                    upper_targets.append((lbl, price))
                else:
                    lower_targets.append((lbl, price))

        for s in swings:
            if s.bar_index >= i - swing_lookback:
                continue
            if s.is_high and s.price >= max(bar.open, bar.close):
                upper_targets.append(("swing_high", s.price))
            elif (not s.is_high) and s.price <= min(bar.open, bar.close):
                lower_targets.append(("swing_low", s.price))

        for lbl, price, end_idx in equal_clusters:
            if end_idx >= i:
                continue
            if lbl == "equal_highs" and price >= max(bar.open, bar.close):
                upper_targets.append((lbl, price))
            elif lbl == "equal_lows" and price <= min(bar.open, bar.close):
                lower_targets.append((lbl, price))

        # Pick the closest target above/below within wick reach (avoid double-count).
        def _best(targets: list[tuple[str, float]], hi_or_lo: str) -> tuple[str, float] | None:
            if not targets:
                return None
            if hi_or_lo == "hi":
                pierced = [t for t in targets if bar.high > t[1] + buf]
                return min(pierced, key=lambda t: t[1]) if pierced else None
            else:
                pierced = [t for t in targets if bar.low < t[1] - buf]
                return max(pierced, key=lambda t: t[1]) if pierced else None

        # ---- buyside sweep: wicked above level, closed back below -----------
        up = _best(upper_targets, "hi")
        if up is not None and bar.close < up[1]:
            confirm_bar_idx, confirm_close = _wait_for_reverse(
                bars, i, direction=Direction.SHORT,
                target_pips=confirm_pips, max_bars=confirm_max_bars,
            )
            if confirm_bar_idx is not None:
                wick_pips = max((bar.high - bar.close) / pip, 1.0)
                out.append(LiquiditySweep(
                    side="buyside",
                    direction=Direction.SHORT,
                    swept_label=up[0],
                    swept_price=up[1],
                    sweep_bar_index=i,
                    sweep_time=bar.time,
                    sweep_high=bar.high,
                    sweep_low=bar.low,
                    sweep_close=bar.close,
                    confirm_bar_index=confirm_bar_idx,
                    confirm_pips=(bar.close - confirm_close) / pip,
                    rr_estimate=((bar.close - confirm_close) / pip) / wick_pips,
                ))

        # ---- sellside sweep: wicked below level, closed back above ----------
        dn = _best(lower_targets, "lo")
        if dn is not None and bar.close > dn[1]:
            confirm_bar_idx, confirm_close = _wait_for_reverse(
                bars, i, direction=Direction.LONG,
                target_pips=confirm_pips, max_bars=confirm_max_bars,
            )
            if confirm_bar_idx is not None:
                wick_pips = max((bar.close - bar.low) / pip, 1.0)
                out.append(LiquiditySweep(
                    side="sellside",
                    direction=Direction.LONG,
                    swept_label=dn[0],
                    swept_price=dn[1],
                    sweep_bar_index=i,
                    sweep_time=bar.time,
                    sweep_high=bar.high,
                    sweep_low=bar.low,
                    sweep_close=bar.close,
                    confirm_bar_index=confirm_bar_idx,
                    confirm_pips=(confirm_close - bar.close) / pip,
                    rr_estimate=((confirm_close - bar.close) / pip) / wick_pips,
                ))

    return out


def _wait_for_reverse(
    bars: list[Bar],
    sweep_idx: int,
    direction: Direction,
    target_pips: float,
    max_bars: int,
) -> tuple[int | None, float]:
    """Look for a confirmation close `target_pips` in `direction` within `max_bars`.
    Returns (bar_index, close_price) of the first confirming bar, or (None, 0.0)."""
    pip = 0.0001
    sweep_close = bars[sweep_idx].close
    for j in range(sweep_idx + 1, min(sweep_idx + 1 + max_bars, len(bars))):
        b = bars[j]
        if direction == Direction.SHORT:
            if (sweep_close - b.close) / pip >= target_pips:
                return j, b.close
        else:
            if (b.close - sweep_close) / pip >= target_pips:
                return j, b.close
    return None, 0.0
