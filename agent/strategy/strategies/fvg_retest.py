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
from agent.strategy.base import Strategy, StrategyResult
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

        swings = getattr(ctx, "swings", None)
        daily_levels = None
        dl_list = getattr(ctx, "daily_levels", None)
        if dl_list and at_index < len(dl_list):
            daily_levels = dl_list[at_index]

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

    def evaluate_explained(self, ctx, at_index: int) -> StrategyResult:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 2 or at_index >= len(bars):
            return StrategyResult(strategy_name=self.name, status="NOT_ACTIVE")

        fvgs = getattr(ctx, "fvgs", None) or []
        if not fvgs:
            return StrategyResult(
                strategy_name=self.name, status="NOT_ACTIVE",
                checks_failed=["No FVGs detected in lookback"],
                next_trigger="Need impulsive candle to create FVG",
            )

        cur = bars[at_index]
        swings = getattr(ctx, "swings", None)
        daily_levels = None
        dl_list = getattr(ctx, "daily_levels", None)
        if dl_list and at_index < len(dl_list):
            daily_levels = dl_list[at_index]

        zones_details: list[str] = []
        checks_passed: list[str] = []
        checks_failed: list[str] = []
        best_status = "NOT_ACTIVE"
        next_trigger = ""

        # Describe all FVGs
        active_fvgs = [f for f in fvgs if f.created_bar_index <= at_index and not f.is_fully_filled]
        for f in active_fvgs[:6]:
            dir_label = "bullish" if f.direction == Direction.LONG else "bearish"
            grade = "A" if f.quality_score >= 70 else ("B+" if f.quality_score >= 55 else ("B" if f.quality_score >= 40 else "C"))
            fill_str = f"{f.fill_pct * 100:.0f}% filled" if f.fill_pct > 0 else "unfilled"
            zones_details.append(
                f"{dir_label} @ {f.bottom:.4f}-{f.top:.4f} (grade {grade}, {fill_str})"
            )

        for direction in (Direction.LONG, Direction.SHORT):
            dir_fvgs = [f for f in active_fvgs if f.direction == direction]
            if not dir_fvgs:
                continue

            quality_fvg_list = [f for f in dir_fvgs if f.quality_score >= 40.0]
            if quality_fvg_list:
                checks_passed.append(f"Quality FVG(s) found ({len(quality_fvg_list)})")
            else:
                checks_failed.append(f"FVGs exist but quality < 40 (best: {max(f.quality_score for f in dir_fvgs):.0f})")
                continue

            for f in quality_fvg_list[:2]:
                price_touched = cur.low <= f.top and cur.high >= f.bottom
                if price_touched:
                    checks_passed.append(f"Price touched FVG boundary ({f.bottom:.4f}-{f.top:.4f})")
                    # Check reaction
                    bar_range = cur.high - cur.low
                    if bar_range > 0:
                        if direction == Direction.LONG:
                            wick_ratio = cur.lower_wick / bar_range
                        else:
                            wick_ratio = cur.upper_wick / bar_range
                        if wick_ratio > 0.5:
                            checks_passed.append("Reaction: rejection wick confirmed")
                        else:
                            checks_failed.append("Reaction: no strong rejection wick yet")
                            best_status = "WATCHING"
                            next_trigger = "Need bar close with reaction (rejection wick or engulfing)"
                    else:
                        checks_failed.append("Reaction: bar still forming, no rejection wick")
                        best_status = "WATCHING"
                        next_trigger = "Need bar close with reaction"
                else:
                    dist_pips = min(abs(cur.close - f.top), abs(cur.close - f.bottom)) * 10000
                    checks_failed.append(f"Price not in FVG (current {cur.close:.5f}, {dist_pips:.0f} pips away)")
                    if best_status != "WATCHING":
                        next_trigger = f"Price must reach FVG @ {f.bottom:.4f}-{f.top:.4f}"

            targets = collect_structural_targets(
                bars, at_index, direction,
                swings=swings, daily_levels=daily_levels,
            )
            entries = check_fvg_retest_entries(
                bars, dir_fvgs, at_index,
                min_quality_score=40.0, require_reaction=True,
                max_fill_pct=0.80, max_revisits=2,
                structural_targets=targets or None, fallback_rr=2.0,
            )
            if entries:
                setup = self._entry_to_setup(entries[0], bars, at_index)
                return StrategyResult(
                    strategy_name=self.name, signal=setup,
                    zones_found=len(active_fvgs), zones_details=zones_details,
                    checks_passed=checks_passed, status="SIGNAL_GENERATED",
                )

        return StrategyResult(
            strategy_name=self.name,
            zones_found=len(active_fvgs),
            zones_details=zones_details,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            status=best_status,
            next_trigger=next_trigger,
        )

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
