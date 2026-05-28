"""SDZoneRetest — quality-graded zone retest strategy with reaction confirmation.

Uses the upgraded zone detector with:
  - Order-block boundary precision (zone = last opposing candle(s))
  - Quality scoring (origin, tightness, departure, session, FVG)
  - Depletion tracking (revisit count, fill percentage)
  - Two-phase entry (zone touch + reaction confirmation)
"""
from __future__ import annotations

from agent.detectors.zone_retest import ZoneEntry, check_zone_retest_entries
from agent.detectors.zones import (
    QualifiedZone,
    detect_qualified_zones,
    fresh_qualified_zones,
)
from agent.strategy.base import Strategy, StrategyResult, build_basic_setup
from agent.types import Direction, Setup


class SDZoneRetest(Strategy):
    name = "SDZoneRetest"
    compatible_regimes = frozenset({"chop", "low_vol", "high_vol", "trending_up", "trending_down"})
    min_confluences = 1
    description = "Quality-graded SD zone retest with reaction confirmation."

    def evaluate(self, ctx, at_index: int) -> Setup | None:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 1 or at_index >= len(bars):
            return None

        # Use qualified zones if available, fall back to legacy
        qualified_zones = getattr(ctx, "qualified_zones", None)
        if not qualified_zones:
            # Try to detect on the fly (expensive but functional for tests)
            zones = getattr(ctx, "zones", None) or []
            if not zones:
                return None
            # Legacy path: use old zone list with basic overlap check
            return self._legacy_evaluate(ctx, bars, zones, at_index)

        # Two-phase entry with quality gating
        entries = check_zone_retest_entries(
            bars,
            qualified_zones,
            at_index,
            min_quality_score=45.0,
            max_revisits=2,
            max_fill_pct=0.80,
            require_reaction=True,
        )

        if not entries:
            return None

        # Pick the highest quality entry
        best = max(entries, key=lambda e: e.quality_score)
        atr_pips = self._get_atr_pips(ctx, at_index)

        return build_basic_setup(
            bar=bars[at_index],
            at_index=at_index,
            direction=best.direction,
            confluences=best.confluences,
            strategy_name=self.name,
            atr_pips=atr_pips,
        )

    def _legacy_evaluate(self, ctx, bars, zones, at_index: int) -> Setup | None:
        """Backward-compatible path using unqualified Zone objects."""
        from agent.detectors.zones import fresh_zones

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

    def _get_atr_pips(self, ctx, at_index: int) -> float | None:
        atr_by_index = getattr(ctx, "atr_by_index", None) or {}
        a = atr_by_index.get(at_index, 0.0)
        return max(0.0, a * 10000.0) if a > 0 else None

    def evaluate_explained(self, ctx, at_index: int) -> StrategyResult:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 1 or at_index >= len(bars):
            return StrategyResult(strategy_name=self.name, status="NOT_ACTIVE")

        qualified_zones = getattr(ctx, "qualified_zones", None)
        zones = getattr(ctx, "zones", None) or []
        cur = bars[at_index]

        zones_details: list[str] = []
        checks_passed: list[str] = []
        checks_failed: list[str] = []
        best_status = "NOT_ACTIVE"
        next_trigger = ""

        if not qualified_zones and not zones:
            return StrategyResult(
                strategy_name=self.name, status="NOT_ACTIVE",
                checks_failed=["No SD zones detected"],
                next_trigger="Need impulsive move to create supply/demand zone",
            )

        if qualified_zones:
            for qz in qualified_zones[:6]:
                dir_label = "Supply" if qz.direction == Direction.SHORT else "Demand"
                q_score = qz.quality.quality_score if hasattr(qz, "quality") else 0
                grade = "A" if q_score >= 70 else ("B" if q_score >= 45 else "C")
                zones_details.append(
                    f"{dir_label} {qz.bottom:.4f}-{qz.top:.4f} "
                    f"(quality {grade}, score {q_score:.0f})"
                )

            for qz in qualified_zones:
                q_score = qz.quality.quality_score if hasattr(qz, "quality") else 0
                price_in_zone = cur.low <= qz.top and cur.high >= qz.bottom
                if price_in_zone:
                    checks_passed.append(f"Price in zone {qz.bottom:.4f}-{qz.top:.4f}")
                    if q_score >= 45:
                        checks_passed.append(f"Zone quality {q_score:.0f} >= 45 threshold")
                        best_status = "WATCHING"
                        next_trigger = "Need reaction confirmation (rejection wick or engulfing)"
                    else:
                        checks_failed.append(f"Zone quality {q_score:.0f} < 45 threshold")
                else:
                    dist = min(abs(cur.close - qz.top), abs(cur.close - qz.bottom)) * 10000
                    if dist < 20:
                        checks_failed.append(f"Price approaching zone ({dist:.0f} pips away)")
                        if best_status != "WATCHING":
                            next_trigger = f"Price must reach zone {qz.bottom:.4f}-{qz.top:.4f}"
                    else:
                        checks_failed.append(f"Price not in zone (current {cur.close:.5f}, zone starts {qz.bottom:.4f})")

            entries = check_zone_retest_entries(
                bars, qualified_zones, at_index,
                min_quality_score=45.0, max_revisits=2,
                max_fill_pct=0.80, require_reaction=True,
            )
            if entries:
                best = max(entries, key=lambda e: e.quality_score)
                atr_pips = self._get_atr_pips(ctx, at_index)
                setup = build_basic_setup(
                    bar=cur, at_index=at_index, direction=best.direction,
                    confluences=best.confluences, strategy_name=self.name,
                    atr_pips=atr_pips,
                )
                return StrategyResult(
                    strategy_name=self.name, signal=setup,
                    zones_found=len(qualified_zones), zones_details=zones_details,
                    checks_passed=checks_passed, status="SIGNAL_GENERATED",
                )
        else:
            for z in zones[:6]:
                dir_label = "Supply" if z.direction == Direction.SHORT else "Demand"
                zones_details.append(
                    f"{dir_label} {z.bottom:.4f}-{z.top:.4f} "
                    f"(impulse {z.impulse_pips:.0f} pips)"
                )
            legacy = self._legacy_evaluate(ctx, bars, zones, at_index)
            if legacy:
                return StrategyResult(
                    strategy_name=self.name, signal=legacy,
                    zones_found=len(zones), zones_details=zones_details,
                    checks_passed=["Legacy zone overlap detected"],
                    status="SIGNAL_GENERATED",
                )

        return StrategyResult(
            strategy_name=self.name,
            zones_found=len(qualified_zones or zones),
            zones_details=zones_details,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            status=best_status,
            next_trigger=next_trigger,
        )
