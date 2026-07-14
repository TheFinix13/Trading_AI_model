"""Squad aggregator arms -- phi41 (sealed default) + arm4 (optional).

Ported v1 (unvalidated port) from the research repo:
``sim/scoring/run_phi4_squad_gate.py::_phi4_aggregate`` +
``sim/core/aggregator_arms/multi_position.py`` @ commit e084c5b
(2026-07-14).

phi41 = per-symbol highest-conviction tournament with TIER_BIAS 0.05
so Tier-1 anchors win same-base-conviction ties. arm4 = up to K=2
concurrent positions per symbol from distinct agents (Sentinel R6
combined-risk cap applied by the engine, not here).

This module is deliberately labelled "ported v1 (unvalidated port)"
until the parity harness proves proposal-level fidelity against the
banked g7retry1-phi41 cache.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.squad.types import AgentProposal

TIER_BIAS: float = 0.05
_EFFECTIVE_TIER_RATIONALE_KEY: str = "_effective_tier"


def _effective_tier(proposal: AgentProposal) -> int:
    """Effective tier for aggregator bias (never demotes)."""
    try:
        override = int(proposal.rationale.get(
            _EFFECTIVE_TIER_RATIONALE_KEY, proposal.agent_tier,
        ))
    except (TypeError, ValueError):
        return int(proposal.agent_tier)
    return min(int(proposal.agent_tier), override)


def _tier_adjusted_conviction(proposal: AgentProposal) -> float:
    return float(proposal.conviction) - TIER_BIAS * (_effective_tier(proposal) - 1)


@dataclass
class AggregationOutcome:
    """Accepted winners + structured rejection journal + full ranking."""

    accepted: list[AgentProposal]
    rejected: list[dict[str, Any]]
    ranked_by_symbol: dict[str, list[AgentProposal]] = field(default_factory=dict)


def phi41_aggregate(
    proposals: list[AgentProposal],
    *,
    tick_id: int,
) -> AggregationOutcome:
    """Phi4.1 sealed aggregator: per-symbol highest-conviction wins.

    Sort key is ``(-tier_adjusted_conviction, effective_tier, agent_id)``.
    Losers are journalled with ``rejection_reason="lower_conviction_same_symbol"``.
    """
    if not proposals:
        return AggregationOutcome(accepted=[], rejected=[], ranked_by_symbol={})

    by_sym: dict[str, list[AgentProposal]] = {}
    for p in proposals:
        by_sym.setdefault(p.symbol, []).append(p)

    accepted: list[AgentProposal] = []
    rejected: list[dict[str, Any]] = []
    ranked_by_symbol: dict[str, list[AgentProposal]] = {}

    for sym, plist in by_sym.items():
        plist.sort(
            key=lambda p: (
                -_tier_adjusted_conviction(p),
                _effective_tier(p),
                p.agent_id,
            ),
        )
        ranked_by_symbol[sym] = list(plist)
        winner = plist[0]
        accepted.append(winner)
        for loser in plist[1:]:
            rejected.append({
                "tick_id": int(tick_id),
                "symbol": sym,
                "winner_agent_id": winner.agent_id,
                "winner_conviction": float(winner.conviction),
                "winner_tier": int(winner.agent_tier),
                "loser_agent_id": loser.agent_id,
                "loser_conviction": float(loser.conviction),
                "loser_tier": int(loser.agent_tier),
                "loser_direction": loser.direction,
                "winner_direction": winner.direction,
                "rejection_reason": "lower_conviction_same_symbol",
                "timestamp": loser.timestamp.isoformat(),
            })
    return AggregationOutcome(
        accepted=accepted, rejected=rejected, ranked_by_symbol=ranked_by_symbol,
    )


def aggregate(
    proposals: list[AgentProposal],
    *,
    tick_id: int,
    arm: str = "phi41",
) -> AggregationOutcome:
    """Dispatch on aggregator arm. ``arm4`` uses the same tournament;
    multi-position admission is decided downstream by the engine."""
    if arm not in ("phi41", "arm4", "arm3"):
        raise ValueError(f"unknown aggregator arm: {arm!r}")
    if arm == "arm3":
        from agent.squad.aggregator_arms.same_direction_merge import (
            apply_same_direction_merge,
        )
        proposals = apply_same_direction_merge(proposals, tick_id=tick_id)
    return phi41_aggregate(proposals, tick_id=tick_id)


__all__ = [
    "AggregationOutcome",
    "TIER_BIAS",
    "aggregate",
    "phi41_aggregate",
    "_tier_adjusted_conviction",
    "_effective_tier",
]
