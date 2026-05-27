"""Two-phase Liquidity Zone of Interest (LZI) detector.

Phase 1 — Zone Creation:
  A significant wick sweeps a tagged level (PDH/PDL/PWH/PWL/swing/equal) and
  the bar closes back inside.  The wick range is marked as an LZI — DO NOT TRADE.

Phase 2 — Retest Entry:
  Wait for price to return to the LZI.  Confirm *consumption* (2+ bars inside
  or touching the zone) then *displacement* (strong candle closing away from
  the zone in the expected direction).  Only then emit an entry signal.

Direction: sellside sweep → LONG entry on retest,  buyside sweep → SHORT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from agent.detectors.daily_levels import DailyLevels, compute_daily_levels
from agent.detectors.swings import detect_swings
from agent.types import Bar, Direction

PIP = 0.0001


@dataclass
class LiquidityZone:
    """A marked zone where liquidity was grabbed — waiting for retest."""
    side: Literal["buyside", "sellside"]
    trade_direction: Direction
    swept_label: str
    swept_price: float
    zone_top: float
    zone_bottom: float
    formation_bar_index: int
    formation_time: datetime
    wick_size_pips: float
    status: Literal["waiting", "retesting", "consumed", "triggered", "expired"] = "waiting"
    retest_bar_index: int | None = None
    consumption_bars: int = 0
    displacement_bar_index: int | None = None


@dataclass
class LiquidityEntry:
    """A confirmed entry signal from a completed LZI retest sequence."""
    zone: LiquidityZone
    direction: Direction
    entry_price: float
    entry_bar_index: int
    stop_price: float
    tp_price: float
    tp_label: str
    r_multiple: float
    confluences: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 1 helpers
# ---------------------------------------------------------------------------

def _equal_levels(swings, tol_pips: float = 5.0) -> list[tuple[str, float, int]]:
    """Detect equal-high / equal-low clusters (stop pools)."""
    out: list[tuple[str, float, int]] = []
    tol = tol_pips * PIP
    highs = [s for s in swings if s.is_high]
    lows = [s for s in swings if not s.is_high]
    for group, label in ((highs, "equal_highs"), (lows, "equal_lows")):
        if len(group) < 2:
            continue
        for i, s in enumerate(group):
            cluster = [s]
            for t in group[i + 1:]:
                if abs(t.price - s.price) <= tol:
                    cluster.append(t)
            if len(cluster) >= 2:
                avg = sum(c.price for c in cluster) / len(cluster)
                out.append((label, avg, max(c.bar_index for c in cluster)))
    return out


def _collect_levels(
    bar_index: int,
    bar: Bar,
    swings,
    daily_levels: DailyLevels | None,
    equal_clusters: list[tuple[str, float, int]],
    swing_lookback: int,
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Collect upper (buyside) and lower (sellside) target levels visible at bar_index."""
    upper: list[tuple[str, float]] = []
    lower: list[tuple[str, float]] = []

    if daily_levels is not None:
        ref_hi = max(bar.open, bar.close)
        ref_lo = min(bar.open, bar.close)
        for lbl, price in daily_levels.levels_dict().items():
            if lbl in ("PDM", "PWM"):
                continue
            if price >= ref_lo:
                upper.append((lbl, price))
            if price <= ref_hi:
                lower.append((lbl, price))

    for s in swings:
        if s.bar_index >= bar_index - swing_lookback:
            continue
        if s.is_high:
            upper.append(("swing_high", s.price))
        else:
            lower.append(("swing_low", s.price))

    for lbl, price, end_idx in equal_clusters:
        if end_idx >= bar_index:
            continue
        if lbl == "equal_highs":
            upper.append((lbl, price))
        else:
            lower.append((lbl, price))

    return upper, lower


# ---------------------------------------------------------------------------
# Phase 1: Detect LZI zones
# ---------------------------------------------------------------------------

