"""BOSContinuation — quality BOS as a CONTEXT signal, not a standalone entry.

A quality BOS (score >= 50) confirms trend direction. Entry happens when:
  1. A quality BOS fires in a direction
  2. The break left an FVG or order block behind
  3. Price returns to that FVG/OB zone
  4. A reaction is confirmed (rejection wick, engulfing, or displacement)

This makes BOS a MODIFIER that enhances FVG entries, not its own trigger.
Without a tradeable zone left behind by the break, no entry is generated.

Best regimes:
    * ``trending_up``   — bullish BOS confirms continuation entries
    * ``trending_down`` — bearish BOS confirms continuation entries
"""
from __future__ import annotations

from agent.detectors.bos import quality_bos
from agent.detectors.fvg_retest import (
    FVGEntry,
    check_fvg_retest_entries,
    collect_structural_targets,
)
from agent.strategy.base import Strategy, StrategyResult
from agent.types import Direction, FVG, Setup


class BOSContinuation(Strategy):
    name = "BOSContinuation"
    compatible_regimes = frozenset({"trending_up", "trending_down"})
    min_confluences = 1
    description = "Quality BOS + FVG/OB left behind + retest reaction."

    BOS_LOOKBACK = 50
    BOS_MIN_QUALITY = 50.0

    def evaluate(self, ctx, at_index: int) -> Setup | None:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 2 or at_index >= len(bars):
            return None

        bos_list = getattr(ctx, "bos_list", None) or []
        fvgs = getattr(ctx, "fvgs", None) or []

        # Find recent quality BOS events
        recent_quality_bos = quality_bos(
            bos_list, at_index,
            min_quality=self.BOS_MIN_QUALITY,
            max_lookback_bars=self.BOS_LOOKBACK,
        )
        if not recent_quality_bos:
            return None

        # Get FVGs that formed AFTER a quality BOS (the BOS left them behind)
        bos_enhanced_fvgs = self._get_bos_enhanced_fvgs(recent_quality_bos, fvgs, at_index)
        if not bos_enhanced_fvgs:
            return None

        # Gather structural targets
        swings = getattr(ctx, "swings", None)
        daily_levels = None
        dl_list = getattr(ctx, "daily_levels", None)
        if dl_list and at_index < len(dl_list):
            daily_levels = dl_list[at_index]

        # Check for confirmed retest entries on BOS-enhanced FVGs
        for direction in (Direction.LONG, Direction.SHORT):
            dir_fvgs = [f for f in bos_enhanced_fvgs if f.direction == direction]
            if not dir_fvgs:
                continue

            targets = collect_structural_targets(
                bars, at_index, direction,
                swings=swings,
                daily_levels=daily_levels,
            )

            entries = check_fvg_retest_entries(
                bars, dir_fvgs, at_index,
                min_quality_score=30.0,  # Lower threshold since BOS already provides context
                require_reaction=True,
                max_fill_pct=0.80,
                max_revisits=2,
                structural_targets=targets or None,
                fallback_rr=2.0,
            )

            if entries:
                return self._entry_to_setup(entries[0], bars, at_index)

        return None

    def _get_bos_enhanced_fvgs(
        self,
        bos_events: list,
        fvgs: list[FVG],
        at_index: int,
    ) -> list[FVG]:
        """Find FVGs that formed at or shortly after a quality BOS.

        These are the tradeable zones left behind by the structural break.
        The BOS gives them extra significance.
        """
        enhanced: list[FVG] = []
        for bos in bos_events:
            for fvg in fvgs:
                if fvg.is_fully_filled:
                    continue
                if fvg.created_bar_index < at_index and fvg.direction == bos.direction:
                    # FVG formed within 5 bars of the BOS (part of the same impulse)
                    bars_after_bos = fvg.created_bar_index - bos.broken_bar_index
                    if -2 <= bars_after_bos <= 5:
                        enhanced.append(fvg)

        return enhanced

    def _entry_to_setup(self, entry: FVGEntry, bars, at_index: int) -> Setup:
        cur = bars[at_index]
        confluences = list(entry.confluences) + ["bos_context"]
        return Setup(
            direction=entry.direction,
            timeframe=cur.timeframe,
            detected_at=cur.time,
            detected_bar_index=at_index,
            entry=entry.entry_price,
            stop=entry.stop_price,
            take_profit=entry.tp_price,
            confluences=confluences,
            confluence_tfs={c: cur.timeframe.value for c in confluences},
            fvg=entry.fvg,
            strategy_name=self.name,
        )

    def evaluate_explained(self, ctx, at_index: int) -> StrategyResult:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 2 or at_index >= len(bars):
            return StrategyResult(strategy_name=self.name, status="NOT_ACTIVE")

        bos_list = getattr(ctx, "bos_list", None) or []
        fvgs = getattr(ctx, "fvgs", None) or []

        checks_passed: list[str] = []
        checks_failed: list[str] = []
        zones_details: list[str] = []

        recent_quality_bos = quality_bos(
            bos_list, at_index,
            min_quality=self.BOS_MIN_QUALITY,
            max_lookback_bars=self.BOS_LOOKBACK,
        )
        if not recent_quality_bos:
            all_bos = [b for b in bos_list if b.broken_bar_index <= at_index and (at_index - b.broken_bar_index) <= self.BOS_LOOKBACK]
            if all_bos:
                best_q = max(b.quality_score for b in all_bos)
                checks_failed.append(f"BOS found but quality {best_q:.0f} < {self.BOS_MIN_QUALITY:.0f} threshold")
            else:
                checks_failed.append("No recent BOS events in lookback")
            return StrategyResult(
                strategy_name=self.name, status="NOT_ACTIVE",
                checks_failed=checks_failed,
                next_trigger="Need quality break of structure (score >= 50)",
            )

        for b in recent_quality_bos[:3]:
            dir_label = "Bullish" if b.direction == Direction.LONG else "Bearish"
            zones_details.append(
                f"{dir_label} BOS at {b.broken_swing_price:.5f} (quality {b.quality_score:.0f})"
            )
        checks_passed.append(f"Quality BOS found ({len(recent_quality_bos)})")

        bos_enhanced_fvgs = self._get_bos_enhanced_fvgs(recent_quality_bos, fvgs, at_index)
        if not bos_enhanced_fvgs:
            checks_failed.append("BOS did not leave an FVG/OB behind")
            return StrategyResult(
                strategy_name=self.name, zones_found=len(recent_quality_bos),
                zones_details=zones_details, checks_passed=checks_passed,
                checks_failed=checks_failed, status="NOT_ACTIVE",
                next_trigger="Need BOS impulse to create an FVG left behind",
            )

        checks_passed.append(f"BOS-enhanced FVG(s) found ({len(bos_enhanced_fvgs)})")
        for f in bos_enhanced_fvgs[:3]:
            dir_label = "bullish" if f.direction == Direction.LONG else "bearish"
            zones_details.append(f"FVG {dir_label} @ {f.bottom:.4f}-{f.top:.4f} (left by BOS)")

        cur = bars[at_index]
        swings = getattr(ctx, "swings", None)
        daily_levels = None
        dl_list = getattr(ctx, "daily_levels", None)
        if dl_list and at_index < len(dl_list):
            daily_levels = dl_list[at_index]

        for direction in (Direction.LONG, Direction.SHORT):
            dir_fvgs = [f for f in bos_enhanced_fvgs if f.direction == direction]
            if not dir_fvgs:
                continue
            for f in dir_fvgs[:2]:
                price_touched = cur.low <= f.top and cur.high >= f.bottom
                if price_touched:
                    checks_passed.append(f"Price touched BOS-FVG {f.bottom:.4f}-{f.top:.4f}")
                else:
                    dist = min(abs(cur.close - f.top), abs(cur.close - f.bottom)) * 10000
                    checks_failed.append(f"Price not at BOS-FVG ({dist:.0f} pips away)")

            targets = collect_structural_targets(
                bars, at_index, direction, swings=swings, daily_levels=daily_levels,
            )
            entries = check_fvg_retest_entries(
                bars, dir_fvgs, at_index, min_quality_score=30.0,
                require_reaction=True, max_fill_pct=0.80, max_revisits=2,
                structural_targets=targets or None, fallback_rr=2.0,
            )
            if entries:
                setup = self._entry_to_setup(entries[0], bars, at_index)
                return StrategyResult(
                    strategy_name=self.name, signal=setup,
                    zones_found=len(bos_enhanced_fvgs), zones_details=zones_details,
                    checks_passed=checks_passed, status="SIGNAL_GENERATED",
                )

        return StrategyResult(
            strategy_name=self.name,
            zones_found=len(bos_enhanced_fvgs),
            zones_details=zones_details,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            status="WATCHING" if any("touched" in c for c in checks_passed) else "NOT_ACTIVE",
            next_trigger="Need price to retest BOS-FVG with confirmed reaction",
        )
