"""Break of Structure detection with quality grading.

A bullish BOS: price closes above the most recent confirmed swing high.
A bearish BOS: price closes below the most recent confirmed swing low.
We only register a NEW BOS when it represents a fresh structural break.

Quality grading assesses BOS significance based on:
  - Break type (body close beyond level >> wick-only pierce)
  - Displacement magnitude (how far past the level)
  - Session context (London/NY open breaks are most significant)
  - Recency of the broken swing (recent structure > ancient)
  - Evidence left behind (FVG or order block created by the break)

Key design principle: BOS is NOT an entry trigger — it's a CONTEXT signal.
It confirms trend direction and enhances FVG/LZI entries that form after it.
"""
from __future__ import annotations

from agent.detectors.sessions import label_session
from agent.detectors.swings import detect_swings
from agent.types import Bar, BreakOfStructure, Direction
from agent.utils import to_pips


def detect_bos(bars: list[Bar], swing_lookback: int = 5) -> list[BreakOfStructure]:
    """Detect breaks of structure with quality scoring.

    Backward-compatible: returns list[BreakOfStructure] with all legacy fields,
    plus new quality fields populated on each BOS event.

    Performance: the v2 version rebuilt ``prior_highs = [s for s in swings if
    ... < i - lookback]`` for every bar (O(N × S) ≈ 136M ops on H1 → ~30s).
    Only ``prior_highs[-1]`` was ever used, so we instead maintain two
    monotonic cursors over the chronological swing lists. Equivalence to the
    v2 output is locked in by ``tests/test_bos_speedup.py``.
    """
    swings = detect_swings(bars, lookback=swing_lookback)
    if not swings:
        return []

    # Chronological swing arrays (detect_swings already returns ascending by
    # bar_index, but sort defensively so a future change doesn't break us).
    high_swings = sorted([s for s in swings if s.is_high], key=lambda s: s.bar_index)
    low_swings = sorted([s for s in swings if not s.is_high], key=lambda s: s.bar_index)

    breaks: list[BreakOfStructure] = []
    last_broken_high: float | None = None
    last_broken_low: float | None = None

    high_cursor = 0  # number of high_swings that are visible at bar i
    low_cursor = 0

    for i, bar in enumerate(bars):
        # Advance the cursors to include every swing whose bar_index <
        # i - swing_lookback (matches the v2 strict-less-than visibility).
        threshold = i - swing_lookback
        while high_cursor < len(high_swings) and high_swings[high_cursor].bar_index < threshold:
            high_cursor += 1
        while low_cursor < len(low_swings) and low_swings[low_cursor].bar_index < threshold:
            low_cursor += 1

        if high_cursor > 0:
            ref = high_swings[high_cursor - 1]
            if bar.close > ref.price and (last_broken_high is None or ref.price > last_broken_high):
                bos = BreakOfStructure(
                    direction=Direction.LONG,
                    broken_swing_price=ref.price,
                    broken_at=bar.time,
                    broken_bar_index=i,
                )
                _enrich_bos_quality(bos, bar, ref.price, ref.bar_index, i, bars)
                breaks.append(bos)
                last_broken_high = ref.price

        if low_cursor > 0:
            ref = low_swings[low_cursor - 1]
            if bar.close < ref.price and (last_broken_low is None or ref.price < last_broken_low):
                bos = BreakOfStructure(
                    direction=Direction.SHORT,
                    broken_swing_price=ref.price,
                    broken_at=bar.time,
                    broken_bar_index=i,
                )
                _enrich_bos_quality(bos, bar, ref.price, ref.bar_index, i, bars)
                breaks.append(bos)
                last_broken_low = ref.price

    return breaks


