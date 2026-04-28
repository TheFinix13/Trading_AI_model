from datetime import datetime, timedelta

from agent.detectors.swings import detect_swings, last_swing
from agent.types import Bar, Timeframe


def make_bars(prices):
    base = datetime(2024, 1, 1)
    bars = []
    for i, p in enumerate(prices):
        bars.append(
            Bar(
                time=base + timedelta(hours=i),
                open=p, high=p + 0.0005, low=p - 0.0005, close=p,
                volume=100, timeframe=Timeframe.H1,
            )
        )
    return bars


def test_detects_swing_high_and_low():
    prices = [1.0, 1.1, 1.2, 1.3, 1.5, 1.4, 1.3, 1.2, 1.0, 0.9, 1.1, 1.2]
    bars = make_bars(prices)
    swings = detect_swings(bars, lookback=2)
    assert any(s.is_high for s in swings)
    assert any(not s.is_high for s in swings)


def test_last_swing():
    bars = make_bars([1.0, 1.1, 1.2, 1.3, 1.5, 1.4, 1.3, 1.2, 1.0, 0.9, 1.1, 1.2, 1.3])
    swings = detect_swings(bars, lookback=2)
    high = last_swing(swings, is_high=True)
    low = last_swing(swings, is_high=False)
    assert high is not None
    assert low is not None
