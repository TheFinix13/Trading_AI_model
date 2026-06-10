"""Tests for the ERL/IRL liquidity-magnet detector."""
from datetime import datetime, timedelta, timezone

from agent.detectors.liquidity_magnet import (
    RangeLiquidity,
    compute_range_liquidity,
    find_liquidity_magnets,
    range_liquidity_levels,
)
from agent.types import Bar, Direction, FVG, Swing, Timeframe

T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _bar(i, o, h, l, c, v=100.0):
    return Bar(time=T0 + timedelta(hours=i), open=o, high=h, low=l, close=c,
               volume=v, timeframe=Timeframe.H1)


def _range_series():
    """A clean dealing range: oscillates between ~1.0950 and ~1.1050."""
    bars = []
    lows = [1.0950, 1.0980, 1.0955]
    highs = [1.1050, 1.1020, 1.1045]
    price = 1.1000
    for i in range(60):
        lo = lows[i % 3]
        hi = highs[i % 3]
        c = hi if i % 2 == 0 else lo
        bars.append(_bar(i, price, hi, lo, c))
        price = c
    return bars


def test_compute_range_liquidity_marks_extremes():
    bars = _range_series()
    rl = compute_range_liquidity(bars, len(bars) - 1, lookback_bars=60)
    assert rl is not None
    assert rl.erl_high >= 1.1045
    assert rl.erl_low <= 1.0955
    assert rl.height > 0
    # Mid sits between the extremes.
    assert rl.erl_low < rl.mid < rl.erl_high


def test_premium_and_discount_classification():
    rl = RangeLiquidity(erl_high=1.1050, erl_low=1.0950)
    assert rl.premium(1.1040) is True       # near the high = premium
    assert rl.premium(1.0960) is False      # near the low = discount
    # The external draw from a premium price is the sell-side (down) extreme.
    assert rl.draw(1.1040) == Direction.SHORT
    assert rl.draw(1.0960) == Direction.LONG


def test_internal_liquidity_inside_extremes_only():
    bars = _range_series()
    swings = [
        Swing(time=T0, price=1.1050, is_high=True, bar_index=10),   # == extreme, excluded
        Swing(time=T0, price=1.1010, is_high=True, bar_index=20),   # internal high
        Swing(time=T0, price=1.0950, is_high=False, bar_index=30),  # == extreme, excluded
        Swing(time=T0, price=1.0990, is_high=False, bar_index=40),  # internal low
    ]
    rl = compute_range_liquidity(bars, len(bars) - 1, lookback_bars=60, swings=swings)
    assert any(abs(p - 1.1010) < 1e-6 for p in rl.irl_highs)
    assert any(abs(p - 1.0990) < 1e-6 for p in rl.irl_lows)
    # The extremes themselves are not duplicated into the internal pools.
    assert all(p < rl.erl_high for p in rl.irl_highs)
    assert all(p > rl.erl_low for p in rl.irl_lows)


def test_find_liquidity_magnets_pairs_fvg_with_minor_pool():
    rl = RangeLiquidity(
        erl_high=1.1050, erl_low=1.0950,
        irl_highs=[1.1010], irl_lows=[1.0990],
    )
    # An unfilled FVG centred at ~1.1008 sits right next to the 1.1010 minor BSL.
    fvg = FVG(
        direction=Direction.LONG, top=1.1012, bottom=1.1004,
        created_at=T0, created_bar_index=5, size_pips=8.0,
    )
    magnets = find_liquidity_magnets([fvg], rl, at_index=50, atr=0.0030,
                                     proximity_atr_mult=0.6)
    assert magnets
    assert any(m.side == "buyside" for m in magnets)


def test_filled_fvg_makes_no_magnet():
    rl = RangeLiquidity(erl_high=1.1050, erl_low=1.0950, irl_highs=[1.1010], irl_lows=[])
    fvg = FVG(direction=Direction.LONG, top=1.1012, bottom=1.1004, created_at=T0,
              created_bar_index=5, size_pips=8.0, is_fully_filled=True)
    assert find_liquidity_magnets([fvg], rl, at_index=50, atr=0.0030) == []


def test_range_liquidity_levels_emit_erl_and_irl():
    rl = RangeLiquidity(erl_high=1.1050, erl_low=1.0950, irl_highs=[1.1010], irl_lows=[1.0990])
    levels = range_liquidity_levels(rl)
    kinds = {kind for _, _, kind in levels}
    assert "erl" in kinds
    assert "irl" in kinds
    # Both external extremes are present.
    erl_prices = sorted(p for p, _, k in levels if k == "erl")
    assert erl_prices == [1.0950, 1.1050]
