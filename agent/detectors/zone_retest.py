"""Two-phase zone retest entry detection.

Phase 1: Price returns to a quality SD zone (score >= threshold, not depleted).
Phase 2: Reaction confirmed (rejection wick, engulfing, or displacement away from zone).

This replaces naive "price touches zone = entry" with institutional-grade logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent.detectors.zones import QualifiedZone, fresh_qualified_zones, update_zone_depletion
from agent.types import Bar, Direction
from agent.utils import to_pips


@dataclass
class ZoneEntry:
    """A confirmed zone retest entry signal."""

    zone: QualifiedZone
    direction: Direction
    entry_bar_index: int
    entry_price: float
    reaction_type: str  # "rejection_wick", "engulfing", "displacement"
    quality_score: float
    zone_level: float  # mid of the zone (for SL placement reference)
    confluences: list[str]


def check_zone_retest_entries(
    bars: list[Bar],
    zones: list[QualifiedZone],
    at_index: int,
    *,
    min_quality_score: float = 45.0,
    max_revisits: int = 2,
    max_fill_pct: float = 0.80,
    require_reaction: bool = True,
    max_age_bars: int = 500,
) -> list[ZoneEntry]:
    """Two-phase zone entry detection.

    1. Price returns to a quality zone (score >= min_quality_score, not depleted)
    2. Reaction confirmed (rejection wick, engulfing, or displacement)

    Returns all valid entries at `at_index` (typically 0-2).
    """
    if at_index < 1 or at_index >= len(bars):
        return []

    # Update depletion state
    update_zone_depletion(zones, bars, at_index)

    # Get fresh, quality zones
    active = fresh_qualified_zones(
        zones, at_index,
        max_age_bars=max_age_bars,
        min_quality_score=min_quality_score,
    )

    # Filter by depletion limits
    candidates = [
        qz for qz in active
        if qz.quality.revisit_count <= max_revisits
        and qz.quality.fill_pct <= max_fill_pct
    ]

    cur = bars[at_index]
    prev = bars[at_index - 1] if at_index > 0 else None
    entries: list[ZoneEntry] = []

    for qz in candidates:
        # Phase 1: Is price at the zone?
        if not _price_at_zone(cur, qz):
            continue

        # Phase 2: Reaction confirmation
        if require_reaction:
            reaction = _detect_reaction(bars, at_index, qz)
            if reaction is None:
                continue
        else:
            reaction = "touch"

        confluences = _build_confluences(qz, reaction)

        entry = ZoneEntry(
            zone=qz,
            direction=qz.direction,
            entry_bar_index=at_index,
            entry_price=cur.close,
            reaction_type=reaction,
            quality_score=qz.quality.quality_score,
            zone_level=qz.mid,
            confluences=confluences,
        )
        entries.append(entry)

    return entries


def _price_at_zone(bar: Bar, qz: QualifiedZone) -> bool:
    """Check if the current bar touches or penetrates the zone."""
    return bar.low <= qz.top and bar.high >= qz.bottom


def _detect_reaction(bars: list[Bar], at_index: int, qz: QualifiedZone) -> str | None:
    """Detect a reaction at the zone confirming institutional interest.

    Returns reaction type or None if no confirmation.
    """
    cur = bars[at_index]
    prev = bars[at_index - 1] if at_index > 0 else None

    if qz.direction == Direction.LONG:
        # Demand zone: looking for bullish reaction
        reaction = _bullish_reaction(cur, prev, qz)
    else:
        # Supply zone: looking for bearish reaction
        reaction = _bearish_reaction(cur, prev, qz)

    return reaction


def _bullish_reaction(cur: Bar, prev: Bar | None, qz: QualifiedZone) -> str | None:
    """Detect bullish reaction at a demand zone."""
    zone_height = qz.top - qz.bottom
    if zone_height <= 0:
        return None

    # 1. Rejection wick: long lower wick that pierced into zone but closed above
    # Requires minimum wick size of 5 pips to avoid noise
    if cur.lower_wick > 0 and cur.range > 0:
        wick_ratio = cur.lower_wick / cur.range
        wick_pips = to_pips(cur.lower_wick)
        if wick_ratio > 0.5 and wick_pips >= 5.0 and cur.close > qz.bottom:
            if cur.low <= qz.top:
                return "rejection_wick"

    # 2. Bullish engulfing: current bar's body engulfs previous bar's body
    if prev is not None and not prev.is_bullish and cur.is_bullish:
        if cur.body > prev.body * 1.0 and cur.close > prev.open:
            if prev.low <= qz.top:  # Previous bar was in/near zone
                return "engulfing"

    # 3. Displacement: strong bullish bar leaving the zone (body > 60% of range)
    if cur.is_bullish and cur.range > 0:
        body_pct = cur.body / cur.range
        if body_pct >= 0.60 and cur.close > qz.top:
            return "displacement"

    return None


def _bearish_reaction(cur: Bar, prev: Bar | None, qz: QualifiedZone) -> str | None:
    """Detect bearish reaction at a supply zone."""
    zone_height = qz.top - qz.bottom
    if zone_height <= 0:
        return None

    # 1. Rejection wick: long upper wick that pierced into zone but closed below
    if cur.upper_wick > 0 and cur.range > 0:
        wick_ratio = cur.upper_wick / cur.range
        wick_pips = to_pips(cur.upper_wick)
        if wick_ratio > 0.5 and wick_pips >= 5.0 and cur.close < qz.top:
            if cur.high >= qz.bottom:
                return "rejection_wick"

    # 2. Bearish engulfing
    if prev is not None and prev.is_bullish and not cur.is_bullish:
        if cur.body > prev.body * 1.0 and cur.close < prev.open:
            if prev.high >= qz.bottom:
                return "engulfing"

    # 3. Displacement: strong bearish bar leaving the zone
    if not cur.is_bullish and cur.range > 0:
        body_pct = cur.body / cur.range
        if body_pct >= 0.60 and cur.close < qz.bottom:
            return "displacement"

    return None


def _build_confluences(qz: QualifiedZone, reaction: str) -> list[str]:
    """Build confluence list from zone quality attributes."""
    confs = ["zone", f"zone_reaction_{reaction}"]

    if qz.quality.is_killzone:
        confs.append("zone_killzone")
    if qz.quality.left_fvg:
        confs.append("zone_fvg_behind")
    if qz.quality.origin_type in ("rally_base_drop", "drop_base_rally"):
        confs.append("zone_proper_formation")
    if qz.quality.quality_score >= 70:
        confs.append("zone_high_quality")

    return confs
