"""Tests for `agent.news.blackout` and `agent.rules.news_filter`.

Covers:
    * Window edges (event - before, event + after) inclusive.
    * Currency filter (USD/EUR vs other).
    * Impact filter (High vs Medium / Low).
    * `next_blackout` lookahead.
    * `NewsAwareRuleEngine` middleware short-circuits the base engine.
    * `filter_setup` functional helper.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from agent.news.blackout import (
    DEFAULT_AFTER_MIN,
    DEFAULT_BEFORE_MIN,
    is_news_blackout,
    next_blackout,
)
from agent.news.calendar import NewsEvent
from agent.rules.news_filter import NewsAwareRuleEngine, filter_setup


def _ev(when: datetime, currency: str = "USD", impact: str = "High", title: str = "FOMC") -> NewsEvent:
    return NewsEvent(time_utc=when, currency=currency, impact=impact, title=title)


def test_blackout_inside_window_before_event():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    events = [_ev(event_t)]
    # 10 minutes before the event -- inside default 15-min before window.
    now = event_t - timedelta(minutes=10)
    assert is_news_blackout(now, events) is True


def test_blackout_inside_window_after_event():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    events = [_ev(event_t)]
    now = event_t + timedelta(minutes=10)
    assert is_news_blackout(now, events) is True


def test_blackout_at_exact_event_time():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    events = [_ev(event_t)]
    assert is_news_blackout(event_t, events) is True


def test_blackout_at_window_boundary_inclusive():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    events = [_ev(event_t)]
    # Exact lower edge: 15 min before.
    assert is_news_blackout(event_t - timedelta(minutes=DEFAULT_BEFORE_MIN), events) is True
    assert is_news_blackout(event_t + timedelta(minutes=DEFAULT_AFTER_MIN), events) is True


def test_no_blackout_outside_window():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    events = [_ev(event_t)]
    # 16 minutes before -- 1 minute outside window.
    assert is_news_blackout(event_t - timedelta(minutes=16), events) is False
    assert is_news_blackout(event_t + timedelta(minutes=16), events) is False
    # 2 hours away -- comfortably clear.
    assert is_news_blackout(event_t + timedelta(hours=2), events) is False


def test_currency_filter_skips_jpy_event():
    # Even a high-impact JPY event should not block a EURUSD trade.
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    events = [_ev(event_t, currency="JPY")]
    assert is_news_blackout(event_t, events, currencies={"USD", "EUR"}) is False
    # ... but if we explicitly include JPY, it does block.
    assert is_news_blackout(event_t, events, currencies={"JPY"}) is True


def test_impact_filter_skips_medium_when_floor_is_high():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    events = [_ev(event_t, impact="Medium")]
    assert is_news_blackout(event_t, events, impact_min="High") is False
    # Lowering the floor catches it.
    assert is_news_blackout(event_t, events, impact_min="Medium") is True


def test_impact_explicit_set_overrides_floor_semantics():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    events = [_ev(event_t, impact="Medium"), _ev(event_t + timedelta(hours=4), impact="High")]
    # Restrict to Medium only.
    assert is_news_blackout(event_t, events, impact_min={"Medium"}) is True
    assert is_news_blackout(event_t + timedelta(hours=4), events, impact_min={"Medium"}) is False


def test_blackout_skips_all_day_entries():
    # All-day Holiday entries have time_utc=None and must not match
    # the timed-window logic (use is_all_day_blackout for those).
    e = NewsEvent(time_utc=None, currency="USD", impact="Holiday", title="July 4th", all_day=True)
    now = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    assert is_news_blackout(now, [e]) is False


def test_naive_datetime_is_treated_as_utc():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    events = [_ev(event_t)]
    naive_now = datetime(2026, 5, 14, 14, 5)  # 5 min after, naive
    assert is_news_blackout(naive_now, events) is True


def test_empty_events_returns_false():
    assert is_news_blackout(datetime.now(timezone.utc), []) is False


def test_custom_window_minutes():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    events = [_ev(event_t)]
    now = event_t - timedelta(minutes=25)
    assert is_news_blackout(now, events, before_min=15) is False
    assert is_news_blackout(now, events, before_min=30) is True


def test_next_blackout_picks_nearest_future_event():
    base = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    events = [
        _ev(base + timedelta(hours=2), title="CPI"),
        _ev(base + timedelta(hours=1), title="FOMC"),  # closer
        _ev(base + timedelta(hours=5), title="ECB", currency="EUR"),
    ]
    nxt = next_blackout(base, events)
    assert nxt is not None
    assert nxt.title == "FOMC"


def test_next_blackout_skips_past_events():
    base = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    events = [
        _ev(base - timedelta(hours=1), title="CPI"),  # past
        _ev(base + timedelta(hours=3), title="FOMC"),
    ]
    nxt = next_blackout(base, events)
    assert nxt is not None
    assert nxt.title == "FOMC"


def test_next_blackout_respects_horizon():
    base = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    events = [_ev(base + timedelta(hours=72), title="FOMC")]
    assert next_blackout(base, events, horizon_hours=24) is None
    assert next_blackout(base, events, horizon_hours=96) is not None


def test_next_blackout_returns_none_when_calendar_empty():
    assert next_blackout(datetime.now(timezone.utc), []) is None


# ---------------------------------------------------------------------------
# NewsAwareRuleEngine middleware
# ---------------------------------------------------------------------------


@dataclass
class _FakeBar:
    time: datetime


class _FakeCtx:
    def __init__(self, times: list[datetime]):
        self.bars = [_FakeBar(t) for t in times]


class _FakeEngine:
    """Records calls and returns a sentinel Setup object so the test can
    distinguish 'engine ran' from 'engine short-circuited'."""

    SENTINEL = object()

    def __init__(self):
        self.cfg = object()  # opaque
        self.calls = 0

    def evaluate_precomputed(self, ctx, at_index):
        self.calls += 1
        return _FakeEngine.SENTINEL

    def evaluate(self, bars, at_index):
        self.calls += 1
        return _FakeEngine.SENTINEL


def test_middleware_blocks_inside_blackout_window():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    base = _FakeEngine()
    eng = NewsAwareRuleEngine(base, events=[_ev(event_t)])
    ctx = _FakeCtx([event_t - timedelta(minutes=5)])
    result = eng.evaluate_precomputed(ctx, 0)
    assert result is None
    assert base.calls == 0
    assert eng.stats.blocked == 1


def test_middleware_passes_through_outside_window():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    base = _FakeEngine()
    eng = NewsAwareRuleEngine(base, events=[_ev(event_t)])
    ctx = _FakeCtx([event_t - timedelta(hours=3)])
    result = eng.evaluate_precomputed(ctx, 0)
    assert result is _FakeEngine.SENTINEL
    assert base.calls == 1
    assert eng.stats.blocked == 0


def test_middleware_disabled_flag_skips_filter():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    base = _FakeEngine()
    eng = NewsAwareRuleEngine(base, events=[_ev(event_t)], enabled=False)
    ctx = _FakeCtx([event_t])
    result = eng.evaluate_precomputed(ctx, 0)
    # When disabled, even a perfect-time-match still goes through.
    assert result is _FakeEngine.SENTINEL
    assert eng.stats.blocked == 0


def test_middleware_evaluate_slow_path_also_filters():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    base = _FakeEngine()
    eng = NewsAwareRuleEngine(base, events=[_ev(event_t)])
    bars = [_FakeBar(event_t)]
    result = eng.evaluate(bars, 0)
    assert result is None
    assert eng.stats.blocked == 1


def test_filter_setup_helper_drops_inside_window():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    sentinel = object()
    out = filter_setup(sentinel, when=event_t, events=[_ev(event_t)])
    assert out is None


def test_filter_setup_helper_passes_outside_window():
    event_t = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    sentinel = object()
    out = filter_setup(sentinel, when=event_t + timedelta(hours=3), events=[_ev(event_t)])
    assert out is sentinel


def test_filter_setup_passes_through_none():
    out = filter_setup(None, when=datetime.now(timezone.utc), events=[])
    assert out is None
