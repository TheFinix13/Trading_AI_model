"""Higher-timeframe bias filter (top-down analysis).

Concept: when trading on M15/H1, professional traders first look at D1 and H4 to
determine the direction of the prevailing trend and locate major demand/supply zones.
A setup taken WITH the higher-timeframe bias has a much better win rate than one
taken AGAINST it.

This module provides three pieces of bias information at any given time:

1. Trend direction (LONG / SHORT / NEUTRAL) derived from EMA20 slope on D1.
2. Whether the current price sits inside an active D1 demand or supply zone.
3. Whether the most recent break of structure on H4 agrees with the LTF setup direction.

The rule engine consumes this and either filters out setups that contradict the bias
(strict mode) or just appends an extra confluence tag for the ML model (advisory mode).

Designing it this way keeps the strategy conservative without losing signal entirely.
The bias is a *filter*, not a setup generator: it doesn't trigger trades on its own."""
from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass, field
from datetime import datetime

from agent.detectors.bos import detect_bos, latest_bos
from agent.detectors.fvg import detect_fvgs
from agent.detectors.zones import detect_zones, fresh_zones
from agent.types import Bar, Direction, FVG, Zone

log = logging.getLogger(__name__)


@dataclass
class HTFBias:
    """Snapshot of higher-timeframe context at a specific moment.

    All fields are optional; absent fields mean "no signal" rather than a falsey value.
    Direction is None when the trend isn't clear (consolidation)."""
    direction: Direction | None = None
    in_demand_zone: bool = False
    in_supply_zone: bool = False
    nearest_zone_distance_pips: float | None = None
    last_bos_direction: Direction | None = None
    source_tf: str = ""
    last_close: float = 0.0
    ema_slope_pips: float = 0.0  # 20-period slope: positive = up, negative = down

    # Actual HTF zone boundaries near current price for cross-TF overlap checks.
    # Each dict: {source_tf, direction ("long"/"short"), top, bottom, distance_pips}
    htf_zones_near_price: list[dict] = field(default_factory=list)

    # HTF FVGs near current price for cross-TF alignment.
    # Each dict: {source_tf, direction ("long"/"short"), top, bottom, distance_pips}
    htf_fvgs_near_price: list[dict] = field(default_factory=list)

    def agrees_with(self, direction: Direction) -> bool:
        """True if the HTF context supports a setup of the given direction.

        Permissive: if the HTF trend is neutral (None), we don't block the trade.
        Only blocks when there's an active opposing trend."""
        if self.direction is None:
            return True  # neutral → allow
        return self.direction == direction


def _ema_slope(bars: list[Bar], period: int = 20, lookback: int = 5) -> float:
    """Slope of EMA(period) over `lookback` bars, returned in pips per bar.
    Positive = uptrend; negative = downtrend; near-zero = consolidation."""
    if len(bars) < period + lookback:
        return 0.0
    closes = [b.close for b in bars]
    k = 2.0 / (period + 1)
    ema = closes[0]
    ema_series = []
    for c in closes:
        ema = c * k + ema * (1 - k)
        ema_series.append(ema)
    if len(ema_series) < lookback + 1:
        return 0.0
    delta = ema_series[-1] - ema_series[-1 - lookback]
    return delta / lookback * 10000.0  # → pips per bar


def _find_bar_at_or_before(bars: list[Bar], t: datetime) -> int:
    """Binary search the index of the last bar with time <= t. Returns -1 if none."""
    times = [b.time for b in bars]
    idx = bisect.bisect_right(times, t) - 1
    return idx


