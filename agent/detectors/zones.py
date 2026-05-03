"""Supply and demand zone detection.

A demand zone is a base of consolidation followed by a strong bullish impulse.
A supply zone is a base of consolidation followed by a strong bearish impulse.
We use the last consolidation candle (smallest body) before the impulse as the zone body."""
from __future__ import annotations

import statistics

from agent.types import Bar, Direction, Zone
from agent.utils import to_pips


def detect_zones(
    bars: list[Bar],
    min_impulse_pips: float = 30.0,
    base_lookback: int = 3,
    max_age_bars: int = 500,
    median_window: int = 200,
) -> list[Zone]:
    """Detect supply/demand zones using a base + impulse rule.

    For each bar, check if it represents a strong impulse (body >= min_impulse_pips).
    If yes, look back `base_lookback` bars for the smallest-body candle (the base/origin).
    The zone is the high-low range of that base candle.

    Bug-fix history (2026-05-03 evening):
      * The original implementation computed `median_body` from the LAST
        ``min(len(bars), 200)`` bars and used a single value for the entire
        series. In a multi-year backtest that meant every historical impulse
        was judged against recent volatility, suppressing zones detected in
        2023-2024 simply because 2026 was less volatile (or vice-versa). We
        now use a *rolling* median centred on each impulse bar.
      * The original implementation pruned zones with
        ``(len(bars) - 1 - z.created_bar_index) <= max_age_bars``, which
        discarded every zone created more than ``max_age_bars`` bars from
        the END of the input series. For a 75 000-bar M15 history that left
        only the last 500 bars (≈5 trading days) of zones — the rest of the
        series saw zero zones. Age filtering must happen *at use time*
        relative to the requested ``at_index``, not at detection time. The
        prune is therefore removed; callers apply it in
        ``fresh_zones(zones, at_index, max_age_bars=...)``.
    """
    zones: list[Zone] = []
    if len(bars) < base_lookback + 1:
        return zones

    # Pre-compute body-size series so we can take a rolling median per impulse
    # without allocating a fresh list inside the hot loop.
    body_series = [b.body for b in bars]
    half = median_window // 2

    for i in range(base_lookback, len(bars)):
        impulse = bars[i]
        impulse_body_pips = to_pips(impulse.body)
        if impulse_body_pips < min_impulse_pips:
            continue
        # Adaptive "strong impulse" gate: body must be >= 2x the local median.
        # Window is centred on `i` and clamped to the series boundaries so
        # the first/last bars use a half-window. This makes the detector
        # behave the same regardless of how much trailing history is supplied.
        lo = max(0, i - half)
        hi = min(len(body_series), i + half + 1)
        # Sorting is fine here — `median_window` is small (default 200) and
        # this branch only fires for bars that already passed the absolute
        # pip threshold, so it's cheap.
        local = body_series[lo:hi]
        median_body = statistics.median(local) if local else 0.0
        if impulse.body < 2 * median_body:
            continue

        base_window = bars[i - base_lookback : i]
        base = min(base_window, key=lambda b: b.body)

        if impulse.is_bullish:
            zone = Zone(
                direction=Direction.LONG,  # demand
                top=max(base.high, base.open, base.close),
                bottom=min(base.low, base.open, base.close),
                created_at=base.time,
                created_bar_index=i - base_lookback + base_window.index(base),
                impulse_pips=impulse_body_pips,
            )
        else:
            zone = Zone(
                direction=Direction.SHORT,  # supply
                top=max(base.high, base.open, base.close),
                bottom=min(base.low, base.open, base.close),
                created_at=base.time,
                created_bar_index=i - base_lookback + base_window.index(base),
                impulse_pips=impulse_body_pips,
            )
        zones.append(zone)

    _mark_mitigated(zones, bars)
    # Note: we deliberately do NOT prune by age here — see docstring. The
    # `max_age_bars` parameter is still accepted for backward compatibility
    # and is forwarded to `fresh_zones()` if callers wish.
    zones = _dedupe(zones)
    return zones


def _mark_mitigated(zones: list[Zone], bars: list[Bar]) -> None:
    """A zone is mitigated when price *closes through* it (not just touches it).

    Demand (LONG) zone: invalidated when a bar CLOSES below the zone bottom.
    Supply (SHORT) zone: invalidated when a bar CLOSES above the zone top.

    This matches how real supply/demand trading works: wicks into a zone are retests
    (potential entries), only a body close beyond the zone signals the level is broken.

    `mitigated_bar_index` is set to the bar where the close-through happened so
    `fresh_zones()` can be no-lookahead-safe."""
    for z in zones:
        for j in range(z.created_bar_index + 5, len(bars)):
            b = bars[j]
            if z.direction == Direction.LONG and b.close < z.bottom:
                z.mitigated = True
                z.mitigated_at = b.time
                z.mitigated_bar_index = j
                break
            if z.direction == Direction.SHORT and b.close > z.top:
                z.mitigated = True
                z.mitigated_at = b.time
                z.mitigated_bar_index = j
                break


def _dedupe(zones: list[Zone]) -> list[Zone]:
    """Drop zones that nearly overlap (within 5 pips on both edges)."""
    out: list[Zone] = []
    for z in zones:
        is_dup = False
        for o in out:
            if (
                z.direction == o.direction
                and abs(z.top - o.top) < 0.0005
                and abs(z.bottom - o.bottom) < 0.0005
            ):
                is_dup = True
                break
        if not is_dup:
            out.append(z)
    return out


def fresh_zones(
    zones: list[Zone],
    at_index: int,
    *,
    max_age_bars: int | None = None,
) -> list[Zone]:
    """Return zones that exist (created before `at_index`) AND have not been
    mitigated yet AS OF `at_index`. Critical for no-lookahead in backtests:
    a zone mitigated at bar 200 must still appear fresh when queried at bar 199.

    `max_age_bars` (optional): drop zones whose `created_bar_index` is more
    than that many bars in the past relative to `at_index`. This is the
    correct place for age filtering — see `detect_zones()` docstring for why
    age MUST be applied at use time, not at detection time."""
    out: list[Zone] = []
    for z in zones:
        if z.created_bar_index >= at_index:
            continue
        if z.mitigated and z.mitigated_bar_index is not None and z.mitigated_bar_index < at_index:
            continue
        if max_age_bars is not None and (at_index - z.created_bar_index) > max_age_bars:
            continue
        out.append(z)
    return out
