"""Mt5Feed missed-bar catch-up (2026-08-04 fix).

``Mt5Feed.poll_new_closed`` used to emit only the single NEWEST closed
bar per symbol. Any H4 close missed during a poll gap -- feed outage
(the Aug 3 DNS death), a VM pause, or a runtime restart -- was
silently skipped and never evaluated. Now every cached bar newer than
the per-symbol cursor is emitted, oldest first, and ``mark_seen``
(wired from ``state.json``'s ``last_bar_times`` by the runner) turns a
restart into a bounded catch-up instead of a gap.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.squad.feed import Mt5Feed
from agent.types import Bar, Timeframe

UTC = timezone.utc
START = datetime(2024, 1, 2, tzinfo=UTC)


def _bar(t: datetime) -> Bar:
    return Bar(time=t, open=1.10, high=1.11, low=1.09, close=1.105,
               volume=100.0, timeframe=Timeframe.H4)


def _series(n: int, start: datetime = START) -> list[Bar]:
    return [_bar(start + timedelta(hours=4 * i)) for i in range(n)]


def _feed_with_cache(bars: list[Bar], symbol: str = "EURUSD") -> Mt5Feed:
    feed = Mt5Feed(broker=object(), symbols=(symbol,))
    feed._cache[symbol] = list(bars)
    return feed


def test_first_poll_without_cursor_emits_only_newest():
    """Fresh boot: history is prepare() hydration, not live tape."""
    bars = _series(10)
    feed = _feed_with_cache(bars)
    out = feed.poll_new_closed()
    assert len(out) == 1
    assert out[0].bar.time == bars[-1].time


def test_poll_gap_emits_every_missed_bar_ascending():
    bars = _series(10)
    feed = _feed_with_cache(bars)
    feed.poll_new_closed()  # cursor now at bars[-1]

    # Three H4 closes arrive while the loop was not polling.
    late = _series(3, start=bars[-1].time + timedelta(hours=4))
    feed._cache["EURUSD"] = bars[1:] + late  # sliding window
    out = feed.poll_new_closed()
    assert [fb.bar.time for fb in out] == [b.time for b in late], (
        "every missed close must be emitted, oldest first -- the old "
        "behavior dropped all but the newest"
    )
    # Cursor advanced; nothing re-emitted next poll.
    assert feed.poll_new_closed() == []


def test_mark_seen_resume_turns_restart_into_catchup():
    bars = _series(10)
    feed = _feed_with_cache(bars)
    # Runner resumed from state.json: last processed bar was bars[6].
    feed.mark_seen("EURUSD", bars[6].time)
    out = feed.poll_new_closed()
    assert [fb.bar.time for fb in out] == [b.time for b in bars[7:]], (
        "restart must catch up every close since the persisted cursor"
    )


def test_no_new_bars_emits_nothing():
    bars = _series(5)
    feed = _feed_with_cache(bars)
    feed.poll_new_closed()
    assert feed.poll_new_closed() == []


def test_multi_symbol_output_sorted_by_time_then_symbol():
    feed = Mt5Feed(broker=object(), symbols=("EURUSD", "GBPUSD"))
    e = _series(6)
    g = _series(6)
    feed._cache["EURUSD"] = e
    feed._cache["GBPUSD"] = g
    feed.mark_seen("EURUSD", e[3].time)
    feed.mark_seen("GBPUSD", g[4].time)
    out = feed.poll_new_closed()
    assert [(fb.symbol, fb.bar.time) for fb in out] == [
        ("EURUSD", e[4].time),
        ("EURUSD", e[5].time),
        ("GBPUSD", g[5].time),
    ]
