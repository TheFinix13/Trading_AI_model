"""Liquidity sweep detector — the *tagged* version of liquidity wicks.

The existing :func:`agent.detectors.liquidity.detect_liquidity_wicks` finds
long-wick stop-hunt bars but doesn't say *what* level was swept. That matters
because a sweep of "PDH" at NY open is a wildly stronger signal than a sweep
of an arbitrary local high.

A "liquidity sweep" here is:

  1. A bar's wick pierces a tagged level (PDH / PDL / PWH / PWL / equal-highs
     / equal-lows / recent swing).
  2. The bar closes back inside the level (failed breakout).
  3. Optionally — when ``require_reversal_confirmation=True`` — the next 1-3
     bars must confirm the rejection by moving in the opposite direction by at
     least ``confirm_pips``.

**Causality note.** When a backtest precomputes sweeps over a long bar series,
forward-looking reversal confirmation creates survivor bias: only sweeps that
*subsequently* reversed appear in the result set. The default in v2 is
``require_reversal_confirmation=False`` so the detector returns every sweep
event at the moment it is geometrically visible, and the strategy loop confirms
the reversal causally bar-by-bar via :func:`confirm_reversal_at`.

Output is a list of :class:`LiquiditySweep` events with the tagged level so
the narrative can say "swept PDH at 1.17680 then reversed".
"""
from __future__ import annotations

