"""Modular alpha layer (docs/10 Phase B).

Each *alpha* is one isolated trading concept (a zone retest, an FVG retest, a
liquidity sweep, the reaction engine, …) measured **on its own** through a clean,
identical fill model. This decomposes the tangled rule-engine blob into pieces we
can keep or cut individually on out-of-sample data — the antidote to overfitting.

See `agent/alphas/base.py` for the interface and `agent/alphas/backtest.py` for
the isolated fill simulator.
"""
from agent.alphas.base import Alpha, AlphaContext, AlphaSignal

__all__ = ["Alpha", "AlphaContext", "AlphaSignal"]
