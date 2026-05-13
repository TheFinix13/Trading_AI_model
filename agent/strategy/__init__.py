"""Regime-aware strategy router.

See `docs/regime_router_design.md` for the full design. This package is
scaffolded but NOT yet wired into the rule engine -- a future commit
will replace the engine's single decision path with a router + per-
strategy gating.
"""
from agent.strategy.base import Strategy
from agent.strategy.registry import (
    StrategyRegistry,
    StrategyRouter,
    StrategyStats,
    default_registry,
)

__all__ = [
    "Strategy",
    "StrategyRegistry",
    "StrategyRouter",
    "StrategyStats",
    "default_registry",
]
