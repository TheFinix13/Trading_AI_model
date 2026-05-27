"""Two-phase FVG retest detection.

Phase 1: Price returns to a quality-graded FVG zone.
Phase 2: Price shows a REACTION (not just a touch) confirming institutional interest.

Reaction types:
  1. Rejection wick — bar enters FVG, wick shows strong rejection (>50% of range on correct side)
  2. Engulfing — bar enters FVG, next bar engulfs in trade direction
  3. Displacement — bar enters FVG, next bar displaces strongly away (body > 60%, > 6 pips)

Only after confirmed reaction is an entry emitted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from agent.detectors.fvg import quality_fvgs, unfilled_fvgs
from agent.types import Bar, Direction, FVG, Swing
from agent.utils import to_pips


@dataclass
class FVGEntry:
    """Confirmed FVG retest entry — price returned to FVG AND reacted."""
    fvg: FVG
    direction: Direction
    entry_price: float
    entry_bar_index: int
    stop_price: float
    tp_price: float
    reaction_type: str  # "rejection_wick", "engulfing", "displacement"
    quality_score: float
    confluences: list[str] = field(default_factory=list)


def check_fvg_retest_entries(
    bars: list[Bar],
    fvgs: list[FVG],
    at_index: int,
    *,
    min_quality_score: float = 40.0,
    require_reaction: bool = True,
    max_fill_pct: float = 0.80,
    max_revisits: int = 2,
    stop_buffer_pips: float = 3.0,
    structural_targets: list[float] | None = None,
    fallback_rr: float = 2.0,
) -> list[FVGEntry]:
    """Check if price has returned to a quality FVG AND shown a reaction.

    Args:
        bars: Price bars
        fvgs: All detected FVGs (quality-graded)
        at_index: Current bar index to evaluate
        min_quality_score: Minimum FVG quality to consider
        require_reaction: If True, must see reaction candle (not just touch)
        max_fill_pct: Don't trade FVGs that are mostly filled
        max_revisits: Don't trade FVGs visited this many times or more
        stop_buffer_pips: Extra pips beyond FVG boundary for stop
        structural_targets: Precomputed target prices (swing highs/lows, daily levels)
        fallback_rr: R:R used when no structural target available

    Returns:
        List of confirmed FVG entries (usually 0 or 1).
    """
    if at_index < 2 or at_index >= len(bars):
        return []

    # Filter to quality FVGs that haven't been overused
    candidates = [
        f for f in fvgs
        if f.created_bar_index < at_index
        and not f.is_fully_filled
        and f.quality_score >= min_quality_score
        and f.fill_pct < max_fill_pct
        and f.revisit_count <= max_revisits
    ]

    if not candidates:
        return []

    entries: list[FVGEntry] = []
    cur = bars[at_index]
    prev = bars[at_index - 1] if at_index >= 1 else None

    for fvg in reversed(candidates[-25:]):
        # Phase 1: Is price currently touching/inside this FVG?
        if not _bar_touches_fvg(cur, fvg):
            continue

        # Phase 2: Check for reaction
        reaction = _detect_reaction(bars, at_index, fvg)
        if require_reaction and reaction is None:
            continue

        reaction_type = reaction if reaction else "touch_only"

        # Compute entry, stop, and TP
        entry_price = cur.close
        stop_price = _compute_stop(fvg, stop_buffer_pips)
        tp_price = _compute_tp(
            fvg, entry_price, stop_price, structural_targets, fallback_rr
        )

        # Build confluences
        confluences = _build_confluences(fvg, reaction_type)

        entries.append(FVGEntry(
            fvg=fvg,
            direction=fvg.direction,
            entry_price=entry_price,
            entry_bar_index=at_index,
            stop_price=stop_price,
            tp_price=tp_price,
            reaction_type=reaction_type,
            quality_score=fvg.quality_score,
            confluences=confluences,
        ))

        # Only emit one entry per bar (best FVG first since we iterate reversed)
        break

    return entries


def _bar_touches_fvg(bar: Bar, fvg: FVG) -> bool:
    """Check if bar's range overlaps the FVG zone."""
    return bar.low <= fvg.top and bar.high >= fvg.bottom


def _detect_reaction(bars: list[Bar], at_index: int, fvg: FVG) -> str | None:
    """Detect if a reaction pattern has formed at the FVG.

    Looks at the current bar and optionally the previous bar for multi-bar
    patterns (engulfing). Returns the reaction type or None.
    """
    cur = bars[at_index]
    prev = bars[at_index - 1] if at_index >= 1 else None

    # Type 1: Rejection wick on current bar
    wick_reaction = _check_rejection_wick(cur, fvg)
    if wick_reaction:
        return "rejection_wick"

    # Type 2: Engulfing — previous bar entered FVG, current bar engulfs in direction
    if prev and _bar_touches_fvg(prev, fvg):
        if _check_engulfing(prev, cur, fvg.direction):
            return "engulfing"

    # Type 3: Displacement — previous bar entered FVG, current bar displaces away
    if prev and _bar_touches_fvg(prev, fvg):
        if _check_displacement(cur, fvg.direction):
            return "displacement"

    return None


