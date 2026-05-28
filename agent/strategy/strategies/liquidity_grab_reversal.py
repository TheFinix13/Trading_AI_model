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
from agent.strategy.base import Strategy, StrategyResult
from agent.types import Direction, Setup


class LiquidityGrabReversal(Strategy):
    name = "LiquidityGrabReversal"
    compatible_regimes = frozenset({"chop", "high_vol", "trending_up", "trending_down"})
    min_confluences = 1
    description = "Two-phase LZI retest: sweep → zone → retest → consumption → displacement."

    def _gather_context(self, ctx, at_index: int):
        """Shared context gathering for both evaluate and evaluate_explained."""
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 0 or at_index >= len(bars):
            return None, None, None, None, None

        liq_zones: list[LiquidityZone] = getattr(ctx, "liquidity_zones", None) or []
        active_zones = [
            z for z in liq_zones
            if z.status not in ("triggered", "expired")
            and z.formation_bar_index < at_index
        ] if liq_zones else []

        liq_cfg = getattr(ctx, "liquidity_config", None)
        daily_levels = None
        dl_list = getattr(ctx, "daily_levels", None)
        if dl_list and at_index < len(dl_list):
            daily_levels = dl_list[at_index]
        swings = getattr(ctx, "swings", None)

        return bars, liq_zones, active_zones, liq_cfg, (daily_levels, swings)

    def _build_retest_kwargs(self, bars, liq_cfg, direction, at_index, daily_levels, swings):
        opp_levels = collect_opposite_liquidity_levels(
            bars, at_index, direction,
            daily_levels=daily_levels,
            swings=swings,
        )
        kwargs = {"opposite_liquidity_levels": opp_levels or None}
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
            tf_val = bars[0].timeframe.value if bars else "H1"
            if tf_val in ("H4", "D1"):
                kwargs["displacement_min_pips"] = liq_cfg.displacement_min_pips_h4
            else:
                kwargs["displacement_min_pips"] = liq_cfg.displacement_min_pips_h1
        return kwargs

    def evaluate(self, ctx, at_index: int) -> Setup | None:
        result = self._gather_context(ctx, at_index)
        bars, liq_zones, active_zones, liq_cfg, (daily_levels, swings) = result
        if bars is None or not active_zones:
            return None

        for direction in (Direction.LONG, Direction.SHORT):
            dir_zones = [z for z in active_zones if z.trade_direction == direction]
            if not dir_zones:
                continue

            kwargs = self._build_retest_kwargs(bars, liq_cfg, direction, at_index, daily_levels, swings)
            entries = check_retest_entries(bars, dir_zones, at_index, **kwargs)
            if entries:
                return self._entry_to_setup(entries[0], bars, at_index)

        return None

    def evaluate_explained(self, ctx, at_index: int) -> StrategyResult:
        result = self._gather_context(ctx, at_index)
        bars, liq_zones, active_zones, liq_cfg, extras = result
        if bars is None:
            return StrategyResult(strategy_name=self.name, status="NOT_ACTIVE")

        daily_levels, swings = extras
        all_zones = liq_zones or []
        zones_details: list[str] = []
        checks_passed: list[str] = []
        checks_failed: list[str] = []
        best_status = "NOT_ACTIVE"
        next_trigger = ""

        # Describe all known zones (active + depleted)
        for z in all_zones:
            if z.formation_bar_index >= at_index:
                continue
            age = at_index - z.formation_bar_index
            quality = "A" if z.wick_size_pips >= 10 else "B"
            status_label = z.status.upper()
            zones_details.append(
                f"{z.zone_bottom:.4f}-{z.zone_top:.4f} "
                f"({z.swept_label} sweep, quality {quality}, {status_label}, "
                f"age {age} bars)"
            )

        if not active_zones:
            if all_zones:
                checks_failed.append("All zones triggered or expired")
                next_trigger = "New liquidity sweep to create fresh zone"
            else:
                checks_failed.append("No liquidity zones detected")
                next_trigger = "Need sweep of PDH/PDL/swing level"
            return StrategyResult(
                strategy_name=self.name,
                zones_found=len(all_zones),
                zones_details=zones_details,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
                status="NOT_ACTIVE",
                next_trigger=next_trigger,
            )

        # Check each direction for zone readiness
        for direction in (Direction.LONG, Direction.SHORT):
            dir_zones = [z for z in active_zones if z.trade_direction == direction]
            if not dir_zones:
                continue

            kwargs = self._build_retest_kwargs(bars, liq_cfg, direction, at_index, daily_levels, swings)
            entries = check_retest_entries(bars, dir_zones, at_index, **kwargs)

            for z in dir_zones:
                dir_label = "BUY" if direction == Direction.LONG else "SELL"
                cur = bars[at_index]

                price_in_zone = z.zone_bottom <= cur.close <= z.zone_top
                price_near = abs(cur.close - (z.zone_top + z.zone_bottom) / 2) * 10000 < 30

                if z.status == "waiting":
                    checks_passed.append(f"Zone {z.zone_bottom:.4f}-{z.zone_top:.4f}: sweep confirmed ({z.swept_label})")
                    if price_near or price_in_zone:
                        checks_failed.append(f"Zone {z.swept_label}: no retest yet (price approaching)")
                        best_status = "WATCHING"
                        next_trigger = f"Price must enter zone {z.zone_bottom:.4f}-{z.zone_top:.4f}"
                    else:
                        checks_failed.append(f"Zone {z.swept_label}: price not near zone (current {cur.close:.5f})")
                        if best_status != "WATCHING":
                            best_status = "NOT_ACTIVE"
                        next_trigger = f"Price must approach zone {z.zone_bottom:.4f}-{z.zone_top:.4f}"

                elif z.status == "retesting":
                    checks_passed.append(f"Zone {z.swept_label}: sweep confirmed")
                    checks_passed.append(f"Zone {z.swept_label}: retest in progress")
                    checks_failed.append(f"Zone {z.swept_label}: no consumption candle yet (need {liq_cfg.consumption_min_bars if liq_cfg else 2}+ bars in zone)")
                    best_status = "WATCHING"
                    next_trigger = f"Need consumption bars inside zone, then displacement candle for {dir_label}"

                elif z.status == "consumed":
                    checks_passed.append(f"Zone {z.swept_label}: sweep confirmed")
                    checks_passed.append(f"Zone {z.swept_label}: retest confirmed")
                    checks_passed.append(f"Zone {z.swept_label}: consumption confirmed ({z.consumption_bars} bars)")
                    checks_failed.append(f"Zone {z.swept_label}: waiting for displacement candle")
                    best_status = "WATCHING"
                    next_trigger = f"Need strong {dir_label.lower()} displacement candle closing away from zone"

            if entries:
                entry = entries[0]
                setup = self._entry_to_setup(entry, bars, at_index)
                z = entry.zone
                checks_passed.append(f"Zone {z.swept_label}: displacement confirmed")
                return StrategyResult(
                    strategy_name=self.name,
                    signal=setup,
                    zones_found=len(active_zones),
                    zones_details=zones_details,
                    checks_passed=checks_passed,
                    checks_failed=[],
                    status="SIGNAL_GENERATED",
                    next_trigger="",
                )

        return StrategyResult(
            strategy_name=self.name,
            zones_found=len(active_zones),
            zones_details=zones_details,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            status=best_status,
            next_trigger=next_trigger,
        )

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
