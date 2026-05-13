"""Registry + router for the regime-aware strategy framework.

`StrategyRegistry`  -- holds named strategies, enforces unique names.
`StrategyStats`     -- per-(strategy, regime) win-rate / profit-factor.
`StrategyRouter`    -- routes a bar through compatible strategies and
                       picks one candidate (or none) using stats.

This module is deliberately decoupled from the rule engine -- a future
PR will compose them at the call site. Phase 1 just gives us the
shape and a battery of unit tests so the shape is stable before we
start changing engine behaviour.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Optional

from agent.regime.detector import RegimeLabel
from agent.strategy.base import Strategy
from agent.types import Setup

log = logging.getLogger(__name__)

MIN_SAMPLES_FOR_PRIOR_OVERRIDE = 30
NEUTRAL_PRIOR_SCORE = 0.5
MIN_SELECTION_SCORE = 0.45  # below this, the router returns None


@dataclass
class StrategyStats:
    """Realised performance for one (strategy, regime) cell.

    Surfaces the three numbers the router needs (`wr`, `pf`, `n`)
    and a thin update method so a journal replay can populate it
    incrementally.
    """
    wins: int = 0
    losses: int = 0
    pnl_pips: float = 0.0
    sum_win_pips: float = 0.0
    sum_loss_pips: float = 0.0  # always >= 0 (absolute value of losses)

    @property
    def n(self) -> int:
        return self.wins + self.losses

    @property
    def wr(self) -> float:
        if self.n == 0:
            return 0.0
        return self.wins / self.n

    @property
    def pf(self) -> float:
        if self.sum_loss_pips <= 0:
            return float("inf") if self.sum_win_pips > 0 else 0.0
        return self.sum_win_pips / self.sum_loss_pips

    def record(self, pnl_pips: float) -> None:
        self.pnl_pips += pnl_pips
        if pnl_pips > 0:
            self.wins += 1
            self.sum_win_pips += pnl_pips
        else:
            self.losses += 1
            self.sum_loss_pips += abs(pnl_pips)

    def score(self) -> float:
        """Combined edge score (WR weighted by capped profit factor).

        Capped at PF=3.0 so an outlier trade can't dominate. Below
        `MIN_SAMPLES_FOR_PRIOR_OVERRIDE` we return the neutral prior
        so under-sampled cells don't get routed away from prematurely.
        """
        if self.n < MIN_SAMPLES_FOR_PRIOR_OVERRIDE:
            return NEUTRAL_PRIOR_SCORE
        pf = self.pf
        if math.isinf(pf):
            pf_capped = 3.0
        else:
            pf_capped = min(3.0, max(0.0, pf))
        # WR in [0,1], pf_capped in [0,3] -> normalise pf to [0,1].
        return self.wr * (pf_capped / 3.0)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class StrategyRegistry:
    """Container for named strategies. Guarantees unique names.

    Strategies are usually registered at import time:

        registry = StrategyRegistry()
        registry.register(LiquidityGrabReversal())
        registry.register(FVGRetest())
        ...

    or pulled in en-bloc via :func:`default_registry`."""

    def __init__(self) -> None:
        self._by_name: dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        if strategy.name in self._by_name:
            raise ValueError(f"Strategy already registered: {strategy.name!r}")
        self._by_name[strategy.name] = strategy

    def unregister(self, name: str) -> None:
        self._by_name.pop(name, None)

    def get(self, name: str) -> Strategy | None:
        return self._by_name.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __iter__(self):
        return iter(self._by_name.values())

    def __len__(self) -> int:
        return len(self._by_name)

    def names(self) -> list[str]:
        return sorted(self._by_name.keys())

    def compatible(self, regime_primary: str) -> list[Strategy]:
        return [s for s in self._by_name.values() if s.is_compatible(regime_primary)]


# ---------------------------------------------------------------------------
# History (per-(strategy, regime) stats table)
# ---------------------------------------------------------------------------


class StatsHistory:
    """In-memory `(strategy_name, regime_primary) -> StrategyStats` map.

    A journal replay can populate this; a dashboard query can read it.
    The router treats it as read-only at decision time.
    """

    def __init__(self) -> None:
        self._table: dict[tuple[str, str], StrategyStats] = {}

    def get(self, strategy_name: str, regime_primary: str) -> StrategyStats:
        return self._table.get((strategy_name, regime_primary), StrategyStats())

    def set(self, strategy_name: str, regime_primary: str, stats: StrategyStats) -> None:
        self._table[(strategy_name, regime_primary)] = stats

    def record(self, strategy_name: str, regime_primary: str, pnl_pips: float) -> None:
        key = (strategy_name, regime_primary)
        if key not in self._table:
            self._table[key] = StrategyStats()
        self._table[key].record(pnl_pips)

    def __len__(self) -> int:
        return len(self._table)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@dataclass
class RouterDecision:
    """Diagnostic record of one routing decision. Useful for the
    dashboard / explain mode."""
    chosen: Setup | None
    candidates: list[Setup]
    scores: dict[str, float]
    regime: RegimeLabel | None


class StrategyRouter:
    """Composes a registry + a stats history into per-bar decisions.

    Two public entry points:
        * `route(ctx, at_index)`             -- raw candidates from
                                                compatible strategies.
        * `select_best(candidates, regime, history)` -- one (or None).

    `decide(ctx, at_index, regime)` is a convenience that calls both.
    """

    def __init__(
        self,
        registry: StrategyRegistry,
        history: StatsHistory | None = None,
        *,
        min_score: float = MIN_SELECTION_SCORE,
    ) -> None:
        self.registry = registry
        self.history = history or StatsHistory()
        self.min_score = min_score

    def route(self, ctx, at_index: int, regime: RegimeLabel | None = None) -> list[Setup]:
        """Run every compatible strategy and collect the non-None Setups.

        When `regime` is None, every registered strategy is consulted;
        when it's provided, only strategies whose `compatible_regimes`
        include the regime's `primary` are run."""
        if regime is None:
            strategies: Iterable[Strategy] = list(self.registry)
        else:
            strategies = self.registry.compatible(regime.primary)
        out: list[Setup] = []
        for strat in strategies:
            try:
                setup = strat.evaluate(ctx, at_index)
            except Exception as e:
                log.exception("Strategy %s raised during evaluate(): %s", strat.name, e)
                continue
            if setup is None:
                continue
            if setup.strategy_name is None:
                setup.strategy_name = strat.name
            out.append(setup)
        return out

    def select_best(
        self,
        candidates: list[Setup],
        regime: RegimeLabel | None,
        history: StatsHistory | None = None,
    ) -> Setup | None:
        """Pick one candidate using per-(strategy, regime) stats.

        Returns None when no candidate clears `min_score`. Falls back to
        the neutral prior of 0.5 for under-sampled cells (see
        `StrategyStats.score`).
        """
        if not candidates:
            return None
        h = history or self.history
        regime_key = regime.primary if regime else "unknown"
        scored: list[tuple[float, Setup]] = []
        for s in candidates:
            name = s.strategy_name or ""
            stats = h.get(name, regime_key)
            scored.append((stats.score(), s))
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best = scored[0]
        if best_score < self.min_score:
            return None
        return best

    def decide(self, ctx, at_index: int, regime: RegimeLabel | None) -> RouterDecision:
        cands = self.route(ctx, at_index, regime)
        chosen = self.select_best(cands, regime)
        h = self.history
        regime_key = regime.primary if regime else "unknown"
        scores = {
            (s.strategy_name or "?"): h.get(s.strategy_name or "", regime_key).score()
            for s in cands
        }
        return RouterDecision(chosen=chosen, candidates=cands, scores=scores, regime=regime)


