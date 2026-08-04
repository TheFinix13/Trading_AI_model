"""Tests for the overdue-bar-close warning (intake 2026-08-04).

During the Aug 3 DNS outage the agents ran healthy but signal-blind for
3.5h: a due H4 close never appeared in the broker data, and the loop
skipped it with no trace. `_maybe_warn_close_overdue` surfaces that state
as a WARNING in the daily log, weekend-aware and rate-limited to once per
timeframe period.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.live.signal_loop import SignalLoop  # noqa: E402

# A Tuesday, well inside market hours.
TUE_10 = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)


def make_loop() -> SignalLoop:
    """Bare loop object — only the overdue-watchdog state is needed."""
    loop = SignalLoop.__new__(SignalLoop)
    loop._close_seen_wallclock = {}
    loop._overdue_warned_at = {}
    return loop


def n_warnings(caplog) -> int:
    return sum(1 for r in caplog.records
               if r.levelno == logging.WARNING and "CLOSE OVERDUE" in r.message)


# ---------------------------------------------------------------------------
# Weekend window
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dt,closed", [
    (datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc), False),   # Tue
    (datetime(2026, 8, 7, 20, 59, tzinfo=timezone.utc), False),  # Fri pre-close
    (datetime(2026, 8, 7, 21, 0, tzinfo=timezone.utc), True),    # Fri close
    (datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc), True),    # Sat
    (datetime(2026, 8, 9, 21, 59, tzinfo=timezone.utc), True),   # Sun pre-open
    (datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc), False),   # Sun open
])
def test_fx_market_closed_window(dt, closed):
    assert SignalLoop._fx_market_closed(dt) is closed


# ---------------------------------------------------------------------------
# Overdue warning behaviour
# ---------------------------------------------------------------------------

def test_first_call_initializes_without_warning(caplog):
    loop = make_loop()
    with caplog.at_level(logging.WARNING):
        loop._maybe_warn_close_overdue("H4", now=TUE_10)
    assert n_warnings(caplog) == 0
    assert loop._close_seen_wallclock["H4"] == TUE_10


def test_no_warning_inside_grace(caplog):
    loop = make_loop()
    loop._close_seen_wallclock["H4"] = TUE_10
    with caplog.at_level(logging.WARNING):
        # 4h + 29min: still inside the 4h TF + 30min grace budget
        loop._maybe_warn_close_overdue(
            "H4", now=TUE_10 + timedelta(hours=4, minutes=29))
    assert n_warnings(caplog) == 0


def test_warning_fires_when_overdue_and_rate_limits(caplog):
    loop = make_loop()
    loop._close_seen_wallclock["H4"] = TUE_10
    overdue = TUE_10 + timedelta(hours=4, minutes=31)
    with caplog.at_level(logging.WARNING):
        loop._maybe_warn_close_overdue("H4", now=overdue)
        # immediate re-poll: rate-limited, no duplicate
        loop._maybe_warn_close_overdue("H4", now=overdue + timedelta(minutes=1))
    assert n_warnings(caplog) == 1
    with caplog.at_level(logging.WARNING):
        # one full TF period later, still stalled: warns again
        loop._maybe_warn_close_overdue("H4", now=overdue + timedelta(hours=4, minutes=1))
    assert n_warnings(caplog) == 2


def test_fresh_close_resets_stall_clock(caplog):
    loop = make_loop()
    loop._close_seen_wallclock["H4"] = TUE_10 + timedelta(hours=4)  # new close seen
    with caplog.at_level(logging.WARNING):
        loop._maybe_warn_close_overdue(
            "H4", now=TUE_10 + timedelta(hours=5))
    assert n_warnings(caplog) == 0


def test_weekend_suppresses_and_resets(caplog):
    loop = make_loop()
    # Last close Friday 20:00 UTC; the loop keeps polling every few
    # seconds through the weekend, so the final closed-market poll lands
    # just before the Sunday reopen.
    fri_20 = datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)
    loop._close_seen_wallclock["H4"] = fri_20
    sat_noon = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    sun_2155 = datetime(2026, 8, 9, 21, 55, tzinfo=timezone.utc)
    sun_2330 = datetime(2026, 8, 9, 23, 30, tzinfo=timezone.utc)
    with caplog.at_level(logging.WARNING):
        loop._maybe_warn_close_overdue("H4", now=sat_noon)   # closed: no warn
        loop._maybe_warn_close_overdue("H4", now=sun_2155)   # closed: no warn
        loop._maybe_warn_close_overdue("H4", now=sun_2330)   # open 1.5h: fine
    assert n_warnings(caplog) == 0
    # The stall clock was parked at the last closed-market poll, so the
    # 49h weekend gap never counts as a stall.
    assert loop._close_seen_wallclock["H4"] == sun_2155
