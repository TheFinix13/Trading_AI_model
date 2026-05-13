"""FVGRetest -- thin shim over the existing FVG detector.

A bar overlapping an unfilled, same-direction FVG. Phase-1 implementation
just emits a Setup; the real (phase 3+) version will require a structural
anchor (fib / phase / session) before counting.
"""
from __future__ import annotations

from agent.strategy.base import Strategy, build_basic_setup
from agent.types import Direction, Setup


class FVGRetest(Strategy):
    name = "FVGRetest"
    compatible_regimes = frozenset({"trending_up", "trending_down", "high_vol"})
    min_confluences = 1
    description = "Bar overlaps an unfilled same-direction FVG."

    def evaluate(self, ctx, at_index: int) -> Setup | None:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 0 or at_index >= len(bars):
            return None
        fvgs = getattr(ctx, "fvgs", None) or []
        if not fvgs:
            return None
        cur = bars[at_index]
        atr_pips_raw = (getattr(ctx, "atr_by_index", {}) or {}).get(at_index, 0.0)
        # Use ATR-derived tolerance the same way the engine does.
        tol_pips = max(15.0, 0.2 * atr_pips_raw * 10000.0)
        tol = tol_pips * 0.0001

        # Iterate newest-first so we pick the freshest active FVG.
        for f in reversed(fvgs[-25:]):
            if f.filled:
                continue
            if f.created_bar_index > at_index:
                continue
            if (cur.low <= f.top + tol) and (cur.high >= f.bottom - tol):
                direction = f.direction if isinstance(f.direction, Direction) else Direction(f.direction)
                return build_basic_setup(
                    bar=cur,
                    at_index=at_index,
                    direction=direction,
                    confluences=["fvg"],
                    strategy_name=self.name,
                    atr_pips=atr_pips_raw * 10000.0 if atr_pips_raw > 0 else None,
                )
        return None
