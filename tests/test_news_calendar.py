"""Tests for `agent.news.calendar`.

Covers:
    * Pure XML parsing (with the offline fixture under fixtures/news/).
    * Cache freshness window (TTL) -- skip refetch when fresh, refetch
      when stale, force_refresh override.
    * Fetcher injection so CI never hits the network.
    * Graceful fallback to stale cache when the fetcher raises.
    * Roundtrip serialization (NewsEvent.to_dict / from_dict).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.news.calendar import (
    DEFAULT_TTL_SECONDS,
    NewsEvent,
    fetch_calendar,
    filter_events,
    load_calendar,
    parse_calendar_xml,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "news" / "ff_calendar_sample.xml"


def _read_fixture() -> str:
    return FIXTURE.read_text()


def test_fixture_exists():
    assert FIXTURE.exists(), "Offline FF calendar fixture is missing -- CI will break without it"


def test_parse_calendar_xml_basic_shape():
    events = parse_calendar_xml(_read_fixture())
    assert len(events) == 8
    titles = [e.title for e in events]
    assert "FOMC Statement" in titles
    assert "Core CPI m/m" in titles
    assert "ECB Press Conference" in titles


def test_parse_calendar_xml_currency_and_impact():
    events = parse_calendar_xml(_read_fixture())
    by_title = {e.title: e for e in events}
    assert by_title["FOMC Statement"].currency == "USD"
    assert by_title["FOMC Statement"].impact == "High"
    assert by_title["ECB Press Conference"].currency == "EUR"
    assert by_title["BOJ Outlook Report"].currency == "JPY"


def test_parse_calendar_xml_time_is_utc():
    events = parse_calendar_xml(_read_fixture())
    fomc = next(e for e in events if e.title == "FOMC Statement")
    assert fomc.time_utc is not None
    assert fomc.time_utc.tzinfo is not None
    assert fomc.time_utc.tzinfo.utcoffset(fomc.time_utc) == timedelta(0)
    # 05-14-2026 at 2:00pm GMT
    assert fomc.time_utc == datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)


def test_parse_calendar_xml_all_day_entry():
    events = parse_calendar_xml(_read_fixture())
    holiday = next(e for e in events if e.title == "French Bank Holiday")
    assert holiday.all_day is True
    assert holiday.time_utc is None
    assert holiday.impact == "Holiday"


def test_parse_calendar_xml_tentative_entry():
    events = parse_calendar_xml(_read_fixture())
    tentative = next(e for e in events if e.title == "FOMC Member Speaks")
    # Tentative -> no specific time, not all-day either.
    assert tentative.time_utc is None
    assert tentative.all_day is False


def test_parse_calendar_xml_empty_input():
    assert parse_calendar_xml("") == []
    assert parse_calendar_xml("   ") == []


def test_parse_calendar_xml_malformed_input_returns_empty():
    # Garbage XML: parser logs warning and returns [], not raises.
    out = parse_calendar_xml("<not really><xml")
    assert out == []


def test_news_event_roundtrip_serialization():
    e = NewsEvent(
        time_utc=datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc),
        currency="USD",
        impact="High",
        title="FOMC Statement",
        all_day=False,
    )
    d = e.to_dict()
    e2 = NewsEvent.from_dict(d)
    assert e == e2


def test_news_event_roundtrip_all_day():
    e = NewsEvent(time_utc=None, currency="EUR", impact="Holiday", title="Bank Holiday", all_day=True)
    e2 = NewsEvent.from_dict(e.to_dict())
    assert e == e2
    assert e2.time_utc is None


def test_filter_events_by_currency():
    events = parse_calendar_xml(_read_fixture())
    usd_only = filter_events(events, currencies={"USD"})
    assert all(e.currency == "USD" for e in usd_only)
    assert len(usd_only) > 0
    eur_only = filter_events(events, currencies={"EUR"})
    assert all(e.currency == "EUR" for e in eur_only)


def test_filter_events_by_impact():
    events = parse_calendar_xml(_read_fixture())
    high_only = filter_events(events, impact_levels={"High"})
    assert all(e.impact == "High" for e in high_only)
    assert any(e.title == "FOMC Statement" for e in high_only)


def test_filter_events_by_time_window():
    events = parse_calendar_xml(_read_fixture())
    # Only events on 05-14-2026 (FOMC + press conference)
    after = datetime(2026, 5, 14, 0, 0, tzinfo=timezone.utc)
    before = datetime(2026, 5, 14, 23, 59, tzinfo=timezone.utc)
    windowed = filter_events(events, after=after, before=before)
    titles = {e.title for e in windowed}
    assert "FOMC Statement" in titles
    assert "FOMC Press Conference" in titles
    # All-day / tentative entries are skipped when a time window is supplied.
    assert "French Bank Holiday" not in titles


def test_fetch_calendar_uses_fresh_cache(tmp_path):
    cache = tmp_path / "news.json"
    fixture_xml = _read_fixture()
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)

    calls = {"n": 0}

    def fake_fetcher(_url):
        calls["n"] += 1
        return fixture_xml

    # First call: cache empty, must fetch.
    e1 = fetch_calendar(cache_path=cache, now=now, fetcher=fake_fetcher)
    assert calls["n"] == 1
    assert len(e1) == 8

    # Second call: same `now`, fresh cache -> no refetch.
    e2 = fetch_calendar(cache_path=cache, now=now, fetcher=fake_fetcher)
    assert calls["n"] == 1
    assert len(e2) == 8


def test_fetch_calendar_refreshes_when_stale(tmp_path):
    cache = tmp_path / "news.json"
    fixture_xml = _read_fixture()
    t0 = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    calls = {"n": 0}

    def fake_fetcher(_url):
        calls["n"] += 1
        return fixture_xml

    fetch_calendar(cache_path=cache, now=t0, fetcher=fake_fetcher)
    assert calls["n"] == 1

    # 7 hours later -- past the default 6h TTL -- should refetch.
    t1 = t0 + timedelta(hours=7)
    fetch_calendar(cache_path=cache, now=t1, fetcher=fake_fetcher)
    assert calls["n"] == 2


def test_fetch_calendar_force_refresh(tmp_path):
    cache = tmp_path / "news.json"
    fixture_xml = _read_fixture()
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    calls = {"n": 0}

    def fake_fetcher(_url):
        calls["n"] += 1
        return fixture_xml

    fetch_calendar(cache_path=cache, now=now, fetcher=fake_fetcher)
    assert calls["n"] == 1
    fetch_calendar(cache_path=cache, now=now, fetcher=fake_fetcher, force_refresh=True)
    assert calls["n"] == 2


def test_fetch_calendar_falls_back_to_stale_on_error(tmp_path):
    cache = tmp_path / "news.json"
    fixture_xml = _read_fixture()
    t0 = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)

    fetch_calendar(cache_path=cache, now=t0, fetcher=lambda _u: fixture_xml)

    # Network broken; cache is stale.
    t1 = t0 + timedelta(days=2)

    def broken(_url):
        raise RuntimeError("network down")

    events = fetch_calendar(cache_path=cache, now=t1, fetcher=broken)
    # Falls back to the cached events instead of raising.
    assert len(events) == 8


def test_fetch_calendar_missing_cache_and_broken_fetcher(tmp_path):
    cache = tmp_path / "news.json"

    def broken(_url):
        raise RuntimeError("offline")

    events = fetch_calendar(cache_path=cache, fetcher=broken)
    assert events == []


def test_load_calendar_reads_cached_events(tmp_path):
    cache = tmp_path / "news.json"
    fixture_xml = _read_fixture()
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    fetch_calendar(cache_path=cache, now=now, fetcher=lambda _u: fixture_xml)

    events = load_calendar(cache)
    assert len(events) == 8
    assert any(e.title == "FOMC Statement" for e in events)


def test_load_calendar_missing_returns_empty(tmp_path):
    assert load_calendar(tmp_path / "does-not-exist.json") == []


def test_default_ttl_is_six_hours():
    # Sanity check on the documented default; surface regressions early.
    assert DEFAULT_TTL_SECONDS == 6 * 60 * 60
