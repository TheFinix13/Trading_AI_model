"""Outcome labeler. For each candidate setup, walk the price forward and record:

  - hit_tp:   1 if take-profit hit before stop, else 0
  - hit_sl:   1 if stop-loss hit, else 0
  - rr_realized: actual R-multiple achieved (negative if SL, positive if TP, partial if force-closed)
  - bars_to_resolve: how many bars until SL or TP hit (or capped at horizon)
  - max_favorable_pips / max_adverse_pips: peak excursions

These labels are what XGBoost trains against. Strict no-lookahead: labeling uses bars
AFTER the candidate's detected_bar_index only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from agent.types import Bar, Direction, Setup
from agent.utils import to_pips

log = logging.getLogger(__name__)


@dataclass
class Outcome:
    candidate: Setup
    hit_tp: int            # 0 or 1
    hit_sl: int            # 0 or 1
    rr_realized: float     # actual R-multiple (-1 if SL, +rr_min if TP, partial otherwise)
    bars_to_resolve: int
    max_favorable_pips: float
    max_adverse_pips: float
    resolved: bool         # False if force-closed at horizon

    @property
    def label(self) -> int:
        """Binary win/loss label for classifier training."""
        return self.hit_tp


def label_candidate(candidate: Setup, bars: list[Bar], horizon_bars: int = 200) -> Outcome:
    """Simulate the candidate forward up to `horizon_bars` bars. Detect SL/TP first-touch
    using bar high/low. If a bar's range straddles both SL and TP, assume SL hit (worst-case)."""
    start_idx = candidate.detected_bar_index + 1  # entry on next bar
    if start_idx >= len(bars):
        return Outcome(candidate, 0, 0, 0.0, 0, 0.0, 0.0, resolved=False)

    entry = bars[start_idx].open
    stop = candidate.stop
    tp = candidate.take_profit
    direction = candidate.direction

    risk = abs(entry - stop)
    if risk <= 0:
        return Outcome(candidate, 0, 0, 0.0, 0, 0.0, 0.0, resolved=False)

    max_fav = 0.0
    max_adv = 0.0
    end_idx = min(start_idx + horizon_bars, len(bars) - 1)

    for i in range(start_idx, end_idx + 1):
        b = bars[i]
        if direction == Direction.LONG:
            fav = b.high - entry
            adv = entry - b.low
        else:
            fav = entry - b.low
            adv = b.high - entry
        max_fav = max(max_fav, fav)
        max_adv = max(max_adv, adv)

        if direction == Direction.LONG:
            hit_sl = b.low <= stop
            hit_tp = b.high >= tp
        else:
            hit_sl = b.high >= stop
            hit_tp = b.low <= tp

        if hit_sl and hit_tp:
            return Outcome(
                candidate, hit_tp=0, hit_sl=1, rr_realized=-1.0,
                bars_to_resolve=i - start_idx,
                max_favorable_pips=to_pips(max_fav),
                max_adverse_pips=to_pips(max_adv),
                resolved=True,
            )
        if hit_sl:
            return Outcome(
                candidate, hit_tp=0, hit_sl=1, rr_realized=-1.0,
                bars_to_resolve=i - start_idx,
                max_favorable_pips=to_pips(max_fav),
                max_adverse_pips=to_pips(max_adv),
                resolved=True,
            )
        if hit_tp:
            rr = abs(tp - entry) / risk
            return Outcome(
                candidate, hit_tp=1, hit_sl=0, rr_realized=rr,
                bars_to_resolve=i - start_idx,
                max_favorable_pips=to_pips(max_fav),
                max_adverse_pips=to_pips(max_adv),
                resolved=True,
            )

    # Force-close at horizon: compute partial RR from last bar's close
    last = bars[end_idx]
    if direction == Direction.LONG:
        partial = (last.close - entry) / risk
    else:
        partial = (entry - last.close) / risk
    return Outcome(
        candidate, hit_tp=0, hit_sl=0, rr_realized=float(partial),
        bars_to_resolve=end_idx - start_idx,
        max_favorable_pips=to_pips(max_fav),
        max_adverse_pips=to_pips(max_adv),
        resolved=False,
    )


def label_all(candidates: list[Setup], bars: list[Bar], horizon_bars: int = 200) -> list[Outcome]:
    """Label every candidate. Skips candidates whose horizon would extend beyond available data."""
    out: list[Outcome] = []
    for c in candidates:
        if c.detected_bar_index + 1 >= len(bars):
            continue
        out.append(label_candidate(c, bars, horizon_bars=horizon_bars))
    return out