def detect_liquidity_zones(
    bars: list[Bar],
    *,
    swing_lookback: int = 5,
    min_wick_size_pips: float = 10.0,
    pierce_buffer_pips: float = 1.0,
    use_daily_levels: bool = True,
) -> list[LiquidityZone]:
    """Phase 1: Walk bars and emit LZI zones wherever a sweep is confirmed.

    An LZI is created when:
      - A bar's wick pierces a tagged level by at least `pierce_buffer_pips`
      - The bar closes back inside the level (failed breakout)
      - The wick is at least `min_wick_size_pips` in size

    No entry is generated here — that's Phase 2 (`check_retest_entries`).
    """
    if len(bars) < swing_lookback * 2 + 2:
        return []

    swings = detect_swings(bars, lookback=swing_lookback)
    daily_levels_list = compute_daily_levels(bars) if use_daily_levels else [None] * len(bars)
    equal_clusters = _equal_levels(swings)

    buf = pierce_buffer_pips * PIP
    min_wick = min_wick_size_pips * PIP
    zones: list[LiquidityZone] = []

    for i in range(len(bars)):
        bar = bars[i]
        dl = daily_levels_list[i] if i < len(daily_levels_list) else None
        upper, lower = _collect_levels(i, bar, swings, dl, equal_clusters, swing_lookback)

        # --- Buyside sweep: wick above level, close back below → SHORT zone ---
        # Pick the closest upper target that was pierced and that the bar closed back below.
        pierced_up = [t for t in upper if bar.high > t[1] + buf and bar.close < t[1]]
        if pierced_up:
            target = min(pierced_up, key=lambda t: t[1])
            wick_top = bar.high
            body_top = max(bar.open, bar.close)
            wick_size = (wick_top - body_top)
            if wick_size >= min_wick:
                zones.append(LiquidityZone(
                    side="buyside",
                    trade_direction=Direction.SHORT,
                    swept_label=target[0],
                    swept_price=target[1],
                    zone_top=wick_top,
                    zone_bottom=body_top,
                    formation_bar_index=i,
                    formation_time=bar.time,
                    wick_size_pips=wick_size / PIP,
                ))

        # --- Sellside sweep: wick below level, close back above → LONG zone ---
        # Pick the closest lower target that was pierced and that the bar closed back above.
        pierced_dn = [t for t in lower if bar.low < t[1] - buf and bar.close > t[1]]
        if pierced_dn:
            target = max(pierced_dn, key=lambda t: t[1])
            wick_bottom = bar.low
            body_bottom = min(bar.open, bar.close)
            wick_size = (body_bottom - wick_bottom)
            if wick_size >= min_wick:
                zones.append(LiquidityZone(
                    side="sellside",
                    trade_direction=Direction.LONG,
                    swept_label=target[0],
                    swept_price=target[1],
                    zone_top=body_bottom,
                    zone_bottom=wick_bottom,
                    formation_bar_index=i,
                    formation_time=bar.time,
                    wick_size_pips=wick_size / PIP,
                ))

    return zones


# ---------------------------------------------------------------------------
# Phase 2: Check for retest → consumption → displacement entries
# ---------------------------------------------------------------------------

