"""FibRetracement — confluence booster, never standalone.

Fibs are drawn only from quality displacement impulses.  The strategy checks
whether price is currently in the OTE zone (61.8-71%) or at the 50% fair-value
level, AND whether another primary strategy (LZI, FVG, Zone) is also firing.
If fib is the only signal present, the strategy returns None.
"""
from __future__ import annotations

from agent.detectors.fib import (
    build_fib_zone,
    fib_confluence_tags,
    invalidate_fib_level,
)
from agent.strategy.base import Strategy, StrategyResult, build_basic_setup
from agent.types import Direction, Setup


class FibRetracement(Strategy):
    name = "FibRetracement"
    compatible_regimes = frozenset({"trending_up", "trending_down", "chop"})
    min_confluences = 1
    description = (
        "Confluence booster: adds fib weight when price is in the OTE zone "
        "or at 50%/38.2% on a quality impulse.  Never trades fib alone."
    )

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

        # --- Step 1: quality gate ---
        if fib.impulse_quality < 35.0:
            return None

        # --- Step 2: invalidation (price past 78.6%) ---
        fib = invalidate_fib_level(fib, bars, at_index)
        if not fib.is_active:
            return None

        cur = bars[at_index]
        atr_pips_raw = (getattr(ctx, "atr_by_index", {}) or {}).get(at_index, 0.0)
        tol_pips = max(15.0, 0.2 * atr_pips_raw * 10000.0)
        tol = tol_pips * 0.0001

        # --- Step 3: is price at a fib level? ---
        tags = fib_confluence_tags(fib, cur, tol=tol)
        if not tags:
            return None

        has_ote = "fib_ote" in tags
        has_50 = "fib_50" in tags
        has_382 = "fib_382" in tags
        if not (has_ote or has_50 or has_382):
            return None

        # --- Step 4: require another primary strategy firing (confluence only) ---
        other_strategy_firing = _has_primary_strategy_signal(ctx, at_index, bars)
        if not other_strategy_firing:
            return None

        direction = fib.direction if isinstance(fib.direction, Direction) else Direction(fib.direction)

        # Build the OTE zone reference if available
        fib_zone = build_fib_zone(fib)
        if fib_zone is not None and has_ote:
            tags.append("fib_ote_zone")

        return build_basic_setup(
            bar=cur,
            at_index=at_index,
            direction=direction,
            confluences=tags,
            strategy_name=self.name,
            atr_pips=atr_pips_raw * 10000.0 if atr_pips_raw > 0 else None,
        )

    def evaluate_explained(self, ctx, at_index: int) -> StrategyResult:
        bars = getattr(ctx, "bars", None)
        if not bars or at_index < 0 or at_index >= len(bars):
            return StrategyResult(strategy_name=self.name, status="NOT_ACTIVE")

        fib_by_index = getattr(ctx, "fib_by_index", None) or {}
        keys = [k for k in fib_by_index.keys() if k <= at_index]
        checks_passed: list[str] = []
        checks_failed: list[str] = []

        if not keys:
            return StrategyResult(
                strategy_name=self.name, status="NOT_ACTIVE",
                checks_failed=["No fib levels computed"],
                next_trigger="Need quality impulse swing for fib drawing",
            )

        fib = fib_by_index[max(keys)]
        if fib is None:
            return StrategyResult(
                strategy_name=self.name, status="NOT_ACTIVE",
                checks_failed=["No valid impulse swing found"],
                next_trigger="Need quality impulse swing for fib drawing",
            )

        if fib.impulse_quality < 35.0:
            checks_failed.append(f"Impulse quality {fib.impulse_quality:.0f} < 35 threshold")
            return StrategyResult(
                strategy_name=self.name, status="NOT_ACTIVE",
                checks_failed=checks_failed,
                next_trigger="Need higher quality impulse (displacement + FVG)",
            )
        checks_passed.append(f"Impulse quality {fib.impulse_quality:.0f} >= 35")

        fib = invalidate_fib_level(fib, bars, at_index)
        if not fib.is_active:
            checks_failed.append("Fib invalidated (price past 78.6%)")
            return StrategyResult(
                strategy_name=self.name, status="NOT_ACTIVE",
                checks_passed=checks_passed, checks_failed=checks_failed,
                next_trigger="Need new impulse swing (current fib invalidated)",
            )

        cur = bars[at_index]
        atr_pips_raw = (getattr(ctx, "atr_by_index", {}) or {}).get(at_index, 0.0)
        tol = max(15.0, 0.2 * atr_pips_raw * 10000.0) * 0.0001
        tags = fib_confluence_tags(fib, cur, tol=tol)

        zones_details: list[str] = []
        for lvl_pct, price in sorted(fib.levels.items()):
            label = f"{lvl_pct * 100:.1f}%"
            dist = abs(cur.close - price) * 10000
            zones_details.append(f"Fib {label} @ {price:.5f} ({dist:.0f} pips away)")

        if not tags or not any(t in tags for t in ("fib_ote", "fib_50", "fib_382")):
            checks_failed.append("Price not at key fib level (OTE/50%/38.2%)")
            return StrategyResult(
                strategy_name=self.name, status="NOT_ACTIVE",
                zones_details=zones_details, checks_passed=checks_passed,
                checks_failed=checks_failed,
                next_trigger="Price must reach OTE zone (61.8-71%) or 50%/38.2%",
            )
        checks_passed.append(f"Price at fib level ({', '.join(tags)})")

        if not _has_primary_strategy_signal(ctx, at_index, bars):
            checks_failed.append("No primary strategy co-firing (fib is confluence-only)")
            return StrategyResult(
                strategy_name=self.name, status="WATCHING",
                zones_details=zones_details, checks_passed=checks_passed,
                checks_failed=checks_failed,
                next_trigger="Need LZI/FVG/Zone signal at this fib level",
            )
        checks_passed.append("Primary strategy co-firing confirmed")

        setup = self.evaluate(ctx, at_index)
        if setup:
            return StrategyResult(
                strategy_name=self.name, signal=setup,
                zones_details=zones_details, checks_passed=checks_passed,
                status="SIGNAL_GENERATED",
            )

        return StrategyResult(
            strategy_name=self.name, status="WATCHING",
            zones_details=zones_details, checks_passed=checks_passed,
            checks_failed=checks_failed,
            next_trigger="Fib + primary strategy alignment detected, awaiting final confirmation",
        )


