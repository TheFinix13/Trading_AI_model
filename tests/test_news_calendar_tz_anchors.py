"""A004 -- calendar-vs-broker timezone verification, pinned.

Verified live on 2026-07-24 against the real weekly feed
(https://nfs.faireconomy.media/ff_calendar_thisweek.xml):

* US Unemployment Claims -- ALWAYS released 08:30 US-Eastern, which in
  July (EDT, UTC-4) is 12:30 UTC. The feed row carried ``12:30pm``.
* S&P Global Flash Manufacturing PMI -- released 09:45 US-Eastern =
  13:45 UTC in July. The feed row carried ``1:45pm``.

Both anchors land exactly on their known UTC schedule, so the feed
publishes GMT/UTC and the parser's ``tzinfo=timezone.utc`` tagging in
``_parse_event_time`` is CORRECT -- not US-Eastern as the audit
hypothesised. (Broker side, verified same day on the VM: the Exness
Trial MT5 server clock reads UTC+0 and H4 bars close on the
00/04/08/12/16/20 UTC grid, so ``fromtimestamp(..., tz=timezone.utc)``
in the broker layer is also correct. Full note:
``reviews/audits/2026-07-24-a004-calendar-tz-verification.md``.)

These tests pin the anchor rows as captured, so any future parser
change that shifts event times off their known UTC schedule fails
loudly here.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.news.calendar import parse_calendar_xml  # noqa: E402

# Rows as captured from the live feed on 2026-07-24 (values trimmed to
# the fields the parser reads).
_FEED_SNIPPET = """<?xml version="1.0" encoding="UTF-8"?>
<weeklyevents>
  <event>
    <title>Unemployment Claims</title>
    <country>USD</country>
    <date>07-23-2026</date>
    <time>12:30pm</time>
    <impact>Medium</impact>
  </event>
  <event>
    <title>Flash Manufacturing PMI</title>
    <country>USD</country>
    <date>07-24-2026</date>
    <time>1:45pm</time>
    <impact>Medium</impact>
  </event>
</weeklyevents>
"""


class TestFeedTimesAreUtc:
    def _events(self):
        evs = parse_calendar_xml(_FEED_SNIPPET)
        return {e.title: e for e in evs}

    def test_unemployment_claims_anchor(self) -> None:
        """08:30 US-Eastern (EDT) == 12:30 UTC -- the feed row said
        12:30pm, so parsing it as UTC must yield exactly 12:30Z."""
        ev = self._events()["Unemployment Claims"]
        assert ev.time_utc == datetime(2026, 7, 23, 12, 30,
                                       tzinfo=timezone.utc)

    def test_flash_pmi_anchor(self) -> None:
        """09:45 US-Eastern (EDT) == 13:45 UTC."""
        ev = self._events()["Flash Manufacturing PMI"]
        assert ev.time_utc == datetime(2026, 7, 24, 13, 45,
                                       tzinfo=timezone.utc)

    def test_wrong_hypothesis_would_have_failed(self) -> None:
        """The audit's feared failure mode: if the feed were US-Eastern,
        the Claims anchor would parse to 16:30 UTC (12:30 + 4h). Assert
        we are 4 hours away from that world."""
        ev = self._events()["Unemployment Claims"]
        eastern_world = datetime(2026, 7, 23, 16, 30, tzinfo=timezone.utc)
        assert (eastern_world - ev.time_utc).total_seconds() == 4 * 3600
