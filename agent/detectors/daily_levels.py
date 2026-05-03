"""Daily / weekly anchor levels (PDH, PDL, daily-mid, prior-week H/L).

These are the "draws on liquidity" most discretionary traders use to frame
the day. The agent already has dynamic detectors (zones, FVG, swings); this
module provides the *static* per-day reference levels you'd hand-draw on a
chart at the NY close:

    PDH   = previous trading day's high
    PDL   = previous trading day's low
    PDM   = midpoint of the previous day's range
    PWH   = previous week's high (Mon-Fri)
    PWL   = previous week's low

A trading "day" is bucketed by NY date (because the FX day rolls at 17:00 NY).
Bars are assumed UTC; the bucketing converts to NY before grouping.

Output is a per-bar list of :class:`DailyLevels`, one per bar, holding the
*currently active* anchors at that timestamp (so a bar at 09:00 NY sees the
prior trading day's H/L, not today's so-far H/L)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    from datetime import timezone
    NY_TZ = timezone(timedelta(hours=-5))

from agent.types import Bar


@dataclass
class DailyLevels:
    pdh: float | None = None
    pdl: float | None = None
    pdm: float | None = None
    pwh: float | None = None
    pwl: float | None = None
    pwm: float | None = None

    def levels_dict(self) -> dict[str, float]:
        return {k: v for k, v in {
            "PDH": self.pdh, "PDL": self.pdl, "PDM": self.pdm,
            "PWH": self.pwh, "PWL": self.pwl, "PWM": self.pwm,
        }.items() if v is not None}


def _ny_date(ts: datetime) -> date:
    if ts.tzinfo is None:
        from datetime import timezone
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(NY_TZ).date()


def _iso_week(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def compute_daily_levels(bars: list[Bar]) -> list[DailyLevels]:
    """Return one :class:`DailyLevels` per input bar, using only PRIOR-day data
    (no look-ahead). For bars before any complete prior day exists, the level
    fields are ``None``.

    Algorithm:
      1. First pass: bucket bars by NY date and accumulate (high, low) per day.
      2. Second pass: walk bars in order, emit the level set as of "yesterday".

    This is O(n); we don't care about per-bar pip cost since detection runs
    once at backtest start (and cheaply per-tick in live)."""
    if not bars:
        return []

    # Bucket high/low per NY day and per ISO week.
    daily_hi: dict[date, float] = {}
    daily_lo: dict[date, float] = {}
    weekly_hi: dict[tuple[int, int], float] = {}
    weekly_lo: dict[tuple[int, int], float] = {}

    for b in bars:
        d = _ny_date(b.time)
        w = _iso_week(d)
        daily_hi[d] = max(daily_hi.get(d, b.high), b.high)
        daily_lo[d] = min(daily_lo.get(d, b.low), b.low)
        weekly_hi[w] = max(weekly_hi.get(w, b.high), b.high)
        weekly_lo[w] = min(weekly_lo.get(w, b.low), b.low)

    sorted_days = sorted(daily_hi.keys())
    sorted_weeks = sorted(weekly_hi.keys())

    # Map each day -> prior trading day (skips weekends naturally because we
    # only have entries for days that had bars).
    prior_day = {}
    for i, d in enumerate(sorted_days):
        prior_day[d] = sorted_days[i - 1] if i > 0 else None
    prior_week = {}
    for i, w in enumerate(sorted_weeks):
        prior_week[w] = sorted_weeks[i - 1] if i > 0 else None

    out: list[DailyLevels] = []
    for b in bars:
        d = _ny_date(b.time)
        w = _iso_week(d)
        pd_, pw = prior_day.get(d), prior_week.get(w)

        levels = DailyLevels()
        if pd_ is not None:
            levels.pdh = daily_hi.get(pd_)
            levels.pdl = daily_lo.get(pd_)
            if levels.pdh is not None and levels.pdl is not None:
                levels.pdm = (levels.pdh + levels.pdl) / 2
        if pw is not None:
            levels.pwh = weekly_hi.get(pw)
            levels.pwl = weekly_lo.get(pw)
            if levels.pwh is not None and levels.pwl is not None:
                levels.pwm = (levels.pwh + levels.pwl) / 2
        out.append(levels)
    return out


def nearest_level(levels: DailyLevels, price: float, max_pips: float = 15.0) -> tuple[str, float] | None:
    """Return (label, price) of the nearest level within `max_pips`, or None.
    Used by the rules engine to tag a setup with `near_PDH` etc."""
    candidates = levels.levels_dict()
    if not candidates:
        return None
    best = min(candidates.items(), key=lambda kv: abs(kv[1] - price))
    if abs(best[1] - price) * 10000 <= max_pips:
        return best
    return None
