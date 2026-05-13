"""SDZoneRetest -- thin shim over the existing supply/demand zone detector.

A fresh, unmitigated zone in the trade direction whose range overlaps the
current bar. Mirrors how the rule engine consumes zones today.
"""
from __future__ import annotations

from agent.detectors.zones import fresh_zones
from agent.strategy.base import Strategy, build_basic_setup
from agent.types import Direction, Setup


class SDZoneRetest(Strategy):
    name = "SDZoneRetest"
    compatible_regimes = frozenset({"chop", "low_vol", "high_vol", "trending_up", "trending_down"})
    min_confluences = 1
    description = "Fresh demand/supply zone overlapping the current bar."

    def evaluate(self, ctx, at_index: int) -> Setup | None:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 0 or at_index >= len(bars):
            return None
        zones = getattr(ctx, "zones", None) or []
        if not zones:
            return None

        cur = bars[at_index]
        atr_pips_raw = (getattr(ctx, "atr_by_index", {}) or {}).get(at_index, 0.0)
        tol_pips = max(15.0, 0.2 * atr_pips_raw * 10000.0)
        tol = tol_pips * 0.0001

        for direction in (Direction.LONG, Direction.SHORT):
            same_dir = [z for z in zones if z.direction == direction
                        and z.created_bar_index <= at_index]
            if not same_dir:
                continue
            try:
                fresh = fresh_zones(same_dir, at_index)
            except TypeError:
                # Older tests may call with just zones; degrade gracefully.
                fresh = same_dir
            for z in fresh[-5:]:
                if (cur.low <= z.top + tol) and (cur.high >= z.bottom - tol):
                    return build_basic_setup(
                        bar=cur,
                        at_index=at_index,
                        direction=direction,
                        confluences=["zone"],
                        strategy_name=self.name,
                        atr_pips=atr_pips_raw * 10000.0 if atr_pips_raw > 0 else None,
                    )
        return None
