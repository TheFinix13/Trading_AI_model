"""Date-window filter for bars — eliminates training/validation data leakage."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.data.loader import filter_bars_by_date
from agent.types import Bar, Timeframe


def _bars(n: int = 100, start: datetime | None = None) -> list[Bar]:
    """Generate n daily bars starting at `start` (UTC)."""
    if start is None:
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out: list[Bar] = []
    for i in range(n):
        t = start + timedelta(days=i)
        out.append(Bar(
            time=t, open=1.10, high=1.11, low=1.09,
            close=1.105, volume=1000.0, timeframe=Timeframe.D1,
        ))
    return out


def test_no_filter_returns_all():
    bars = _bars(100)
    assert len(filter_bars_by_date(bars)) == 100


def test_start_filter():
    bars = _bars(100)
    cut = bars[50].time  # day 50 inclusive
    out = filter_bars_by_date(bars, start=cut)
    assert len(out) == 50
    assert out[0].time == cut


def test_end_filter():
    bars = _bars(100)
    cut = bars[50].time  # day 50 exclusive
    out = filter_bars_by_date(bars, end=cut)
    assert len(out) == 50
    assert out[-1].time == bars[49].time


def test_start_and_end():
    """Critical: simulating an OOS validation window that excludes training period."""
    bars = _bars(365)  # one year of daily bars
    train_end = bars[200].time
    val_end = bars[300].time
    val_bars = filter_bars_by_date(bars, start=train_end, end=val_end)
    assert len(val_bars) == 100
    assert val_bars[0].time == train_end
    assert val_bars[-1].time < val_end


def test_naive_datetime_handled():
    """Real-world CLI usage passes a naive datetime; we must not crash."""
    bars = _bars(50)
    naive = datetime(2025, 1, 25)  # no tzinfo
    out = filter_bars_by_date(bars, start=naive)
    assert len(out) > 0  # didn't raise
    assert all(b.time >= datetime(2025, 1, 25, tzinfo=timezone.utc) for b in out)


def test_window_outside_data():
    bars = _bars(50)
    out = filter_bars_by_date(bars,
                               start=datetime(2099, 1, 1, tzinfo=timezone.utc))
    assert out == []