def _has_primary_strategy_signal(ctx, at_index: int, bars: list) -> bool:
    """Check if any primary strategy (LZI/FVG/Zone) has a signal near at_index."""
    # Check for active zones near price
    cur = bars[at_index]
    zones = getattr(ctx, "zones", None) or []
    for z in zones:
        if getattr(z, "created_bar_index", at_index + 1) <= at_index:
            if not getattr(z, "mitigated", False) and z.contains(cur.close):
                return True

    # Check for recent FVGs
    fvgs = getattr(ctx, "fvgs", None) or []
    for f in fvgs:
        if getattr(f, "created_bar_index", at_index + 1) <= at_index:
            if not getattr(f, "filled", False):
                if f.bottom <= cur.close <= f.top:
                    return True

    # Check for recent BOS
    bos_list = getattr(ctx, "bos_list", None) or []
    for b in bos_list:
        if getattr(b, "broken_bar_index", at_index + 1) <= at_index:
            if (at_index - b.broken_bar_index) <= 10:
                return True

    # Check for liquidity sweeps
    sweeps = getattr(ctx, "liquidity_sweeps", None) or []
    for s in sweeps:
        confirm_idx = getattr(s, "confirm_bar_index", at_index + 1)
        sweep_idx = getattr(s, "sweep_bar_index", at_index + 1)
        if confirm_idx <= at_index and (at_index - sweep_idx) <= 5:
            return True

    return False
