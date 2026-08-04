"""Tests for the log-timestamp timezone normalization (intake 2026-08-04).

VM logs are written in local time (Python logging default) but the review
tooling labeled them UTC unconverted — a +1h summer skew found in the
2026-08-04 weekly review. `_parse_line_ts` now converts LOG_TZ -> UTC.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts import compile_review_bundle as crb  # noqa: E402

LINE = "2026-08-03 15:07:12 INFO     agent.live.signal_loop: heartbeat: balance=$1003.88"


def _with_log_tz(tz, line=LINE):
    old = crb.LOG_TZ
    crb.LOG_TZ = tz
    try:
        return crb._parse_line_ts(line)
    finally:
        crb.LOG_TZ = old


def test_utc_logs_parse_identically():
    ts = _with_log_tz(timezone.utc)
    assert ts == datetime(2026, 8, 3, 15, 7, 12, tzinfo=timezone.utc)


def test_uk_summer_logs_shift_back_one_hour():
    # The Aug 3 incident: log says 15:07 UK local -> real 14:07 UTC.
    ts = _with_log_tz(timezone(timedelta(hours=1)))
    assert ts == datetime(2026, 8, 3, 14, 7, 12, tzinfo=timezone.utc)


def test_default_uses_machine_local_tz():
    ts = _with_log_tz(None)
    expected = (datetime(2026, 8, 3, 15, 7, 12)
                .astimezone().astimezone(timezone.utc))
    assert ts == expected
    assert ts.tzinfo == timezone.utc


def test_non_timestamp_line_returns_none():
    assert _with_log_tz(timezone.utc, "Auto-kill: daily drawdown") is None
