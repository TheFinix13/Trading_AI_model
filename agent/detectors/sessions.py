"""Session labelling for FX bars (Asia / London / NY / overlap / off-session).

The session a bar belongs to is one of the most under-used signals in retail
backtesting — but it's central to how discretionary traders read the chart
("the London open swept liquidity then NY ran the real move"). We label
every bar with its NY-time session bucket so:

  * downstream detectors can ask "did this sweep happen in the London kill
    zone?" when scoring quality;
  * the rules engine can stack a `session_<bucket>` confluence on top of
    other signals;
  * the narrative explainer can say "London-NY overlap" instead of leaking
    raw UTC times the user has to convert manually.

Conventions (NY local time, DST-aware via zoneinfo):

  Asia            19:00 -> 03:00  (low-vol accumulation)
  London          03:00 -> 08:00  (London-only, before NY opens)
  London-NY OL    08:00 -> 12:00  (highest volatility window of the day)
  NY              12:00 -> 17:00  (NY-only afternoon)
  Off-session     17:00 -> 19:00  (~rollover dead-zone)

These match the ICT "kill zones" most discretionary traders quote without
forcing the agent to commit to a single trading style.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Literal

try:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - fallback for very old Python
    from datetime import timezone, timedelta
    NY_TZ = timezone(timedelta(hours=-5))

from agent.types import Bar

SessionLabel = Literal["asia", "london", "london_ny_overlap", "ny", "off"]

# NY-local session boundaries (start, end). End is exclusive.
_BOUNDS: list[tuple[time, time, SessionLabel]] = [
    (time(19, 0), time(23, 59, 59), "asia"),
    (time(0, 0),  time(3, 0),       "asia"),
    (time(3, 0),  time(8, 0),       "london"),
    (time(8, 0),  time(12, 0),      "london_ny_overlap"),
    (time(12, 0), time(17, 0),      "ny"),
    (time(17, 0), time(19, 0),      "off"),
]


def label_session(ts: datetime) -> SessionLabel:
    """Return the session bucket for a bar timestamp.

    `ts` may be naive (assumed UTC) or timezone-aware; we always convert to
    America/New_York before bucketing so DST is handled correctly."""
    if ts.tzinfo is None:
        from datetime import timezone
        ts = ts.replace(tzinfo=timezone.utc)
    ny = ts.astimezone(NY_TZ).timetz().replace(tzinfo=None)
    for start, end, label in _BOUNDS:
        if start <= ny < end:
            return label
    return "off"


def label_bars(bars: list[Bar]) -> list[SessionLabel]:
    """Vectorised convenience: one label per bar, same length as input."""
    return [label_session(b.time) for b in bars]


def is_kill_zone(label: SessionLabel) -> bool:
    """True for the high-volatility windows ICT-style traders prefer to trade."""
    return label in ("london", "london_ny_overlap", "ny")