def _check_rejection_wick(bar: Bar, fvg: FVG) -> bool:
    """Bar enters FVG but shows strong rejection wick on the correct side.

    For bullish FVG: wick below (lower_wick) > 50% of bar range
    For bearish FVG: wick above (upper_wick) > 50% of bar range
    """
    if bar.range == 0:
        return False

    if fvg.direction == Direction.LONG:
        # Bullish FVG: price dips into gap then rejects up (lower wick prominent)
        if bar.lower_wick / bar.range >= 0.50 and bar.close > fvg.bottom:
            return True
    else:
        # Bearish FVG: price rises into gap then rejects down (upper wick prominent)
        if bar.upper_wick / bar.range >= 0.50 and bar.close < fvg.top:
            return True

    return False


def _check_engulfing(prev: Bar, cur: Bar, direction: Direction) -> bool:
    """Current bar engulfs previous bar in the trade direction."""
    if direction == Direction.LONG:
        return (
            cur.is_bullish
            and cur.close > prev.high
            and cur.open <= prev.close
        )
    else:
        return (
            not cur.is_bullish
            and cur.close < prev.low
            and cur.open >= prev.close
        )


def _check_displacement(bar: Bar, direction: Direction) -> bool:
    """Bar shows strong displacement away from FVG (body > 60%, > 6 pips)."""
    if bar.range == 0:
        return False

    body_pct = bar.body / bar.range
    body_pips = to_pips(bar.body)

    if body_pct < 0.60 or body_pips < 6.0:
        return False

    if direction == Direction.LONG:
        return bar.is_bullish
    else:
        return not bar.is_bullish


def _compute_stop(fvg: FVG, buffer_pips: float) -> float:
    """Stop placed beyond the FVG boundary with buffer."""
    buffer = buffer_pips * 0.0001
    if fvg.direction == Direction.LONG:
        return fvg.bottom - buffer
    else:
        return fvg.top + buffer


def _compute_tp(
    fvg: FVG,
    entry_price: float,
    stop_price: float,
    structural_targets: list[float] | None,
    fallback_rr: float,
) -> float:
    """Compute take-profit from structural targets or fallback R:R."""
    stop_distance = abs(entry_price - stop_price)

    if structural_targets:
        # Find the nearest structural target that gives at least 1.5R
        min_tp_distance = stop_distance * 1.5
        best_target = None

        for target in structural_targets:
            if fvg.direction == Direction.LONG:
                if target > entry_price + min_tp_distance:
                    if best_target is None or target < best_target:
                        best_target = target
            else:
                if target < entry_price - min_tp_distance:
                    if best_target is None or target > best_target:
                        best_target = target

        if best_target is not None:
            return best_target

    # Fallback: use R:R multiplier
    if fvg.direction == Direction.LONG:
        return entry_price + fallback_rr * stop_distance
    else:
        return entry_price - fallback_rr * stop_distance


def _build_confluences(fvg: FVG, reaction_type: str) -> list[str]:
    """Construct the confluence list for this entry."""
    confs = ["fvg_retest"]

    if fvg.is_killzone:
        confs.append("fvg_killzone")
    if fvg.quality_score >= 70:
        confs.append("fvg_high_quality")
    if fvg.has_sweep_before:
        confs.append("fvg_post_sweep")
    if fvg.aligns_with_htf_trend:
        confs.append("fvg_htf_aligned")

    if reaction_type == "rejection_wick":
        confs.append("reaction_wick")
    elif reaction_type == "engulfing":
        confs.append("reaction_engulfing")
    elif reaction_type == "displacement":
        confs.append("reaction_displacement")

    return confs


def collect_structural_targets(
    bars: list[Bar],
    at_index: int,
    direction: Direction,
    swings: list[Swing] | None = None,
    daily_levels: dict | None = None,
) -> list[float]:
    """Gather potential TP targets from swing structure and daily levels.

    For LONG: collect swing highs and resistance levels above current price.
    For SHORT: collect swing lows and support levels below current price.
    """
    if at_index >= len(bars):
        return []

    cur_price = bars[at_index].close
    targets: list[float] = []

    if swings:
        for s in swings:
            if s.bar_index >= at_index:
                continue
            if direction == Direction.LONG and s.is_high and s.price > cur_price:
                targets.append(s.price)
            elif direction == Direction.SHORT and not s.is_high and s.price < cur_price:
                targets.append(s.price)

    if daily_levels:
        for key in ("pdh", "pdl", "pwh", "pwl", "pdm"):
            level = (daily_levels.get(key) if isinstance(daily_levels, dict)
                     else getattr(daily_levels, key, None))
            if level is None:
                continue
            if direction == Direction.LONG and level > cur_price:
                targets.append(level)
            elif direction == Direction.SHORT and level < cur_price:
                targets.append(level)

    # Sort by proximity
    if direction == Direction.LONG:
        targets.sort()
    else:
        targets.sort(reverse=True)

    return targets
