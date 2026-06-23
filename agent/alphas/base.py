"""The Alpha interface — one isolated trading concept (docs/10 §10.4).

An alpha looks at the market on each closed bar and either proposes a complete
trade (`AlphaSignal`) or stays flat (`None`). It does **not** know about gates,
the rule engine, sizing, or other alphas — that separation is the whole point:
each concept's raw edge is measured independently, then the meta-allocator
decides how to combine the survivors.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from agent.config import Config
from agent.rules.engine import PrecomputedContext
from agent.types import Bar, Direction


@dataclass
class AlphaSignal:
    """A complete, self-contained trade proposal from one alpha."""

    direction: Direction
    entry: float
    stop: float
    take_profit: float
    reason: str = ""
    conviction: float = 1.0   # 0..1; used by the portfolio manager's flip gate
    # Optional decision metadata (gate inputs, e.g. HTF bias/align/mode). The
    # trading path ignores this; logging and vault recorders surface it so
    # operators can grep "why did this fire?" without opening the JSON vault.
    meta: dict = field(default_factory=dict)

    @property
    def stop_pips(self) -> float:
        return abs(self.entry - self.stop) * 10000.0

    @property
    def rr(self) -> float:
        sp = self.stop_pips
        return (abs(self.take_profit - self.entry) * 10000.0 / sp) if sp > 0 else 0.0


@dataclass
class AlphaContext:
    """Everything an alpha may need, computed once over the bar series.

    `ctx` is the shared precomputed detector context (zones, fvgs, swings, ATR,
    daily levels, …). Alphas pull what they need and ignore the rest.
    """

    bars: list[Bar]
    ctx: PrecomputedContext
    cfg: Config


class Alpha(ABC):
    """Abstract base for an isolated trading concept."""

    name: str = "abstract"
    description: str = ""

    @abstractmethod
    def signal(self, actx: AlphaContext, i: int) -> Optional[AlphaSignal]:
        """Return a trade proposal for the bar at index ``i`` (a CLOSED bar), or
        None to stay flat. Must be causal: use only ``bars[:i+1]``."""
        raise NotImplementedError
