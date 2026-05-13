"""Regime detection for the strategy router.

See `docs/regime_router_design.md` section 3 for the regime taxonomy.
This module exposes the cheap-feature classifier; the router itself
lives in `agent.strategy.registry`.
"""
from agent.regime.detector import RegimeDetector, RegimeLabel

__all__ = ["RegimeDetector", "RegimeLabel"]
