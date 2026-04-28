"""Session and no-trade window filters."""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from agent.config import NoTradeWindow

# Mapping for human-readable day filtering. weekday() returns 0=Mon..6=Sun.
DAY_NAME_TO_INDEX = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


def is_no_trade_day(now: datetime, no_trade_days: list[str], tz: str = "UTC") -> bool:
    """Block entire days based on local-time weekday. Useful for systematic risk-off
    days the journal has shown to be unprofitable (e.g. Wednesday on EURUSD)."""
    if not no_trade_days:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    local = now.astimezone(ZoneInfo(tz))
    blocked: set[int] = set()
    for raw in no_trade_days:
        idx = DAY_NAME_TO_INDEX.get(str(raw).lower().strip())
        if idx is not None:
            blocked.add(idx)
    return local.weekday() in blocked


def in_no_trade_window(now: datetime, windows: list[NoTradeWindow], tz: str) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    local = now.astimezone(ZoneInfo(tz))
    for w in windows:
        if local.weekday() != w.day_of_week:
            continue
        sh, sm = map(int, w.from_.split(":"))
        eh, em = map(int, w.to.split(":"))
        if time(sh, sm) <= local.time() <= time(eh, em):
            return True
    return False


def in_active_session(now: datetime, sessions: list[str] = None) -> bool:
    """Return True if current UTC time is within any of the requested sessions.
    sessions may include: 'london', 'ny', 'london_ny_overlap'.
    Default: any of the three is acceptable."""
    if sessions is None:
        sessions = ["london", "ny", "london_ny_overlap"]
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    h = now.astimezone(ZoneInfo("UTC")).hour
    london = 7 <= h < 16
    ny = 13 <= h < 22
    overlap = 13 <= h < 16
    if "london_ny_overlap" in sessions and overlap:
        return True
    if "london" in sessions and london:
        return True
    if "ny" in sessions and ny:
        return True
    return False
