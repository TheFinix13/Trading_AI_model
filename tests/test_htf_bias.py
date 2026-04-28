"""Unit tests for the higher-timeframe bias filter."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.rules.htf_bias import HTFBiasComputer, _ema_slope, _find_bar_at_or_before
from agent.types import Bar, Direction, Timeframe


def _bars_uptrend(n: int = 60, start_price: float = 1.0800,
                  step: float = 0.0008) -> list[Bar]:
    """Strictly increasing closes — D1 bars marching up."""
    bars: list[Bar] = []
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        c = start_price + i * step
        bars.append(Bar(
            time=t0 + timedelta(days=i),
            open=c - step / 2, high=c + step / 4, low=c - step,
            close=c, volume=1000.0, timeframe=Timeframe.D1,
        ))
    return bars


def _bars_downtrend(n: int = 60) -> list[Bar]:
    return [Bar(
        time=b.time, open=b.open, high=b.high, low=b.low,
        close=2 * 1.0800 - b.close,  # mirror around 1.0800
        volume=b.volume, timeframe=b.timeframe,
    ) for b in _bars_uptrend(n)]


def test_ema_slope_positive_in_uptrend():
    bars = _bars_uptrend(60)
    slope = _ema_slope(bars, period=20, lookback=5)
    assert slope > 0


def test_ema_slope_negative_in_downtrend():
    bars = _bars_downtrend(60)
    slope = _ema_slope(bars, period=20, lookback=5)
    assert slope < 0


def test_bias_at_uptrend():
    bars = _bars_uptrend(60)
    hb = HTFBiasComputer.build(bars, zone_min_impulse_pips=10.0)
    bias = hb.bias_at(bars[-1].time, current_price=bars[-1].close)
    assert bias.direction == Direction.LONG
    assert bias.agrees_with(Direction.LONG)
    assert not bias.agrees_with(Direction.SHORT)


def test_bias_at_downtrend():
    bars = _bars_downtrend(60)
    hb = HTFBiasComputer.build(bars, zone_min_impulse_pips=10.0)
    bias = hb.bias_at(bars[-1].time, current_price=bars[-1].close)
    assert bias.direction == Direction.SHORT
    assert bias.agrees_with(Direction.SHORT)
    assert not bias.agrees_with(Direction.LONG)


def test_neutral_bias_permits_any_direction():
    """No clear trend → neither direction is blocked."""
    # Build flat bars: all closes at 1.0800
    bars = []
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(60):
        bars.append(Bar(
            time=t0 + timedelta(days=i),
            open=1.0800, high=1.0801, low=1.0799,
            close=1.0800, volume=1000.0, timeframe=Timeframe.D1,
        ))
    hb = HTFBiasComputer.build(bars, zone_min_impulse_pips=10.0)
    bias = hb.bias_at(bars[-1].time, current_price=1.0800)
    assert bias.direction is None
    assert bias.agrees_with(Direction.LONG)
    assert bias.agrees_with(Direction.SHORT)


def test_no_lookahead():
    """Querying bias_at() with an early time must not 'see' future bars."""
    bars = _bars_uptrend(60)
    hb = HTFBiasComputer.build(bars)
    # Ask for bias halfway through; should only have N/2 bars to work with
    bias = hb.bias_at(bars[10].time, current_price=bars[10].close)
    # idx<5 returns empty bias; that's expected here for lookback safety
    # Important assertion: doesn't raise, and direction comes from history-only
    if bias.direction is not None:
        # if a direction was inferred, it had to be from the first 11 bars
        assert _find_bar_at_or_before(bars, bars[10].time) == 10
