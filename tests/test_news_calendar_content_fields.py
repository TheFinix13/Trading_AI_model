"""Sae v2 S0 (D141): the calendar must carry event CONTENT, not just timing.

Until 2026-08-04 `parse_calendar_xml` dropped the feed's `<forecast>` /
`<previous>` fields, so nothing downstream could ever compute a surprise.
These tests pin: (a) the parser keeps them verbatim, (b) the JSON cache
round-trips them (old caches without the fields still load), and (c) the
`parse_numeric` / `surprise` helpers handle FF's value conventions.
"""
from __future__ import annotations

from agent.news.calendar import NewsEvent, parse_calendar_xml, parse_numeric

_XML = """<?xml version="1.0" encoding="utf-8"?>
<weeklyevents>
  <event>
    <title>Non-Farm Employment Change</title>
    <country>USD</country>
    <date><![CDATA[08-07-2026]]></date>
    <time><![CDATA[8:30am]]></time>
    <impact><![CDATA[High]]></impact>
    <forecast><![CDATA[185K]]></forecast>
    <previous><![CDATA[206K]]></previous>
  </event>
  <event>
    <title>FOMC Statement</title>
    <country>USD</country>
    <date><![CDATA[08-05-2026]]></date>
    <time><![CDATA[6:00pm]]></time>
    <impact><![CDATA[High]]></impact>
    <forecast />
    <previous />
  </event>
</weeklyevents>
"""


def test_parser_keeps_forecast_and_previous_verbatim():
    events = parse_calendar_xml(_XML)
    nfp = next(e for e in events if "Non-Farm" in e.title)
    assert nfp.forecast == "185K"
    assert nfp.previous == "206K"
    assert nfp.actual is None  # weekly feed never carries actuals

    fomc = next(e for e in events if e.title == "FOMC Statement")
    assert fomc.forecast is None  # empty element -> None, not ""
    assert fomc.previous is None


def test_cache_round_trip_and_legacy_cache_tolerance():
    events = parse_calendar_xml(_XML)
    nfp = next(e for e in events if "Non-Farm" in e.title)
    assert NewsEvent.from_dict(nfp.to_dict()) == nfp

    # A pre-S0 cache row has no content keys at all -- must still load.
    legacy = {
        "time_utc": "2026-08-07T12:30:00+00:00",
        "currency": "USD",
        "impact": "High",
        "title": "Non-Farm Employment Change",
        "all_day": False,
    }
    ev = NewsEvent.from_dict(legacy)
    assert ev.forecast is None and ev.previous is None and ev.actual is None


def test_parse_numeric_ff_conventions():
    assert parse_numeric("185K") == 185_000.0
    assert parse_numeric("2.1M") == 2_100_000.0
    assert parse_numeric("0.2%") == 0.2
    assert parse_numeric("-4.0%") == -4.0
    assert parse_numeric("<0.1%") == 0.1
    assert parse_numeric("4.25%") == 4.25
    assert parse_numeric("1,234") == 1234.0
    assert parse_numeric("") is None
    assert parse_numeric(None) is None
    assert parse_numeric("Tentative") is None


def test_surprise_needs_both_sides_and_same_units():
    ev = NewsEvent(
        time_utc=None, currency="USD", impact="High", title="NFP",
        forecast="185K", actual="220K",
    )
    assert ev.surprise == 35_000.0

    no_actual = NewsEvent(
        time_utc=None, currency="USD", impact="High", title="NFP",
        forecast="185K",
    )
    assert no_actual.surprise is None
