"""BlueLockStriker Protocol + BaseStriker abstract base class.

Ported v1 (unvalidated port) from the research repo:
``finance-research-experiments/programs/M001_multi_agent_ensemble/
sim/core/striker.py`` @ commit e084c5b (2026-07-14).

Every agent observes every tick (always emits a Thought), intends only
at home-TF close (may emit an AgentProposal / YieldReason / None), owns
lot-size cognition (F19), owns SL/TP-shape cognition (F20), and
participates in the shared reasoning workspace (F21).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Protocol

import numpy as np

from agent.squad.ledger import ThoughtLedger
from agent.squad.lot_intent import Playstyle, default_lot_intent, playstyle_lot_intent
from agent.squad.workspace import Tier, WorkspaceSnapshot
from agent.squad.risk_intent import default_risk_intent, playstyle_risk_intent
from agent.squad.seed import seed, seed_for
from agent.squad.types import (
    CanonRole,
    IntentDecision,
    MarketState,
    Symbol,
    Thought,
)


class BlueLockStriker(Protocol):
    """The contract every roster agent implements."""

    agent_id: str
    canon_role: CanonRole
    home_tf: str
    symbols: list[Symbol]
    playstyle: Playstyle | str
    tier: Tier

    def observe(self, market: MarketState, ledger: ThoughtLedger) -> Thought: ...

    def intend(
        self,
        market: MarketState,
        my_recent_thought: Thought,
        *,
        workspace: WorkspaceSnapshot | None = None,
    ) -> IntentDecision: ...

    def lot_intent(
        self,
        conviction: float,
        sl_pips: float,
        equity: float,
        regime_fit: float,
    ) -> float: ...

    def risk_intent(
        self,
        conviction: float,
        atr_pips: float,
        h1_swing_pips: float,
    ) -> tuple[float, list[float]]: ...

    def read_workspace(
        self,
        workspace: WorkspaceSnapshot,
        as_of: datetime,
    ) -> tuple[Thought, ...]: ...


class BaseStriker(ABC):
    """Abstract base with deterministic helpers + F19/F20/F21 defaults."""

    agent_id: str
    canon_role: CanonRole
    home_tf: str
    symbols: list[Symbol]
    playstyle: Playstyle | str
    tier: Tier

    def __init__(
        self,
        agent_id: str,
        canon_role: CanonRole,
        home_tf: str,
        symbols: list[Symbol],
        *,
        playstyle: Playstyle | str = "unknown",
        tier: Tier = 2,
    ) -> None:
        self.agent_id = agent_id
        self.canon_role = canon_role
        self.home_tf = home_tf
        self.symbols = list(symbols)
        self.playstyle = playstyle
        self.tier = tier

    def rng(self, tick_id: int, channel: str = "default") -> np.random.Generator:
        return np.random.default_rng(seed_for(self.agent_id, tick_id, channel))

    def base_seed(self, tick_id: int) -> int:
        return seed(self.agent_id, tick_id)

    @abstractmethod
    def observe(self, market: MarketState, ledger: ThoughtLedger) -> Thought:
        raise NotImplementedError

    @abstractmethod
    def intend(
        self,
        market: MarketState,
        my_recent_thought: Thought,
    ) -> IntentDecision:
        raise NotImplementedError

    def lot_intent(
        self,
        conviction: float,
        sl_pips: float,
        equity: float,
        regime_fit: float,
    ) -> float:
        if self.playstyle == "unknown":
            return default_lot_intent(conviction, sl_pips, equity, regime_fit)
        return playstyle_lot_intent(
            conviction, sl_pips, equity, regime_fit,
            playstyle=self.playstyle,  # type: ignore[arg-type]
        )

    def risk_intent(
        self,
        conviction: float,
        atr_pips: float,
        h1_swing_pips: float,
    ) -> tuple[float, list[float]]:
        if self.playstyle == "unknown":
            return default_risk_intent(conviction, atr_pips, h1_swing_pips)
        return playstyle_risk_intent(
            conviction, atr_pips, h1_swing_pips,
            playstyle=self.playstyle,  # type: ignore[arg-type]
        )

    def read_workspace(
        self,
        workspace: WorkspaceSnapshot,
        as_of: datetime,  # noqa: ARG002
    ) -> tuple[Thought, ...]:
        return workspace.read_for(agent_id=self.agent_id, tier=self.tier)

    def report_kpis(self, week_id: str) -> dict:
        return {
            "agent_id": self.agent_id,
            "week_id": week_id,
            "assertion_rate": None,
            "coexistence_rate": None,
            "devour_rate": None,
            "goal_rate": None,
            "beauty_rate": None,
            "_status": "ported_v1_placeholder",
        }
