"""BOSContinuation -- thin shim over the existing BOS detector.

A break-of-structure within the last ~50 bars in the trade direction.
Engine-side gating (require_fvg_or_sweep_with_bos) still applies in
phase 3+ wiring; this shim just marks the trigger.
"""
from __future__ import annotations

from agent.strategy.base import Strategy, build_basic_setup
from agent.types import Direction, Setup


class BOSContinuation(Strategy):
    name = "BOSContinuation"
    compatible_regimes = frozenset({"trending_up", "trending_down"})
    min_confluences = 1
    description = "Recent break-of-structure in the trade direction."

    BOS_LOOKBACK = 50

    def evaluate(self, ctx, at_index: int) -> Setup | None:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 0 or at_index >= len(bars):
            return None
        bos_list = getattr(ctx, "bos_list", None) or []
        # Most recent BOS at or before this bar.
        recent = [b for b in bos_list if b.broken_bar_index <= at_index
                  and (at_index - b.broken_bar_index) <= self.BOS_LOOKBACK]
        if not recent:
            return None
        bos = recent[-1]
        cur = bars[at_index]
        atr_pips = (getattr(ctx, "atr_by_index", {}) or {}).get(at_index, 0.0) * 10000.0
        return build_basic_setup(
            bar=cur,
            at_index=at_index,
            direction=bos.direction if isinstance(bos.direction, Direction) else Direction(bos.direction),
            confluences=["bos"],
            strategy_name=self.name,
            atr_pips=atr_pips if atr_pips > 0 else None,
        )