def check_retest_entries(
    bars: list[Bar],
    zones: list[LiquidityZone],
    at_index: int,
    *,
    opposite_liquidity_levels: list[tuple[str, float]] | None = None,
    retest_max_bars: int = 50,
    retest_proximity_pips: float = 5.0,
    consumption_min_bars: int = 2,
    displacement_min_body_pct: float = 0.60,
    displacement_min_pips: float = 8.0,
    zone_expiry_bars: int = 100,
    stop_buffer_pips: float = 3.0,
    fallback_rr: float = 2.0,
    use_pd_array_targeting: bool = True,
) -> list[LiquidityEntry]:
    """Phase 2: Check if any active LZI has completed the full retest sequence.

    For each zone:
      1. If expired (too many bars since formation), mark expired and skip.
      2. If "waiting", check if the current bar retests the zone.
      3. If "retesting", count consumption bars (inside/touching zone).
      4. If consumed enough, check for a displacement candle.
      5. On displacement, compute entry/stop/tp and emit a LiquidityEntry.
    """
    if at_index < 0 or at_index >= len(bars):
        return []

    cur = bars[at_index]
    prox = retest_proximity_pips * PIP
    disp_min = displacement_min_pips * PIP
    entries: list[LiquidityEntry] = []

    for zone in zones:
        if zone.status in ("triggered", "expired"):
            continue
        if zone.formation_bar_index >= at_index:
            continue

        age = at_index - zone.formation_bar_index
        if age > zone_expiry_bars:
            zone.status = "expired"
            continue

        # Must be within the retest window
        if zone.status == "waiting":
            if age > retest_max_bars:
                zone.status = "expired"
                continue

            touches_zone = (
                cur.low <= zone.zone_top + prox
                and cur.high >= zone.zone_bottom - prox
            )
            if touches_zone:
                zone.status = "retesting"
                zone.retest_bar_index = at_index
                zone.consumption_bars = 1
            continue

        if zone.status == "retesting":
            touches_zone = (
                cur.low <= zone.zone_top + prox
                and cur.high >= zone.zone_bottom - prox
            )
            if touches_zone:
                zone.consumption_bars += 1
            else:
                # Price left the zone before consuming enough — check if it
                # displaced or just drifted away.
                if zone.consumption_bars < consumption_min_bars:
                    # Not enough consumption yet. If price moved away in the
                    # WRONG direction, zone goes back to waiting (might retest again).
                    # If it moved away in the right direction without enough
                    # consumption, also go back to waiting.
                    zone.status = "waiting"
                    zone.consumption_bars = 0
                    zone.retest_bar_index = None
                    continue

            if zone.consumption_bars >= consumption_min_bars:
                zone.status = "consumed"
                # Fall through to check displacement on this same bar

        if zone.status == "consumed":
            # Check for displacement candle
            bar_range = cur.high - cur.low
            body = abs(cur.close - cur.open)

            if bar_range <= 0:
                continue

            body_pct = body / bar_range

            if body_pct < displacement_min_body_pct:
                # Check if zone expired while consumed (still inside)
                touches_zone = (
                    cur.low <= zone.zone_top + prox
                    and cur.high >= zone.zone_bottom - prox
                )
                if not touches_zone:
                    # Price left without displacement — back to waiting
                    zone.status = "waiting"
                    zone.consumption_bars = 0
                    zone.retest_bar_index = None
                continue

            if body < disp_min:
                continue

            # Check direction of displacement
            if zone.trade_direction == Direction.LONG:
                displaced_correct = cur.close > cur.open and cur.close > zone.zone_top
            else:
                displaced_correct = cur.close < cur.open and cur.close < zone.zone_bottom

            if not displaced_correct:
                continue

            # --- Displacement confirmed! Build entry ---
            zone.status = "triggered"
            zone.displacement_bar_index = at_index

            entry_price = cur.close
            buf = stop_buffer_pips * PIP

            if zone.trade_direction == Direction.LONG:
                stop_price = zone.zone_bottom - buf
            else:
                stop_price = zone.zone_top + buf

            stop_dist = abs(entry_price - stop_price)
            if stop_dist <= 0:
                continue

            # TP from opposite-side liquidity (PD Array targeting)
            tp_price = 0.0
            tp_label = "fallback_rr"
            if use_pd_array_targeting and opposite_liquidity_levels:
                if zone.trade_direction == Direction.LONG:
                    candidates = [
                        (lbl, p) for lbl, p in opposite_liquidity_levels
                        if p > entry_price + stop_dist
                    ]
                    if candidates:
                        best = min(candidates, key=lambda x: x[1])
                        tp_price = best[1]
                        tp_label = best[0]
                else:
                    candidates = [
                        (lbl, p) for lbl, p in opposite_liquidity_levels
                        if p < entry_price - stop_dist
                    ]
                    if candidates:
                        best = max(candidates, key=lambda x: x[1])
                        tp_price = best[1]
                        tp_label = best[0]

            if tp_price == 0.0:
                if zone.trade_direction == Direction.LONG:
                    tp_price = entry_price + fallback_rr * stop_dist
                else:
                    tp_price = entry_price - fallback_rr * stop_dist

            reward_dist = abs(tp_price - entry_price)
            r_multiple = reward_dist / stop_dist if stop_dist > 0 else 0.0

            confluences = [
                "lzi_retest",
                "lzi_consumed",
                "lzi_displacement",
                f"sweep_{zone.swept_label}",
            ]
            if tp_label != "fallback_rr":
                confluences.append(f"pd_target_{tp_label}")

            entries.append(LiquidityEntry(
                zone=zone,
                direction=zone.trade_direction,
                entry_price=entry_price,
                entry_bar_index=at_index,
                stop_price=stop_price,
                tp_price=tp_price,
                tp_label=tp_label,
                r_multiple=r_multiple,
                confluences=confluences,
            ))

    return entries