def _enrich_bos_quality(
    bos: BreakOfStructure,
    break_bar: Bar,
    swing_price: float,
    swing_bar_index: int,
    break_bar_index: int,
    bars: list[Bar],
) -> None:
    """Populate quality fields on a BOS event."""
    # Break displacement
    if bos.direction == Direction.LONG:
        displacement = break_bar.close - swing_price
    else:
        displacement = swing_price - break_bar.close
    bos.break_displacement_pips = to_pips(max(0.0, displacement))

    # Body percentage of break candle
    bar_range = break_bar.range
    bos.break_body_pct = (break_bar.body / bar_range) if bar_range > 0 else 0.0

    # Is it a body break? (close beyond level, not just wick)
    bos.is_body_break = True  # We already check bar.close > ref.price in detection

    # Check if it was ALSO a wick-only scenario (body didn't actually clear)
    if bos.direction == Direction.LONG:
        body_top = max(break_bar.open, break_bar.close)
        if body_top <= swing_price:
            bos.is_body_break = False
    else:
        body_bottom = min(break_bar.open, break_bar.close)
        if body_bottom >= swing_price:
            bos.is_body_break = False

    # Session
    bos.break_session = _classify_break_session(break_bar.time)

    # Recency
    bos.bars_since_swing = break_bar_index - swing_bar_index

    # Evidence: did the break leave an FVG behind?
    bos.left_fvg_behind = _check_fvg_left_behind(bars, break_bar_index)

    # Evidence: is there an order block (last opposite candle before break)?
    bos.left_orderblock = _check_orderblock(bars, break_bar_index, bos.direction)

    # Compute quality score
    bos.quality_score = compute_bos_quality(bos)


def _classify_break_session(ts) -> str:
    """Map timestamp to session label for BOS quality."""
    raw = label_session(ts)
    if raw == "london":
        return "london_open"
    elif raw == "london_ny_overlap":
        return "ny_open"
    elif raw == "ny":
        return "ny_body"
    elif raw == "asia":
        return "asia"
    return "off_session"


def _check_fvg_left_behind(bars: list[Bar], break_index: int) -> bool:
    """Check if a 3-bar FVG pattern formed around the break candle."""
    if break_index < 2 or break_index >= len(bars):
        return False

    b0 = bars[break_index - 2]
    b2 = bars[break_index]

    # Bullish FVG: bar[-2].high < bar[0].low
    if b0.high < b2.low:
        gap_pips = to_pips(b2.low - b0.high)
        if gap_pips >= 3.0:
            return True

    # Bearish FVG: bar[-2].low > bar[0].high
    if b0.low > b2.high:
        gap_pips = to_pips(b0.low - b2.high)
        if gap_pips >= 3.0:
            return True

    return False


def _check_orderblock(bars: list[Bar], break_index: int, direction: Direction) -> bool:
    """Check for an order block (last opposite-direction candle before the break).

    An order block is the final candle that traded against the eventual break direction,
    immediately before the impulsive move. Look back 1-3 bars.
    """
    lookback = min(3, break_index)
    for offset in range(1, lookback + 1):
        idx = break_index - offset
        if idx < 0:
            break
        bar = bars[idx]
        if direction == Direction.LONG and not bar.is_bullish:
            return True
        elif direction == Direction.SHORT and bar.is_bullish:
            return True
    return False


def compute_bos_quality(bos: BreakOfStructure) -> float:
    """Score a BOS event from 0-100 based on institutional significance."""
    score = 0.0

    # Break type (body break >> wick break)
    if bos.is_body_break and bos.break_body_pct >= 0.70:
        score += 30
    elif bos.is_body_break:
        score += 20
    else:
        score += 5  # Wick-only break = very weak

    # Displacement on break
    if bos.break_displacement_pips >= 10:
        score += 20
    elif bos.break_displacement_pips >= 5:
        score += 12
    else:
        score += 5

    # Session
    if bos.break_session in ("london_open", "ny_open"):
        score += 20
    elif bos.break_session in ("london_body", "ny_body"):
        score += 12
    else:
        score += 5

    # Recency of broken swing
    if bos.bars_since_swing <= 20:
        score += 15
    elif bos.bars_since_swing <= 50:
        score += 10
    else:
        score += 3  # Ancient swing = meaningless break

    # Left evidence behind
    if bos.left_fvg_behind:
        score += 10
    if bos.left_orderblock:
        score += 5

    return min(100.0, score)


def latest_bos(bos_list: list[BreakOfStructure], before_index: int | None = None) -> BreakOfStructure | None:
    """Get the most recent BOS event, optionally before a given index."""
    if not bos_list:
        return None
    if before_index is None:
        return bos_list[-1]
    candidates = [b for b in bos_list if b.broken_bar_index <= before_index]
    return candidates[-1] if candidates else None


def quality_bos(
    bos_list: list[BreakOfStructure],
    at_index: int,
    min_quality: float = 50.0,
    max_lookback_bars: int = 50,
) -> list[BreakOfStructure]:
    """Return recent quality BOS events that meet the threshold."""
    return [
        b for b in bos_list
        if b.broken_bar_index <= at_index
        and (at_index - b.broken_bar_index) <= max_lookback_bars
        and b.quality_score >= min_quality
    ]
