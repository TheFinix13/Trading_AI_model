"""LiquidityGrabReversal -- a thin shim over the existing liquidity-sweep detector.

A "liquidity grab" here is a recent sweep at a tagged level (PDH/PDL/PWH/PWL/
swing/equal-highs) followed by a close back inside the level. The classic
ICT stop-hunt + reversal. See `agent/detectors/liquidity_sweep.py` for the
detection details.

Best regimes (a priori; pending phase-2 stats):
    * `chop`     -- sweeps are reversion plays, ranges have edges to sweep
    * `high_vol` -- volatility expansion at session opens often presents as a sweep
"""
from __future__ import annotations

from agent.strategy.base import Strategy, build_basic_setup
from agent.types import Direction, Setup


class LiquidityGrabReversal(Strategy):
    name = "LiquidityGrabReversal"
    compatible_regimes = frozenset({"chop", "high_vol", "trending_up", "trending_down"})
    min_confluences = 1
    description = "Recent tagged sweep + close back inside the level."

    def evaluate(self, ctx, at_index: int) -> Setup | None:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 0 or at_index >= len(bars):
            return None
        sweeps = getattr(ctx, "liquidity_sweeps", None) or []
        # Only consider sweeps whose confirm bar already closed and which are
        # within the last 5 bars -- same window the rule engine uses.
        recent = [
            s for s in sweeps
            if s.confirm_bar_index <= at_index and (at_index - s.sweep_bar_index) <= 5
        ]
        if not recent:
            return None
        sweep = recent[-1]
        # Trade the *opposite* of the swept side: a sweep_PDH is a long-stop
        # hunt -> short. Direction on the sweep already encodes this.
        cur = bars[at_index]
        atr_pips = (getattr(ctx, "atr_by_index", {}) or {}).get(at_index, 0.0) * 10000.0
        confluences = [f"sweep_{sweep.swept_label}", "liquidity_grab"]
        return build_basic_setup(
            bar=cur,
            at_index=at_index,
            direction=sweep.direction if isinstance(sweep.direction, Direction) else Direction(sweep.direction),
            confluences=confluences,
            strategy_name=self.name,
            atr_pips=atr_pips if atr_pips > 0 else None,
        )
