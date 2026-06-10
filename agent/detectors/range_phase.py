"""ICT "power-of-three" range-phase tagging.

Discretionary traders read the day in three acts:

  1. **Accumulation**  — quiet, low-vol, builds the range. Usually Asia.
  2. **Manipulation**  — sweeps one side of that range to grab stops. Usually
                          London open.
  3. **Distribution**  — the real directional move. Usually NY.

Tagging each bar with which phase it sits in lets:
  * the rules engine reject entries detected during accumulation (low conviction);
  * the narrative explainer say "London swept Asia high then NY ran lower" in
    plain English;
  * the ML scorer learn that confluences in distribution > confluences in
    accumulation.

This module is intentionally heuristic — it doesn't try to detect the *true*
phase via volume profile (we'd need tick data). Instead it combines:

  * NY-time session label (from :mod:`agent.detectors.sessions`)
  * Whether the day's range so far has been swept (using :mod:`liquidity_sweep`)
  * Whether displacement (large body relative to ATR) has happened

The result is a pragmatic tag good enough to filter weak setups and to colour
the narrative; it does not pretend to be a market-microstructure model.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from agent.detectors.daily_levels import _ny_date
from agent.detectors.sessions import label_session
from agent.types import Bar

Phase = Literal["accumulation", "manipulation", "distribution", "off"]


@dataclass
class RangePhase:
    phase: Phase
    day_high_so_far: float
    day_low_so_far: float
    swept_high: bool   # has today's bars taken out yesterday's high?
    swept_low: bool
    displacement_pips: float  # max single-bar body so far today, in pips


def label_range_phases(bars: list[Bar],
                        displacement_atr_mult: float = 1.5,
                        atr_period: int = 14) -> list[RangePhase]:
    """Walk bars in order, emit one :class:`RangePhase` per bar with the
    phase as observed *up to that bar* (no look-ahead).

    Phase rules:
      * ``off``           : weekends or off-session bars (17-19 NY).
      * ``accumulation``  : Asia session, no level sweep yet today.
      * ``manipulation``  : London / overlap, OR a sweep has happened today
                            but no displacement candle yet.
      * ``distribution``  : NY session AND the day already had its sweep AND
                            we've seen a body >= displacement_atr_mult * ATR.

    The ATR is computed on the *prior* `atr_period` bars to avoid look-ahead.
    """
    if not bars:
        return []

    out: list[RangePhase] = []
    pip = 0.0001

    # rolling ATR (simple, not Wilder — close enough for phase tagging)
    atr_window: list[float] = []
    last_atr = 0.0

    # per-day state
    cur_day: date | None = None
    day_hi = day_lo = 0.0
    prior_day_hi = prior_day_lo = None
    swept_hi = swept_lo = False
    max_body_pips = 0.0
    daily_hi_per_day: dict[date, float] = {}
    daily_lo_per_day: dict[date, float] = {}

    for i, bar in enumerate(bars):
        d = _ny_date(bar.time)
        if cur_day is None or d != cur_day:
            # Close out previous day, roll state forward.
            if cur_day is not None:
                daily_hi_per_day[cur_day] = day_hi
                daily_lo_per_day[cur_day] = day_lo
                # Yesterday's high/low becomes today's reference.
                prior_day_hi = day_hi
                prior_day_lo = day_lo
            cur_day = d
            day_hi = bar.high
            day_lo = bar.low
            swept_hi = swept_lo = False
            max_body_pips = 0.0

        day_hi = max(day_hi, bar.high)
        day_lo = min(day_lo, bar.low)

        if prior_day_hi is not None and bar.high > prior_day_hi:
            swept_hi = True
        if prior_day_lo is not None and bar.low < prior_day_lo:
            swept_lo = True
        body_pips = bar.body / pip
        if body_pips > max_body_pips:
            max_body_pips = body_pips

        # update ATR
        atr_window.append(bar.range)
        if len(atr_window) > atr_period:
            atr_window.pop(0)
        if atr_window:
            last_atr = sum(atr_window) / len(atr_window)
        atr_pips = last_atr / pip

        sess = label_session(bar.time)
        any_sweep = swept_hi or swept_lo
        big_body = atr_pips > 0 and max_body_pips >= displacement_atr_mult * atr_pips

        if sess == "off":
            phase: Phase = "off"
        elif sess == "asia" and not any_sweep:
            phase = "accumulation"
        elif sess in ("london", "london_ny_overlap") and not big_body:
            phase = "manipulation"
        elif sess in ("ny", "london_ny_overlap") and any_sweep and big_body:
            phase = "distribution"
        elif any_sweep and not big_body:
            phase = "manipulation"
        elif any_sweep and big_body:
            phase = "distribution"
        else:
            phase = "accumulation"

        out.append(RangePhase(
            phase=phase,
            day_high_so_far=day_hi,
            day_low_so_far=day_lo,
            swept_high=swept_hi,
            swept_low=swept_lo,
            displacement_pips=max_body_pips,
        ))
    return out
