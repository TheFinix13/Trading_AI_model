"""LiquidityGrabReversal — two-phase LZI retest strategy.

Phase 1: Detect Liquidity Zones of Interest (LZIs) from sweep events.
Phase 2: Wait for price to retest → consume → displace from the zone.
Phase 3: Target opposite-side unswept liquidity (PD Array) for TP.

This replaces the old immediate-entry approach with the correct two-phase
retest logic taught by the discretionary trader.

Best regimes:
    * ``chop``     — sweeps are reversion plays in ranging markets
    * ``high_vol`` — volatility expansion at session opens presents as a sweep
"""
from __future__ import annotations

from agent.detectors.liquidity_zones import (
    LiquidityEntry,
    LiquidityZone,
    check_retest_entries,
)
from agent.detectors.pd_array import collect_opposite_liquidity_levels
from agent.strategy.base import Strategy
from agent.types import Direction, Setup


class LiquidityGrabReversal(Strategy):
    name = "LiquidityGrabReversal"
    compatible_regimes = frozenset({"chop", "high_vol", "trending_up", "trending_down"})
    min_confluences = 1
    description = "Two-phase LZI retest: sweep → zone → retest → consumption → displacement."

    def evaluate(self, ctx, at_index: int) -> Setup | None:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 0 or at_index >= len(bars):
            return None

        liq_zones: list[LiquidityZone] = getattr(ctx, "liquidity_zones", None) or []
        if not liq_zones:
            return None

        # Collect active (non-triggered, non-expired) zones
        active_zones = [
            z for z in liq_zones
            if z.status not in ("triggered", "expired")
            and z.formation_bar_index < at_index
        ]
        if not active_zones:
            return None

        # Get config from ctx if available
        liq_cfg = getattr(ctx, "liquidity_config", None)

        # Gather opposite liquidity levels for PD Array targeting
        daily_levels = None
        dl_list = getattr(ctx, "daily_levels", None)
        if dl_list and at_index < len(dl_list):
            daily_levels = dl_list[at_index]

        swings = getattr(ctx, "swings", None)

        # Check each active zone for completed retest sequence
        # We need to check for both LONG and SHORT since zones carry their direction
        for direction in (Direction.LONG, Direction.SHORT):
            dir_zones = [z for z in active_zones if z.trade_direction == direction]
            if not dir_zones:
                continue

            opp_levels = collect_opposite_liquidity_levels(
                bars, at_index, direction,
                daily_levels=daily_levels,
                swings=swings,
            )

            kwargs = {
                "opposite_liquidity_levels": opp_levels or None,
            }
            if liq_cfg is not None:
                kwargs.update({
                    "retest_max_bars": liq_cfg.retest_max_bars,
                    "retest_proximity_pips": liq_cfg.retest_proximity_pips,
                    "consumption_min_bars": liq_cfg.consumption_min_bars,
                    "displacement_min_body_pct": liq_cfg.displacement_min_body_pct,
                    "zone_expiry_bars": liq_cfg.zone_expiry_bars,
                    "stop_buffer_pips": liq_cfg.stop_buffer_pips,
                    "fallback_rr": liq_cfg.fallback_rr,
                    "use_pd_array_targeting": liq_cfg.use_pd_array_targeting,
                })
                # TF-aware displacement sizing
                tf_val = bars[0].timeframe.value if bars else "H1"
                if tf_val in ("H4", "D1"):
                    kwargs["displacement_min_pips"] = liq_cfg.displacement_min_pips_h4
                else:
                    kwargs["displacement_min_pips"] = liq_cfg.displacement_min_pips_h1

            entries = check_retest_entries(
                bars, dir_zones, at_index, **kwargs,
            )

            if entries:
                return self._entry_to_setup(entries[0], bars, at_index)

        return None

    def _entry_to_setup(self, entry: LiquidityEntry, bars, at_index: int) -> Setup:
        cur = bars[at_index]
        return Setup(
            direction=entry.direction,
            timeframe=cur.timeframe,
            detected_at=cur.time,
            detected_bar_index=at_index,
            entry=entry.entry_price,
            stop=entry.stop_price,
            take_profit=entry.tp_price,
            confluences=entry.confluences,
            confluence_tfs={c: cur.timeframe.value for c in entry.confluences},
            strategy_name=self.name,
        )
