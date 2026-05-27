"""Supply and demand zone detection with quality grading.

A demand zone is the last bearish candle(s) before a bullish displacement (order block).
A supply zone is the last bullish candle(s) before a bearish displacement.
Zone boundaries are the high/low of that order block, NOT the entire impulse.

Quality grading assesses zone tradability based on:
  - Origin pattern (rally-base-drop, drop-base-rally, impulse-only)
  - Base tightness (1-3 candles ideal)
  - Departure aggressiveness (body/range of displacement candle)
  - Session context (killzone vs off-session)
  - FVG left behind (extra institutional confirmation)
  - Width vs ATR (proportional zones are better)
  - Depletion tracking (revisits drain remaining orders)
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime

from agent.detectors.sessions import label_session
from agent.types import Bar, Direction, Zone
from agent.utils import to_pips


@dataclass
class ZoneQuality:
    """Quality assessment for a supply/demand zone."""

    # Origin pattern
    origin_type: str = "impulse_only"  # "rally_base_drop", "drop_base_rally", "impulse_only"
    base_candle_count: int = 1
    departure_pips: float = 0.0
    departure_body_pct: float = 0.0
    left_fvg: bool = False

    # Session context
    formation_session: str = "off_session"
    is_killzone: bool = False

    # Precision
    zone_width_pips: float = 0.0
    width_vs_atr: float = 0.0

    # Depletion tracking
    revisit_count: int = 0
    fill_pct: float = 0.0
    is_depleted: bool = False
    age_bars: int = 0

    # Quality score (0-100)
    quality_score: float = 0.0


@dataclass
class QualifiedZone:
    """A Zone with full quality metadata."""

    zone: Zone
    quality: ZoneQuality

    @property
    def direction(self) -> Direction:
        return self.zone.direction

    @property
    def top(self) -> float:
        return self.zone.top

    @property
    def bottom(self) -> float:
        return self.zone.bottom

    @property
    def mid(self) -> float:
        return self.zone.mid

    @property
    def created_bar_index(self) -> int:
        return self.zone.created_bar_index

    @property
    def created_at(self) -> datetime:
        return self.zone.created_at

    @property
    def mitigated(self) -> bool:
        return self.zone.mitigated

    @property
    def mitigated_bar_index(self) -> int | None:
        return self.zone.mitigated_bar_index

    def contains(self, price: float) -> bool:
        return self.zone.contains(price)


def compute_zone_quality(quality: ZoneQuality) -> float:
    """Compute quality score (0-100) for a zone based on its attributes."""
    score = 0.0

    # Origin type (rally-base-drop/drop-base-rally = proper formation)
    if quality.origin_type in ("rally_base_drop", "drop_base_rally"):
        score += 15
    elif quality.origin_type == "impulse_only":
        score += 8

    # Base tightness (1-3 candles ideal)
    if quality.base_candle_count <= 2:
        score += 15
    elif quality.base_candle_count <= 3:
        score += 12
    elif quality.base_candle_count <= 5:
        score += 6
    else:
        score += 2

    # Departure aggressiveness
    if quality.departure_body_pct >= 0.75:
        score += 20
    elif quality.departure_body_pct >= 0.60:
        score += 14
    elif quality.departure_body_pct >= 0.45:
        score += 8
    else:
        score += 3

    # FVG left behind (extra confirmation of institutional interest)
    if quality.left_fvg:
        score += 10

    # Session
    if quality.is_killzone:
        score += 15
    elif quality.formation_session in ("london_body", "ny_body"):
        score += 10
    else:
        score += 3

    # Width vs ATR (proportional zones are better)
    if quality.width_vs_atr <= 1.0:
        score += 10
    elif quality.width_vs_atr <= 1.5:
        score += 7
    elif quality.width_vs_atr <= 2.5:
        score += 4
    else:
        score += 0

    # Depletion penalty
    score -= min(15, quality.revisit_count * 5)
    if quality.fill_pct > 0.5:
        score -= 10

    # Age penalty (very old zones are stale)
    if quality.age_bars > 300:
        score -= 5
    if quality.age_bars > 500:
        score -= 10

    return max(0.0, min(100.0, score))


def _classify_formation_session(ts: datetime) -> str:
    """Map bar timestamp to formation session label."""
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
        return "ny_body"
    elif raw == "ny":
        return "ny_body"
    elif raw == "asia":
        return "asia"
    return "off_session"


def _utc_hour(ts: datetime) -> int:
    """Extract UTC hour from a possibly-naive timestamp."""
    if ts.tzinfo is not None:
        from datetime import timezone
        return ts.astimezone(timezone.utc).hour
    return ts.hour


def _is_killzone(session: str) -> bool:
    """Killzones: London 07-10 UTC or NY 13-16 UTC."""
    return session in ("london_open", "ny_open")


def _classify_origin(bars: list[Bar], base_start: int, base_end: int, impulse_idx: int) -> str:
    """Determine origin pattern: rally-base-drop, drop-base-rally, or impulse-only.

    For demand zones (bullish impulse):
      - drop-base-rally: price was falling, consolidated, then surged up
    For supply zones (bearish impulse):
      - rally-base-drop: price was rising, consolidated, then dropped
    """
    if base_start < 2:
        return "impulse_only"

    impulse = bars[impulse_idx]
    pre_base_start = max(0, base_start - 3)
    pre_base_bars = bars[pre_base_start:base_start]

    if not pre_base_bars:
        return "impulse_only"

    pre_move = pre_base_bars[-1].close - pre_base_bars[0].open

    if impulse.is_bullish:
        if pre_move < -0.0002:
            return "drop_base_rally"
    else:
        if pre_move > 0.0002:
            return "rally_base_drop"

    return "impulse_only"


def _check_fvg_left(bars: list[Bar], impulse_idx: int) -> bool:
    """Check if the departure candle left an FVG behind."""
    if impulse_idx < 2 or impulse_idx >= len(bars) - 1:
        return False

    b0 = bars[impulse_idx - 2]
    b2 = bars[impulse_idx]

    # Bullish FVG: gap between bar[i-2].high and bar[i].low
    if b2.is_bullish and b0.high < b2.low:
        return True
    # Bearish FVG: gap between bar[i-2].low and bar[i].high
    if not b2.is_bullish and b0.low > b2.high:
        return True

    return False


def _compute_local_atr(bars: list[Bar], idx: int, period: int = 14) -> float:
    """Compute ATR around a given index."""
    start = max(0, idx - period)
    window = bars[start:idx + 1]
    if len(window) < 2:
        return 0.0001
    ranges = [b.range for b in window]
    return sum(ranges) / len(ranges) if ranges else 0.0001


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

    body_series = [b.body for b in bars]
    half = median_window // 2

    for i in range(base_lookback, len(bars)):
        impulse = bars[i]
        impulse_body_pips = to_pips(impulse.body)
        if impulse_body_pips < min_impulse_pips:
            continue
        lo = max(0, i - half)
        hi = min(len(body_series), i + half + 1)
        local = body_series[lo:hi]
        median_body = statistics.median(local) if local else 0.0
        if impulse.body < 2 * median_body:
            continue

        base_window = bars[i - base_lookback : i]
        base = min(base_window, key=lambda b: b.body)

        if impulse.is_bullish:
            zone = Zone(
                direction=Direction.LONG,
                top=max(base.high, base.open, base.close),
                bottom=min(base.low, base.open, base.close),
                created_at=base.time,
                created_bar_index=i - base_lookback + base_window.index(base),
                impulse_pips=impulse_body_pips,
            )
        else:
            zone = Zone(
                direction=Direction.SHORT,
                top=max(base.high, base.open, base.close),
                bottom=min(base.low, base.open, base.close),
                created_at=base.time,
                created_bar_index=i - base_lookback + base_window.index(base),
                impulse_pips=impulse_body_pips,
            )
        zones.append(zone)

    _mark_mitigated(zones, bars)
    zones = _dedupe(zones)
    return zones


def detect_qualified_zones(
    bars: list[Bar],
    min_impulse_pips: float = 30.0,
    base_lookback: int = 5,
    max_base_candles: int = 5,
    median_window: int = 200,
) -> list[QualifiedZone]:
    """Detect supply/demand zones with full quality grading.

    Uses order-block logic for precise zone boundaries:
      - DEMAND: zone = last bearish candle(s) before bullish displacement
      - SUPPLY: zone = last bullish candle(s) before bearish displacement

    Returns QualifiedZone objects with quality scores.
    """
    qualified: list[QualifiedZone] = []
    if len(bars) < base_lookback + 1:
        return qualified

    body_series = [b.body for b in bars]
    half = median_window // 2

    for i in range(base_lookback, len(bars)):
        impulse = bars[i]
        impulse_body_pips = to_pips(impulse.body)
        if impulse_body_pips < min_impulse_pips:
            continue

        lo_w = max(0, i - half)
        hi_w = min(len(body_series), i + half + 1)
        local = body_series[lo_w:hi_w]
        median_body = statistics.median(local) if local else 0.0
        if impulse.body < 2 * median_body:
            continue

        # Order block identification:
        # For DEMAND (bullish impulse): find last bearish candle(s) before impulse
        # For SUPPLY (bearish impulse): find last bullish candle(s) before impulse
        ob_candles = _find_order_block(bars, i, base_lookback, max_base_candles)
        if not ob_candles:
            continue

        ob_start_idx = i - base_lookback + ob_candles[0]
        ob_bars = [bars[i - base_lookback + c] for c in ob_candles]

        zone_top = max(b.high for b in ob_bars)
        zone_bottom = min(b.low for b in ob_bars)

        direction = Direction.LONG if impulse.is_bullish else Direction.SHORT

        zone = Zone(
            direction=direction,
            top=zone_top,
            bottom=zone_bottom,
            created_at=ob_bars[0].time,
            created_bar_index=ob_start_idx,
            impulse_pips=impulse_body_pips,
        )

        # Build quality assessment
        local_atr = _compute_local_atr(bars, i)
        zone_width = zone_top - zone_bottom
        zone_width_pips = to_pips(zone_width)

        session = _classify_formation_session(impulse.time)
        origin = _classify_origin(bars, i - base_lookback, i - 1, i)
        has_fvg = _check_fvg_left(bars, i)

        departure_body_pct = (impulse.body / impulse.range) if impulse.range > 0 else 0.0

        quality = ZoneQuality(
            origin_type=origin,
            base_candle_count=len(ob_candles),
            departure_pips=impulse_body_pips,
            departure_body_pct=departure_body_pct,
            left_fvg=has_fvg,
            formation_session=session,
            is_killzone=_is_killzone(session),
            zone_width_pips=zone_width_pips,
            width_vs_atr=zone_width / local_atr if local_atr > 0 else 5.0,
        )
        quality.quality_score = compute_zone_quality(quality)

        qualified.append(QualifiedZone(zone=zone, quality=quality))

    # Mark mitigated zones
    raw_zones = [qz.zone for qz in qualified]
    _mark_mitigated(raw_zones, bars)

    # Dedupe
    qualified = _dedupe_qualified(qualified)
    return qualified


def _find_order_block(
    bars: list[Bar], impulse_idx: int, lookback: int, max_candles: int
) -> list[int]:
    """Find order block candles before the impulse.

    For bullish impulse: last bearish candle(s) in the lookback window.
    For bearish impulse: last bullish candle(s) in the lookback window.

    Returns indices relative to the lookback window start.
    """
    impulse = bars[impulse_idx]
    window_start = impulse_idx - lookback
    window = bars[window_start:impulse_idx]

    if impulse.is_bullish:
        # Demand: find last bearish candles (order block = selling before the buy surge)
        target_bullish = False
    else:
        # Supply: find last bullish candles (order block = buying before the sell surge)
        target_bullish = True

    # Scan backwards from the impulse to find the opposing candle(s)
    ob_indices: list[int] = []
    for j in range(len(window) - 1, -1, -1):
        if window[j].is_bullish == target_bullish:
            ob_indices.insert(0, j)
            if len(ob_indices) >= max_candles:
                break
        elif ob_indices:
            break  # Hit a non-matching candle after finding some OB candles

    if not ob_indices:
        # Fallback: use the smallest-body candle (legacy behavior)
        base = min(range(len(window)), key=lambda k: window[k].body)
        return [base]

    return ob_indices


def update_zone_depletion(
    qualified_zones: list[QualifiedZone],
    bars: list[Bar],
    at_index: int,
) -> None:
    """Update depletion tracking for zones relative to the current bar index.

    Each time price revisits a zone, its order-flow is partially consumed.
    Skips the initial departure bars (first 5 after creation) and the current bar.
    """
    for qz in qualified_zones:
        if qz.zone.mitigated:
            continue
        if qz.zone.created_bar_index >= at_index:
            continue

        qz.quality.age_bars = at_index - qz.zone.created_bar_index

        revisits = 0
        max_penetration = 0.0
        zone_height = qz.top - qz.bottom
        if zone_height <= 0:
            continue

        # Skip first 5 bars after creation (departure/impulse bars)
        # and stop BEFORE at_index (don't count current bar as revisit)
        scan_start = qz.zone.created_bar_index + 5
        scan_end = at_index  # exclusive

        for j in range(scan_start, min(scan_end, len(bars))):
            b = bars[j]
            if b.low <= qz.top and b.high >= qz.bottom:
                revisits += 1
                if qz.direction == Direction.LONG:
                    penetration = (qz.top - b.low) / zone_height
                else:
                    penetration = (b.high - qz.bottom) / zone_height
                max_penetration = max(max_penetration, penetration)

        qz.quality.revisit_count = max(qz.quality.revisit_count, revisits)
        qz.quality.fill_pct = max(qz.quality.fill_pct, min(1.0, max_penetration))
        qz.quality.is_depleted = (
            qz.quality.is_depleted
            or qz.quality.revisit_count >= 3
            or qz.quality.fill_pct >= 0.8
        )
        qz.quality.quality_score = compute_zone_quality(qz.quality)


def fresh_qualified_zones(
    zones: list[QualifiedZone],
    at_index: int,
    *,
    max_age_bars: int | None = None,
    min_quality_score: float = 0.0,
) -> list[QualifiedZone]:
    """Return qualified zones that are fresh (not mitigated, not too old) at `at_index`."""
    out: list[QualifiedZone] = []
    for qz in zones:
        if qz.zone.created_bar_index >= at_index:
            continue
        if qz.zone.mitigated and qz.zone.mitigated_bar_index is not None and qz.zone.mitigated_bar_index < at_index:
            continue
        if max_age_bars is not None and (at_index - qz.zone.created_bar_index) > max_age_bars:
            continue
        if qz.quality.quality_score < min_quality_score:
            continue
        if qz.quality.is_depleted:
            continue
        out.append(qz)
    return out


# ---------------------------------------------------------------------------
# Legacy API (preserved for backward compatibility)
# ---------------------------------------------------------------------------


def _mark_mitigated(zones: list[Zone], bars: list[Bar]) -> None:
    """A zone is mitigated when price *closes through* it (not just touches it).

    Demand (LONG) zone: invalidated when a bar CLOSES below the zone bottom.
    Supply (SHORT) zone: invalidated when a bar CLOSES above the zone top.

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


def _dedupe_qualified(zones: list[QualifiedZone]) -> list[QualifiedZone]:
    """Drop qualified zones that nearly overlap."""
    out: list[QualifiedZone] = []
    for qz in zones:
        is_dup = False
        for o in out:
            if (
                qz.direction == o.direction
                and abs(qz.top - o.top) < 0.0005
                and abs(qz.bottom - o.bottom) < 0.0005
            ):
                is_dup = True
                break
        if not is_dup:
            out.append(qz)
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
