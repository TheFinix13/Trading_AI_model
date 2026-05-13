"""Strategy abstract base class + small construction helpers.

A `Strategy` is a named recipe that wraps existing detector output and
emits candidate `Setup` objects tagged with `strategy_name`. The router
later picks one (or none) based on the current regime + per-(strategy,
regime) win-rate history.

Phase 1 strategies (this commit) are thin shims over existing detector
output; they do not duplicate the rule engine's confluence-stack /
gating logic. The design doc (section 4) lists the migration path.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent.types import Bar, Direction, Setup, Timeframe

# Compatible-regime sentinel meaning "any primary regime".
ANY_REGIME: frozenset[str] = frozenset(
    {"trending_up", "trending_down", "chop", "low_vol", "high_vol", "unknown"}
)


@dataclass
class StrategyMeta:
    """Lightweight metadata bag for the registry."""
    name: str
    compatible_regimes: frozenset[str]
    min_confluences: int
    description: str = ""


class Strategy(ABC):
    """Abstract base for all named strategies.

    Subclasses must:
        * set `name` (registry key, unique within a registry)
        * set `compatible_regimes` (regimes it's willing to fire under)
        * implement `evaluate(ctx, at_index) -> Setup | None`

    `min_confluences` defaults to 1; override per-strategy if needed.
    """

    name: str = "abstract"
    compatible_regimes: frozenset[str] = ANY_REGIME
    min_confluences: int = 1
    description: str = ""

    def meta(self) -> StrategyMeta:
        return StrategyMeta(
            name=self.name,
            compatible_regimes=self.compatible_regimes,
            min_confluences=self.min_confluences,
            description=self.description,
        )

    def is_compatible(self, regime_primary: str) -> bool:
        return regime_primary in self.compatible_regimes

    @abstractmethod
    def evaluate(self, ctx, at_index: int) -> Setup | None:
        """Inspect the precomputed context at `at_index` and return a
        Setup candidate if the strategy's pattern is present, else None.

        Implementations should set `setup.strategy_name = self.name`.
        Use `build_basic_setup` below for a default Setup constructor.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Convenience helpers shared by the strategy shims under
# agent/strategy/strategies/. Kept here so the shims stay tiny.
# ---------------------------------------------------------------------------


def _atr_pips_at(ctx, at_index: int) -> float:
    """Pull a pip-denominated ATR from the precomputed context. Falls
    back to a 30-pip default if the engine didn't precompute ATR (e.g.
    in a unit test that builds ctx by hand)."""
    atr_by_index = getattr(ctx, "atr_by_index", None) or {}
    a = atr_by_index.get(at_index, 0.0)
    if a > 0:
        return max(0.0, a * 10000.0)
    return 30.0


def build_basic_setup(
    *,
    bar: Bar,
    at_index: int,
    direction: Direction,
    confluences: list[str],
    strategy_name: str,
    rr: float = 1.5,
    stop_buffer_pips: float = 5.0,
    atr_pips: float | None = None,
) -> Setup:
    """Construct a minimally-valid Setup for a strategy shim.

    The router does NOT use this to place trades directly -- the existing
    rule engine remains the source of truth for entry/stop/tp during the
    phase-1 instrumentation period. This helper exists so a strategy can
    return a structurally valid `Setup` object for tests, journal
    attribution, and dashboard rendering.

    Stop is sized off ATR (or a 30-pip default), TP at `rr` * stop.
    """
    if atr_pips is None:
        atr_pips = 30.0
    stop_dist_pips = max(15.0, atr_pips) + stop_buffer_pips
    stop_dist = stop_dist_pips * 0.0001

    if direction == Direction.LONG:
        entry = bar.close
        stop = entry - stop_dist
        tp = entry + rr * stop_dist
    else:
        entry = bar.close
        stop = entry + stop_dist
        tp = entry - rr * stop_dist

    return Setup(
        direction=direction,
        timeframe=bar.timeframe,
        detected_at=bar.time,
        detected_bar_index=at_index,
        entry=entry,
        stop=stop,
        take_profit=tp,
        confluences=list(confluences),
        confluence_tfs={c: bar.timeframe.value for c in confluences},
        strategy_name=strategy_name,
    )


__all__ = ["Strategy", "StrategyMeta", "ANY_REGIME", "build_basic_setup"]