# ---------------------------------------------------------------------------
# Default registry assembly. Imported lazily to avoid circular imports
# when `agent.strategy.strategies.*` is being defined.
# ---------------------------------------------------------------------------


def default_registry() -> StrategyRegistry:
    """Build a registry containing all the phase-1 shim strategies.

    The shim modules import only stdlib + agent.types + agent.strategy.base,
    so this is safe to call at module import time.
    """
    from agent.strategy.strategies.bos_continuation import BOSContinuation
    from agent.strategy.strategies.fib_retracement import FibRetracement
    from agent.strategy.strategies.fvg_retest import FVGRetest
    from agent.strategy.strategies.liquidity_grab_reversal import LiquidityGrabReversal
    from agent.strategy.strategies.sd_zone_retest import SDZoneRetest

    reg = StrategyRegistry()
    reg.register(LiquidityGrabReversal())
    reg.register(FVGRetest())
    reg.register(BOSContinuation())
    reg.register(FibRetracement())
    reg.register(SDZoneRetest())
    return reg


__all__ = [
    "StrategyRegistry",
    "StrategyRouter",
    "StrategyStats",
    "StatsHistory",
    "RouterDecision",
    "default_registry",
    "MIN_SELECTION_SCORE",
    "MIN_SAMPLES_FOR_PRIOR_OVERRIDE",
]