import bisect
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
    require_reversal_confirmation: bool = False,
) -> list[LiquiditySweep]:
    """Walk bars and emit sweep events. See module docstring for criteria.

    With ``require_reversal_confirmation=False`` (v2 default) the detector is
    fully causal — every sweep is emitted at its sweep bar with
    ``confirm_bar_index = -1`` and ``confirm_pips = 0.0``. Callers that need
    reversal confirmation should iterate sweeps bar-by-bar and call
    :func:`confirm_reversal_at` with the index they have reached. Legacy
    callers can opt into the old forward-looking behaviour but should NOT use
    it inside a backtest precompute (see module docstring).

    Performance: the original v2 implementation iterated every ``swing`` for
    every ``bar`` (O(N × S) ≈ 136M Python ops on 68k H1 bars × 2k swings →
    ~123s wall time). This version maintains two ``bisect``-sorted lists of
    swing prices indexed chronologically; each bar's candidate window is found
    in ``O(log N)`` and the bar-output loop stays unchanged. Result objects
    are bit-identical (verified by ``tests/test_liquidity_sweep_speedup.py``).
    """
    if len(bars) < swing_lookback * 2 + 2:
        return []

    swings = detect_swings(bars, lookback=swing_lookback)
    daily_levels = compute_daily_levels(bars) if use_daily_levels else [None] * len(bars)
    equal_clusters = _equal_levels(swings)

    pip = 0.0001
    buf = pierce_buffer_pips * pip
    out: list[LiquiditySweep] = []

    # --- chronological swing index + maintained sorted-price lists -----------
    high_swings = sorted([s for s in swings if s.is_high], key=lambda s: s.bar_index)
    low_swings = sorted([s for s in swings if not s.is_high], key=lambda s: s.bar_index)
    visible_high_prices: list[float] = []  # maintained sorted ascending
    visible_low_prices: list[float] = []
    high_cursor = 0
    low_cursor = 0

    # Equal clusters bucketed by visibility index — small (~hundreds), so a
    # single sort + linear scan with a cursor is fastest.
    eq_highs = sorted([(end_idx, price) for lbl, price, end_idx in equal_clusters
                       if lbl == "equal_highs"], key=lambda t: t[0])
    eq_lows = sorted([(end_idx, price) for lbl, price, end_idx in equal_clusters
                      if lbl == "equal_lows"], key=lambda t: t[0])
    visible_eq_highs: list[float] = []
    visible_eq_lows: list[float] = []
    eq_high_cursor = 0
    eq_low_cursor = 0

    last_idx = len(bars) - 1 if require_reversal_confirmation else len(bars)
    for i in range(last_idx):
        bar = bars[i]

        # --- update visibility cursors as new swings/clusters become legal ---
        # A swing is visible at i iff swing.bar_index < i - swing_lookback,
        # matching the original strict-inequality semantics.
        threshold = i - swing_lookback
        while high_cursor < len(high_swings) and high_swings[high_cursor].bar_index < threshold:
            bisect.insort(visible_high_prices, high_swings[high_cursor].price)
            high_cursor += 1
        while low_cursor < len(low_swings) and low_swings[low_cursor].bar_index < threshold:
            bisect.insort(visible_low_prices, low_swings[low_cursor].price)
            low_cursor += 1
        # Equal-cluster visibility threshold is end_idx < i (also strict).
        while eq_high_cursor < len(eq_highs) and eq_highs[eq_high_cursor][0] < i:
            bisect.insort(visible_eq_highs, eq_highs[eq_high_cursor][1])
            eq_high_cursor += 1
        while eq_low_cursor < len(eq_lows) and eq_lows[eq_low_cursor][0] < i:
            bisect.insort(visible_eq_lows, eq_lows[eq_low_cursor][1])
            eq_low_cursor += 1

        ref_upper = bar.open if bar.open > bar.close else bar.close
        ref_lower = bar.open if bar.open < bar.close else bar.close

        # --- buyside sweep: wicked above some level, closed back below ------
        # Target window: price in [ref_upper, bar.high - buf). The lowest
        # price in that window is the closest pierced level (matches the
        # ``min(pierced, key=price)`` of the original ``_best("hi")``).
        #
        # All upper-target sources (daily, swing_high, equal_highs) require
        # ``price >= ref_upper`` in the v2 semantics, so the cheapest possible
        # candidate sits exactly at ``ref_upper``. The early-exit gate is
        # therefore safe at ``ref_upper`` for the upper side.
        if bar.high > ref_upper + buf:
            up_label, up_price = _best_above(
                ref_upper, bar.high - buf, daily_levels[i] if use_daily_levels else None,
                visible_high_prices, visible_eq_highs,
            )
            if up_label is not None and bar.close < up_price:
                sweep_event = LiquiditySweep(
                    side="buyside",
                    direction=Direction.SHORT,
                    swept_label=up_label,
                    swept_price=up_price,
                    sweep_bar_index=i,
                    sweep_time=bar.time,
                    sweep_high=bar.high,
                    sweep_low=bar.low,
                    sweep_close=bar.close,
                    confirm_bar_index=-1,
                    confirm_pips=0.0,
                    rr_estimate=None,
                )
                if require_reversal_confirmation:
                    wick_pips = max((bar.high - bar.close) / pip, 1.0)
                    confirm_bar_idx, confirm_close = _wait_for_reverse(
                        bars, i, direction=Direction.SHORT,
                        target_pips=confirm_pips, max_bars=confirm_max_bars,
                    )
                    if confirm_bar_idx is None:
                        continue
                    sweep_event.confirm_bar_index = confirm_bar_idx
                    sweep_event.confirm_pips = (bar.close - confirm_close) / pip
                    sweep_event.rr_estimate = sweep_event.confirm_pips / wick_pips
                out.append(sweep_event)

        # --- sellside sweep: wicked below some level, closed back above -----
        # ``ref_upper`` (NOT ref_lower!) is the right early-exit ceiling here:
        # daily levels can sit anywhere up to ref_upper - epsilon (their split
        # rule is ``price < ref_upper``), so a daily level can be a valid
        # lower target even when bar.low == ref_lower. Using ref_lower here
        # silently dropped 15 H4 PDH sweeps that the v2 detector emitted.
        if bar.low < ref_upper - buf:
            dn_label, dn_price = _best_below(
                swing_ceiling=ref_lower,
                daily_ceiling=ref_upper,
                floor=bar.low + buf,
                daily=daily_levels[i] if use_daily_levels else None,
                visible_swing_lows=visible_low_prices,
                visible_eq_lows=visible_eq_lows,
            )
            if dn_label is not None and bar.close > dn_price:
                sweep_event = LiquiditySweep(
                    side="sellside",
                    direction=Direction.LONG,
                    swept_label=dn_label,
                    swept_price=dn_price,
                    sweep_bar_index=i,
                    sweep_time=bar.time,
                    sweep_high=bar.high,
                    sweep_low=bar.low,
                    sweep_close=bar.close,
                    confirm_bar_index=-1,
                    confirm_pips=0.0,
                    rr_estimate=None,
                )
                if require_reversal_confirmation:
                    wick_pips = max((bar.close - bar.low) / pip, 1.0)
                    confirm_bar_idx, confirm_close = _wait_for_reverse(
                        bars, i, direction=Direction.LONG,
                        target_pips=confirm_pips, max_bars=confirm_max_bars,
                    )
                    if confirm_bar_idx is None:
                        continue
                    sweep_event.confirm_bar_index = confirm_bar_idx
                    sweep_event.confirm_pips = (confirm_close - bar.close) / pip
                    sweep_event.rr_estimate = sweep_event.confirm_pips / wick_pips
                out.append(sweep_event)

    return out


