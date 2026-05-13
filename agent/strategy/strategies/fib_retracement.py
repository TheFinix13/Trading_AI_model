"""FibRetracement -- thin shim over the existing fib detector.

The bar's range tags one of the configured fib levels (382 / 500 / 618 / 786)
on the latest impulse. Phase-1 just emits a candidate; phase 3+ will combine
this with FVG / sweep before promoting to a live entry.
"""
from __future__ import annotations

from agent.strategy.base import Strategy, build_basic_setup
from agent.types import Direction, Setup


class FibRetracement(Strategy):
    name = "FibRetracement"
    compatible_regimes = frozenset({"trending_up", "trending_down", "chop"})
    min_confluences = 1
    description = "Bar range tags a fib level on the latest impulse."

    def evaluate(self, ctx, at_index: int) -> Setup | None:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 0 or at_index >= len(bars):
            return None
        fib_by_index = getattr(ctx, "fib_by_index", None) or {}
        keys = [k for k in fib_by_index.keys() if k <= at_index]
        if not keys:
            return None
        fib = fib_by_index[max(keys)]
        if fib is None:
            return None
        cur = bars[at_index]
        atr_pips_raw = (getattr(ctx, "atr_by_index", {}) or {}).get(at_index, 0.0)
        tol_pips = max(15.0, 0.2 * atr_pips_raw * 10000.0)
        tol = tol_pips * 0.0001

        tagged = None
        for lvl, price in fib.levels.items():
            if (cur.low - tol) <= price <= (cur.high + tol):
                tagged = lvl
                break
        if tagged is None:
            return None

        direction = fib.direction if isinstance(fib.direction, Direction) else Direction(fib.direction)
        confluences = [f"fib_{int(tagged * 1000)}"]
        return build_basic_setup(
            bar=cur,
            at_index=at_index,
            direction=direction,
            confluences=confluences,
            strategy_name=self.name,
            atr_pips=atr_pips_raw * 10000.0 if atr_pips_raw > 0 else None,
        )
