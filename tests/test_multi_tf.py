"""Test the multi-TF backtest aggregator's overlap-prevention logic."""
from datetime import datetime, timedelta

from agent.backtest.multi_tf import _merge_chronological
from agent.types import Direction, Setup, Timeframe, Trade


def _make_trade(entry: datetime, exit_: datetime, tf: Timeframe = Timeframe.H1, pnl: float = 1.0):
    setup = Setup(
        direction=Direction.LONG, timeframe=tf, detected_at=entry, detected_bar_index=0,
        entry=1.10, stop=1.099, take_profit=1.102,
    )
    return Trade(
        setup=setup, direction=Direction.LONG,
        entry_time=entry, entry_price=1.10, stop_price=1.099, tp_price=1.102,
        lot_size=0.01, exit_time=exit_, exit_price=1.102, exit_reason="tp", pnl=pnl,
    )


def test_overlapping_trades_dropped():
    base = datetime(2024, 1, 1, 9, 0)
    h1 = _make_trade(base, base + timedelta(hours=4), Timeframe.H1)
    m15 = _make_trade(base + timedelta(hours=1), base + timedelta(hours=2), Timeframe.M15)
    out = _merge_chronological({Timeframe.H1: [h1], Timeframe.M15: [m15]})
    # H1 fired first; M15 trade is inside its window and must be dropped
    assert len(out) == 1
    assert out[0] is h1


def test_non_overlapping_kept():
    base = datetime(2024, 1, 1, 9, 0)
    a = _make_trade(base, base + timedelta(hours=2), Timeframe.H1)
    b = _make_trade(base + timedelta(hours=3), base + timedelta(hours=5), Timeframe.M15)
    out = _merge_chronological({Timeframe.H1: [a], Timeframe.M15: [b]})
    assert len(out) == 2
    assert out[0].setup.timeframe == Timeframe.H1
    assert out[1].setup.timeframe == Timeframe.M15


def test_earlier_signal_wins():
    base = datetime(2024, 1, 1, 9, 0)
    h1_late = _make_trade(base + timedelta(hours=2), base + timedelta(hours=6), Timeframe.H1)
    m15_early = _make_trade(base, base + timedelta(hours=1), Timeframe.M15)
    out = _merge_chronological({Timeframe.H1: [h1_late], Timeframe.M15: [m15_early]})
    # M15 fired first
    assert len(out) == 2
    assert out[0].setup.timeframe == Timeframe.M15
