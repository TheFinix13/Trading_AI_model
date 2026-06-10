"""Quality-graded Fibonacci retracement detector.

Fibs are drawn only from *displacement* impulses — fast, aggressive moves with
large candle bodies that indicate institutional participation.  Each level is
weighted by its trading reliability (OTE zone > 50% > 38.2% >> 78.6%), and the
entire set is invalidated if price retraces past 78.6%.

The legacy ``auto_fib`` function is preserved for backward compatibility with the
rule engine and precompute pipeline — it now delegates to the upgraded internals.
"""
from __future__ import annotations


from agent.detectors.swings import detect_swings
from agent.types import Bar, Direction, FibLevel, FibZone, GradedFibLevel


# ---------------------------------------------------------------------------
# Impulse quality scoring
# ---------------------------------------------------------------------------

def compute_impulse_quality(
    bars: list[Bar],
    swing_start_idx: int,
    swing_end_idx: int,
) -> tuple[float, float, float, bool]:
    """Score the impulse move that fibs are drawn from.

    Returns (quality_score, displacement_pips, avg_body_pct, left_fvg).
    """
    score = 0.0

    n_bars = swing_end_idx - swing_start_idx
    move_pips = abs(bars[swing_end_idx].close - bars[swing_start_idx].close) / 0.0001

    if move_pips >= 50:
        score += 25
    elif move_pips >= 30:
        score += 20
    elif move_pips >= 20:
        score += 15
    else:
        score += 5

    pips_per_bar = move_pips / max(n_bars, 1)
    if pips_per_bar >= 10:
        score += 25
    elif pips_per_bar >= 5:
        score += 18
    elif pips_per_bar >= 2:
        score += 10
    else:
        score += 3

    body_pcts: list[float] = []
    for i in range(swing_start_idx, min(swing_end_idx + 1, len(bars))):
        r = bars[i].high - bars[i].low
        if r > 0:
            body_pcts.append(abs(bars[i].close - bars[i].open) / r)
    avg_body_pct = sum(body_pcts) / len(body_pcts) if body_pcts else 0.0

    if avg_body_pct >= 0.65:
        score += 20
    elif avg_body_pct >= 0.50:
        score += 14
    else:
        score += 5

    # Structure break bonus / penalty
    score += 15
    if move_pips < 20:
        score -= 10

    # FVG detection inside the impulse
    left_fvg = False
    for i in range(swing_start_idx + 2, min(swing_end_idx + 1, len(bars))):
        bullish_gap = bars[i].low - bars[i - 2].high
        bearish_gap = bars[i - 2].low - bars[i].high
        if bullish_gap > 0 or bearish_gap > 0:
            left_fvg = True
            score += 10
            break

    return (min(100.0, max(0.0, score)), move_pips, avg_body_pct, left_fvg)


# ---------------------------------------------------------------------------
# Level weighting
# ---------------------------------------------------------------------------

def compute_level_weight(level_pct: float, impulse_quality: float) -> float:
    """How much this fib level should boost a confluence score."""
    if 0.618 <= level_pct <= 0.710:
        base = 1.0
    elif 0.495 <= level_pct <= 0.505:
        base = 0.85
    elif 0.375 <= level_pct <= 0.390:
        base = 0.60
    elif level_pct >= 0.780:
        base = 0.15
    else:
        base = 0.50

    quality_mult = 0.3 + (impulse_quality / 100.0) * 0.7
    return base * quality_mult


# ---------------------------------------------------------------------------
# Fib invalidation
# ---------------------------------------------------------------------------

def invalidate_fibs(fib_levels: list[GradedFibLevel], bars: list[Bar], at_index: int) -> list[GradedFibLevel]:
    """Mark fibs as invalid if price has passed 78.6% retracement."""
    current = bars[at_index].close
    for fib in fib_levels:
        move = fib.swing_end - fib.swing_start
        invalidation_price = fib.swing_end - 0.786 * move
        if fib.direction == Direction.LONG and current < invalidation_price:
            fib.is_active = False
        elif fib.direction == Direction.SHORT and current > invalidation_price:
            fib.is_active = False
    return [f for f in fib_levels if f.is_active]


def invalidate_fib_level(fib: FibLevel, bars: list[Bar], at_index: int) -> FibLevel:
    """Check if the legacy FibLevel should be invalidated (price past 78.6%)."""
    current = bars[at_index].close
    move = fib.impulse_end - fib.impulse_start
    invalidation_price = fib.impulse_end - 0.786 * move
    if fib.direction == Direction.LONG and current < invalidation_price:
        fib.is_active = False
    elif fib.direction == Direction.SHORT and current > invalidation_price:
        fib.is_active = False
    return fib


# ---------------------------------------------------------------------------
# Confluence tag generation
# ---------------------------------------------------------------------------

def fib_confluence_tags(fib: FibLevel, bar: Bar, tol: float = 0.0015) -> list[str]:
    """Produce confluence tags for the optimizer/strategy based on which fib
    levels the current bar is touching."""
    tags: list[str] = []
    if not fib.is_active:
        return tags

    for lvl, price in fib.levels.items():
        if (bar.low - tol) <= price <= (bar.high + tol):
            if 0.618 <= lvl <= 0.710:
                tags.append("fib_ote")
            elif 0.495 <= lvl <= 0.505:
                tags.append("fib_50")
            elif 0.375 <= lvl <= 0.390:
                tags.append("fib_382")
            else:
                tags.append(f"fib_{int(lvl * 1000)}")

    if fib.impulse_quality >= 60:
        tags.append("fib_high_quality")
    elif fib.impulse_quality < 40:
        tags.append("fib_low_quality")

    return tags


