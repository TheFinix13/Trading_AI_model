from datetime import datetime, timedelta

from agent.detectors.fvg import detect_fvgs
from agent.types import Bar, Direction, Timeframe


def bar(t, o, h, l, c):
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=100, timeframe=Timeframe.H1)


def test_bullish_fvg():
    t = datetime(2024, 1, 1)
    bars = [
        bar(t, 1.1000, 1.1010, 1.0990, 1.1005),
        bar(t + timedelta(hours=1), 1.1005, 1.1100, 1.1000, 1.1095),  # impulse up
        bar(t + timedelta(hours=2), 1.1100, 1.1110, 1.1050, 1.1080),  # gap: low > prev-prev high
    ]
    fvgs = detect_fvgs(bars, min_size_pips=2)
    assert len(fvgs) == 1
    assert fvgs[0].direction == Direction.LONG


def test_bearish_fvg():
    t = datetime(2024, 1, 1)
    bars = [
        bar(t, 1.1100, 1.1110, 1.1090, 1.1095),
        bar(t + timedelta(hours=1), 1.1095, 1.1100, 1.1000, 1.1005),  # impulse down
        bar(t + timedelta(hours=2), 1.1000, 1.1080, 1.0990, 1.0995),  # high < prev-prev low
    ]
    fvgs = detect_fvgs(bars, min_size_pips=2)
    assert len(fvgs) == 1
    assert fvgs[0].direction == Direction.SHORT