@dataclass
class HTFBiasComputer:
    """Pre-computes detector state on the HTF bars once, then answers `bias_at(t)`
    in O(log n) lookup. Use one of these per HTF feed (D1, H4, etc.)."""
    bars: list[Bar]
    zones: list[Zone]
    fvgs: list[FVG] = field(default_factory=list)
    min_trend_slope_pips: float = 0.5  # below this, we call the trend "neutral"
    zone_proximity_pips: float = 30.0  # how close price must be to report a zone

    def __post_init__(self):
        if not self.bars:
            return
        self.bos_list = detect_bos(self.bars, swing_lookback=10)

    @classmethod
    def build(cls, bars: list[Bar],
              zone_min_impulse_pips: float = 30.0,
              zone_max_age_bars: int = 200,
              min_trend_slope_pips: float = 0.5,
              fvg_min_size_pips: float = 5.0,
              zone_proximity_pips: float = 30.0) -> HTFBiasComputer:
        zones = detect_zones(bars,
                             min_impulse_pips=zone_min_impulse_pips,
                             max_age_bars=zone_max_age_bars)
        fvgs = detect_fvgs(bars, min_size_pips=fvg_min_size_pips)
        return cls(bars=bars, zones=zones, fvgs=fvgs,
                   min_trend_slope_pips=min_trend_slope_pips,
                   zone_proximity_pips=zone_proximity_pips)

    def bias_at(self, t: datetime, current_price: float | None = None) -> HTFBias:
        """Return the HTF bias as it would have been seen at decision time `t`.
        Critical: only uses HTF bars whose CLOSE timestamp is <= t to avoid lookahead."""
        if not self.bars:
            return HTFBias()
        idx = _find_bar_at_or_before(self.bars, t)
        if idx < 5:
            return HTFBias(source_tf=self.bars[0].timeframe.value)

        history = self.bars[: idx + 1]
        last_close = history[-1].close
        price = current_price if current_price is not None else last_close

        slope_pips = _ema_slope(history, period=20, lookback=5)
        if slope_pips > self.min_trend_slope_pips:
            direction: Direction | None = Direction.LONG
        elif slope_pips < -self.min_trend_slope_pips:
            direction = Direction.SHORT
        else:
            direction = None

        # Check active fresh zones at price
        active_long = fresh_zones([z for z in self.zones
                                   if z.direction == Direction.LONG
                                   and z.created_bar_index <= idx], idx)
        active_short = fresh_zones([z for z in self.zones
                                    if z.direction == Direction.SHORT
                                    and z.created_bar_index <= idx], idx)

        in_demand = any(z.bottom <= price <= z.top for z in active_long[-5:])
        in_supply = any(z.bottom <= price <= z.top for z in active_short[-5:])

        nearest = None
        for z in active_long[-5:] + active_short[-5:]:
            mid = (z.top + z.bottom) / 2.0
            d_pips = abs(price - mid) * 10000.0
            if nearest is None or d_pips < nearest:
                nearest = d_pips

        # Latest BOS direction
        last_bos = None
        if hasattr(self, "bos_list") and self.bos_list:
            recent = [b for b in self.bos_list if b.broken_bar_index <= idx]
            if recent:
                bos_obj = latest_bos(recent)
                if bos_obj is not None:
                    last_bos = bos_obj.direction

        # Collect HTF zones near price (within proximity tolerance).
        src_tf = self.bars[0].timeframe.value
        prox_tol = self.zone_proximity_pips * 0.0001
        zones_near: list[dict] = []
        for z in active_long[-5:] + active_short[-5:]:
            mid = (z.top + z.bottom) / 2.0
            d_abs = min(abs(price - z.top), abs(price - z.bottom), abs(price - mid))
            d_pips = d_abs * 10000.0
            if d_abs <= prox_tol or z.bottom <= price <= z.top:
                zones_near.append({
                    "source_tf": src_tf,
                    "direction": "long" if z.direction == Direction.LONG else "short",
                    "top": z.top,
                    "bottom": z.bottom,
                    "distance_pips": round(d_pips, 2),
                })

        # Collect HTF FVGs near price.
        fvgs_near: list[dict] = []
        active_fvgs = [
            f for f in self.fvgs
            if f.created_bar_index <= idx and not f.filled
        ]
        for f in active_fvgs[-10:]:
            mid = (f.top + f.bottom) / 2.0
            d_abs = min(abs(price - f.top), abs(price - f.bottom), abs(price - mid))
            d_pips = d_abs * 10000.0
            if d_abs <= prox_tol or f.bottom <= price <= f.top:
                fvgs_near.append({
                    "source_tf": src_tf,
                    "direction": "long" if f.direction == Direction.LONG else "short",
                    "top": f.top,
                    "bottom": f.bottom,
                    "distance_pips": round(d_pips, 2),
                })

        return HTFBias(
            direction=direction,
            in_demand_zone=in_demand,
            in_supply_zone=in_supply,
            nearest_zone_distance_pips=nearest,
            last_bos_direction=last_bos,
            source_tf=src_tf,
            last_close=last_close,
            ema_slope_pips=slope_pips,
            htf_zones_near_price=zones_near,
            htf_fvgs_near_price=fvgs_near,
        )
