"""Fair Value Gap detection with quality grading.

Bullish FVG: a 3-bar pattern where bar[i-2].high < bar[i].low (gap between bars 1 and 3).
Bearish FVG: a 3-bar pattern where bar[i-2].low > bar[i].high.

The middle bar's range covers the gap. Price often returns to fill these gaps.

Quality grading assesses FVG tradability based on:
  - Size (institutional FVGs are larger)
  - Creation displacement/aggressiveness
  - Session context (kill-zone vs off-session)
  - Fill state (fresh > partially filled > mostly filled)
  - Revisit count (each visit drains resting orders)
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from agent.detectors.sessions import label_session
from agent.types import Bar, FVG, Direction
from agent.utils import to_pips

if TYPE_CHECKING:
    pass


def detect_fvgs(bars: list[Bar], min_size_pips: float = 5.0,
                up_to_index: int | None = None) -> list[FVG]:
    """Detect FVGs and compute quality scores.

    ``up_to_index`` bounds the forward fill-tracking scan so quality fields stay
    CAUSAL when called from a backtest harness. Without it the scan runs to the
    end of the series, leaking future fill state into the quality score applied
    at an earlier decision bar. The default of ``None`` preserves the old wide
    behaviour for clients that need it (e.g. visual sanity / dashboard).
    """
    fvgs: list[FVG] = []
    if len(bars) < 3:
        return fvgs

    for i in range(2, len(bars)):
        b0, b1, b2 = bars[i - 2], bars[i - 1], bars[i]

        if b0.high < b2.low:
            size = to_pips(b2.low - b0.high)
            if size >= min_size_pips:
                fvg = FVG(
                    direction=Direction.LONG,
                    top=b2.low,
                    bottom=b0.high,
                    created_at=b1.time,
                    created_bar_index=i - 1,
                    size_pips=size,
                )
                _enrich_quality(fvg, b1)
                fvgs.append(fvg)

        elif b0.low > b2.high:
            size = to_pips(b0.low - b2.high)
            if size >= min_size_pips:
                fvg = FVG(
                    direction=Direction.SHORT,
                    top=b0.low,
                    bottom=b2.high,
                    created_at=b1.time,
                    created_bar_index=i - 1,
                    size_pips=size,
                )
                _enrich_quality(fvg, b1)
                fvgs.append(fvg)

    _update_fill_tracking(fvgs, bars, up_to_index=up_to_index)
    return fvgs


def _enrich_quality(fvg: FVG, creation_bar: Bar) -> None:
    """Populate quality fields from the candle that created the FVG."""
    fvg.creation_displacement_pips = to_pips(creation_bar.body)
    bar_range = creation_bar.range
    fvg.creation_body_pct = (creation_bar.body / bar_range) if bar_range > 0 else 0.0

    session = _classify_formation_session(creation_bar.time)
    fvg.formation_session = session
    fvg.is_killzone = session in ("london_open", "ny_open")

    fvg.quality_score = compute_fvg_quality(fvg)


def _classify_formation_session(ts: datetime) -> str:
    """Map a bar timestamp to a formation session label for quality scoring.

    Returns one of: london_open, ny_open, london_body, ny_body, asia, off_session
    """
    raw = label_session(ts)
    if raw == "london":
        hour = _utc_hour(ts)
        if 7 <= hour < 10:
            return "london_open"
        return "london_body"
    elif raw == "london_ny_overlap":
        hour = _utc_hour(ts)
        if 13 <= hour < 16:
            return "ny_open"
        return "london_body"
    elif raw == "ny":
        hour = _utc_hour(ts)
        if 13 <= hour < 16:
            return "ny_open"
        return "ny_body"
    elif raw == "asia":
        return "asia"
    return "off_session"


def _utc_hour(ts: datetime) -> int:
    """Get hour in UTC."""
    if ts.tzinfo is not None:
        from datetime import timezone
        ts = ts.astimezone(timezone.utc)
    return ts.hour


def compute_fvg_quality(fvg: FVG) -> float:
    """Score an FVG from 0-100 based on institutional quality factors."""
    score = 0.0

    # Size: institutional FVGs are larger
    if fvg.size_pips >= 15:
        score += 25
    elif fvg.size_pips >= 10:
        score += 20
    elif fvg.size_pips >= 7:
        score += 15
    else:
        score += 5

    # Creation aggressiveness (displacement)
    if fvg.creation_body_pct >= 0.80:
        score += 25
    elif fvg.creation_body_pct >= 0.65:
        score += 18
    elif fvg.creation_body_pct >= 0.50:
        score += 10
    else:
        score += 3

    # Session context
    if fvg.is_killzone:
        score += 20
    elif fvg.formation_session in ("london_body", "ny_body"):
        score += 12
    else:
        score += 5

    # Fill freshness (unfilled > partially filled)
    if fvg.fill_pct == 0:
        score += 15
    elif fvg.fill_pct < 0.5:
        score += 10
    elif fvg.fill_pct < 0.8:
        score += 5
    else:
        score += 0

    # Revisit penalty (each visit drains remaining orders)
    score -= min(15, fvg.revisit_count * 5)

    return max(0.0, min(100.0, score))


def _update_fill_tracking(fvgs: list[FVG], bars: list[Bar],
                          up_to_index: int | None = None) -> None:
    """Track partial fill percentage and revisit count for each FVG.

    Also sets the legacy `filled`/`filled_at` fields for backward compatibility.

    ``up_to_index`` bounds the forward scan so fill state is computed CAUSALLY
    (only using bars at or before that index). Without it the scan runs to the
    end of the series, which leaks the future into a fill-state filter applied at
    an earlier decision bar — a look-ahead bug for backtesting (see docs/10 §10.5).
    """
    end = len(bars) if up_to_index is None else min(len(bars), up_to_index + 1)
    for fvg in fvgs:
        fvg_range = fvg.top - fvg.bottom
        if fvg_range <= 0:
            continue

        max_penetration = 0.0
        for j in range(fvg.created_bar_index + 1, end):
            b = bars[j]

            if fvg.direction == Direction.LONG:
                if b.low <= fvg.top:
                    penetration = fvg.top - max(b.low, fvg.bottom)
                    if penetration > 0:
                        if max_penetration == 0.0 or b.low < (fvg.top - max_penetration):
                            fvg.revisit_count += 1
                        max_penetration = max(max_penetration, penetration)

                    if b.low <= fvg.bottom:
                        fvg.filled = True
                        fvg.filled_at = b.time
                        fvg.is_fully_filled = True
                        fvg.fill_pct = 1.0
                        break

            elif fvg.direction == Direction.SHORT:
                if b.high >= fvg.bottom:
                    penetration = min(b.high, fvg.top) - fvg.bottom
                    if penetration > 0:
                        if max_penetration == 0.0 or b.high > (fvg.bottom + max_penetration):
                            fvg.revisit_count += 1
                        max_penetration = max(max_penetration, penetration)

                    if b.high >= fvg.top:
                        fvg.filled = True
                        fvg.filled_at = b.time
                        fvg.is_fully_filled = True
                        fvg.fill_pct = 1.0
                        break

        if not fvg.is_fully_filled and max_penetration > 0:
            fvg.fill_pct = min(1.0, max_penetration / fvg_range)

        # Recompute quality after fill tracking
        fvg.quality_score = compute_fvg_quality(fvg)


def unfilled_fvgs(fvgs: list[FVG], at_index: int) -> list[FVG]:
    """Return FVGs that are not fully filled and were created before at_index."""
    return [
        f for f in fvgs
        if f.created_bar_index < at_index and not f.is_fully_filled
    ]


def quality_fvgs(fvgs: list[FVG], at_index: int, min_quality: float = 40.0) -> list[FVG]:
    """Return unfilled FVGs that meet the quality threshold."""
    return [
        f for f in unfilled_fvgs(fvgs, at_index)
        if f.quality_score >= min_quality
    ]