def _best_above(
    floor: float,
    ceiling: float,
    daily: "DailyLevels | None",
    visible_swing_highs: list[float],
    visible_eq_highs: list[float],
) -> tuple[str | None, float]:
    """Find the lowest level price in ``[floor, ceiling)`` across the three
    candidate sources (daily, swings, equal-highs). Returns ``(label, price)``
    or ``(None, 0.0)`` if no candidate sits in the pierce window.

    Tie-break order mirrors the original detector: daily-levels evaluated
    first (their label wins when prices coincide), then swing_high, then
    equal_highs — but the original used ``min(pierced, key=lambda t: t[1])``
    which is *only* by price, so we replicate that. Stable sort by insertion
    order for tied prices.
    """
    best_label: str | None = None
    best_price = float("inf")

    # Daily-levels: small dict (≤8 entries). Linear scan is cheapest.
    if daily is not None:
        for lbl, price in daily.levels_dict().items():
            if floor <= price < ceiling and price < best_price:
                best_label = lbl
                best_price = price

    # Swings: O(log N) bisect into the sorted price list.
    lo = bisect.bisect_left(visible_swing_highs, floor)
    if lo < len(visible_swing_highs):
        s_price = visible_swing_highs[lo]
        if s_price < ceiling and s_price < best_price:
            best_label = "swing_high"
            best_price = s_price

    # Equal-highs cluster: same trick.
    lo = bisect.bisect_left(visible_eq_highs, floor)
    if lo < len(visible_eq_highs):
        e_price = visible_eq_highs[lo]
        if e_price < ceiling and e_price < best_price:
            best_label = "equal_highs"
            best_price = e_price

    return (best_label, best_price if best_label is not None else 0.0)


def _best_below(
    *,
    swing_ceiling: float,
    daily_ceiling: float,
    floor: float,
    daily: "DailyLevels | None",
    visible_swing_lows: list[float],
    visible_eq_lows: list[float],
) -> tuple[str | None, float]:
    """Mirror of :func:`_best_above`. For the sellside we want the *highest*
    price in the pierce window across the three sources.

    Two different ceilings on purpose — this mirrors the original v2
    asymmetry:

      * **daily levels** are split into upper/lower at ``ref_upper`` (the
        body top), so a daily level qualifies as a lower target when
        ``price < ref_upper``. Hence ``daily_ceiling = ref_upper``.
      * **swings / equal-lows** only join ``lower_targets`` when
        ``price <= ref_lower`` (price is at or below the body bottom). Hence
        ``swing_ceiling = ref_lower``.

    Conflating the two ceilings (using ``ref_lower`` for daily too) silently
    discards every PDH/PDL that sits inside the body — exactly the drift the
    equivalence test caught.
    """
    best_label: str | None = None
    best_price = float("-inf")

    if daily is not None:
        for lbl, price in daily.levels_dict().items():
            # Original used `price < ref` (strict) for the daily-level split.
            if floor < price < daily_ceiling and price > best_price:
                best_label = lbl
                best_price = price

    # bisect_right returns the insertion point AFTER any equal entries; the
    # element at idx-1 is the largest <= swing_ceiling.
    hi = bisect.bisect_right(visible_swing_lows, swing_ceiling)
    if hi > 0:
        s_price = visible_swing_lows[hi - 1]
        if s_price > floor and s_price > best_price:
            best_label = "swing_low"
            best_price = s_price

    hi = bisect.bisect_right(visible_eq_lows, swing_ceiling)
    if hi > 0:
        e_price = visible_eq_lows[hi - 1]
        if e_price > floor and e_price > best_price:
            best_label = "equal_lows"
            best_price = e_price

    return (best_label, best_price if best_label is not None else 0.0)


def _wait_for_reverse(
    bars: list[Bar],
    sweep_idx: int,
    direction: Direction,
    target_pips: float,
    max_bars: int,
) -> tuple[int | None, float]:
    """Legacy forward-looking confirmation. **DO NOT use in batch precompute.**
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


def confirm_reversal_at(
    sweep: LiquiditySweep,
    bars: list[Bar],
    at_index: int,
    *,
    target_pips: float = 5.0,
    max_bars: int = 3,
) -> bool:
    """Causal confirmation: True iff some bar in
    ``(sweep.sweep_bar_index, min(sweep.sweep_bar_index + max_bars, at_index)]``
    closed ``target_pips`` in the sweep's reaction direction. Strategy loops
    should call this when they reach ``at_index`` rather than reading any
    pre-stored ``confirm_bar_index``."""
    pip = 0.0001
    end = min(sweep.sweep_bar_index + max_bars, at_index)
    if end <= sweep.sweep_bar_index:
        return False
    for j in range(sweep.sweep_bar_index + 1, end + 1):
        b = bars[j]
        if sweep.direction == Direction.SHORT:
            if (sweep.sweep_close - b.close) / pip >= target_pips:
                return True
        else:
            if (b.close - sweep.sweep_close) / pip >= target_pips:
                return True
    return False
