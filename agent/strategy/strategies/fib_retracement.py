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
from agent.strategy.base import Strategy, build_basic_setup
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