# ---------------------------------------------------------------------------
# OTE zone builder
# ---------------------------------------------------------------------------

def build_fib_zone(fib: FibLevel) -> FibZone | None:
    """Extract the OTE zone from a legacy FibLevel if it contains the
    necessary retracement levels."""
    if not fib.is_active:
        return None
    ote_top = fib.levels.get(0.618)
    ote_bottom = fib.levels.get(0.705)
    fair_value = fib.levels.get(0.5) or fib.levels.get(0.500)

    if ote_top is None or ote_bottom is None:
        return None

    return FibZone(
        direction=fib.direction,
        ote_top=ote_top,
        ote_bottom=ote_bottom,
        fair_value=fair_value or (ote_top + ote_bottom) / 2,
        impulse_quality=fib.impulse_quality,
        bar_index=0,
        time=fib.created_at,
        is_active=True,
    )


# ---------------------------------------------------------------------------
# Core detector — graded fib levels from an impulse
# ---------------------------------------------------------------------------

def detect_graded_fibs(
    bars: list[Bar],
    swing_lookback: int = 5,
    active_levels: tuple[float, ...] = (0.382, 0.500, 0.618, 0.705),
    min_impulse_quality: float = 35.0,
    min_impulse_pips: float = 20.0,
) -> list[GradedFibLevel]:
    """Detect quality-graded fib levels from the last displacement impulse."""
    swings = detect_swings(bars, lookback=swing_lookback)
    if len(swings) < 2:
        return []

    last = swings[-1]
    prev_opposite = next(
        (s for s in reversed(swings[:-1]) if s.is_high != last.is_high),
        None,
    )
    if prev_opposite is None:
        return []

    swing_start_idx = prev_opposite.bar_index
    swing_end_idx = last.bar_index

    quality, displacement_pips, avg_body_pct, left_fvg = compute_impulse_quality(
        bars, swing_start_idx, swing_end_idx
    )

    if quality < min_impulse_quality or displacement_pips < min_impulse_pips:
        return []

    if last.is_high:
        start_price = prev_opposite.price
        end_price = last.price
        direction = Direction.LONG
    else:
        start_price = prev_opposite.price
        end_price = last.price
        direction = Direction.SHORT

    span = end_price - start_price
    broke_structure = displacement_pips >= 20

    graded: list[GradedFibLevel] = []
    for lvl in active_levels:
        price = end_price - lvl * span
        weight = compute_level_weight(lvl, quality)
        graded.append(GradedFibLevel(
            level_pct=lvl,
            price=price,
            direction=direction,
            swing_start=start_price,
            swing_end=end_price,
            bar_index=swing_end_idx,
            impulse_quality=quality,
            impulse_displacement_pips=displacement_pips,
            impulse_body_pct=avg_body_pct,
            impulse_left_fvg=left_fvg,
            impulse_broke_structure=broke_structure,
            is_in_ote=(0.618 <= lvl <= 0.710),
            confluence_weight=weight,
        ))

    return graded


# ---------------------------------------------------------------------------
# Legacy-compatible entry point
# ---------------------------------------------------------------------------

def auto_fib(
    bars: list[Bar],
    swing_lookback: int = 5,
    levels: tuple[float, ...] | list[float] = (0.382, 0.5, 0.618, 0.786),
    min_impulse_quality: float = 0.0,
    min_impulse_pips: float = 0.0,
) -> FibLevel | None:
    """Find the last impulse leg and draw fibs over it.

    Backward-compatible with the old signature (quality defaults to 0 so all
    impulses pass when called from legacy code).  When *min_impulse_quality* or
    *min_impulse_pips* are set, weak impulses are filtered out.
    """
    swings = detect_swings(bars, lookback=swing_lookback)
    if len(swings) < 2:
        return None

    last = swings[-1]
    prev_opposite = next(
        (s for s in reversed(swings[:-1]) if s.is_high != last.is_high),
        None,
    )
    if prev_opposite is None:
        return None

    swing_start_idx = prev_opposite.bar_index
    swing_end_idx = last.bar_index

    quality, displacement_pips, avg_body_pct, left_fvg = compute_impulse_quality(
        bars, swing_start_idx, swing_end_idx
    )

    if quality < min_impulse_quality or displacement_pips < min_impulse_pips:
        return None

    if last.is_high:
        start = prev_opposite.price
        end = last.price
        direction = Direction.LONG
    else:
        start = prev_opposite.price
        end = last.price
        direction = Direction.SHORT

    span = end - start
    level_prices = {lvl: end - lvl * span for lvl in levels}
    level_weights = {lvl: compute_level_weight(lvl, quality) for lvl in levels}

    return FibLevel(
        impulse_start=start,
        impulse_end=end,
        direction=direction,
        levels=level_prices,
        created_at=last.time,
        impulse_quality=quality,
        impulse_displacement_pips=displacement_pips,
        impulse_body_pct=avg_body_pct,
        impulse_left_fvg=left_fvg,
        impulse_broke_structure=(displacement_pips >= 20),
        level_weights=level_weights,
    )
