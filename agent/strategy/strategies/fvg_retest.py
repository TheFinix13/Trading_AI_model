"""FVGRetest — two-phase FVG retest strategy.

Phase 1: Detect quality-graded FVGs (size, displacement, session, fill state).
Phase 2: Wait for price to return to FVG AND show a confirmed reaction.

Reaction types (any one confirms entry):
  - Rejection wick: bar enters FVG, wick shows strong rejection (>50% of range)
  - Engulfing: previous bar in FVG, current bar engulfs in direction
  - Displacement: previous bar in FVG, current bar displaces away (body > 60%, > 6 pips)

This replaces the old touch-and-enter approach. Only institutional-grade FVGs
with confirmed reactions produce entries.

Best regimes:
    * ``trending_up``   — bullish FVGs as pullback entries
    * ``trending_down`` — bearish FVGs as pullback entries
    * ``high_vol``      — displacement creates larger, more reliable FVGs
"""
from __future__ import annotations

from agent.detectors.fvg import quality_fvgs
from agent.detectors.fvg_retest import (
    FVGEntry,
    check_fvg_retest_entries,
    collect_structural_targets,
)
from agent.strategy.base import Strategy
from agent.types import Direction, Setup


class FVGRetest(Strategy):
    name = "FVGRetest"
    compatible_regimes = frozenset({"trending_up", "trending_down", "high_vol"})
    min_confluences = 1
    description = "Two-phase FVG retest: quality FVG → price return → reaction confirmation."

    def evaluate(self, ctx, at_index: int) -> Setup | None:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 2 or at_index >= len(bars):
            return None

        fvgs = getattr(ctx, "fvgs", None) or []
        if not fvgs:
            return None

        # Gather structural targets for TP computation
        swings = getattr(ctx, "swings", None)
        daily_levels = None
        dl_list = getattr(ctx, "daily_levels", None)
        if dl_list and at_index < len(dl_list):
            daily_levels = dl_list[at_index]

        # Try both directions — FVG carries its own direction
        for direction in (Direction.LONG, Direction.SHORT):
            dir_fvgs = [f for f in fvgs if f.direction == direction]
            if not dir_fvgs:
                continue

            targets = collect_structural_targets(
                bars, at_index, direction,
                swings=swings,
                daily_levels=daily_levels,
            )

            entries = check_fvg_retest_entries(
                bars, dir_fvgs, at_index,
                min_quality_score=40.0,
                require_reaction=True,
                max_fill_pct=0.80,
                max_revisits=2,
                structural_targets=targets or None,
                fallback_rr=2.0,
            )

            if entries:
                return self._entry_to_setup(entries[0], bars, at_index)

        return None

    def _entry_to_setup(self, entry: FVGEntry, bars, at_index: int) -> Setup:
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
            fvg=entry.fvg,
            strategy_name=self.name,
        )
