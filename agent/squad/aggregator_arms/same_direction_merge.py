"""Arm 3 of the Phi5 aggregator experiment -- same-direction merge.

When N >= 2 agents propose the SAME direction on the SAME symbol within
window W = 1 H4 bar (i.e. concurrent on the same tick close), merge into
a single AgentProposal with:

- SL = tightest (max stop for long, min stop for short)
- TP = median across proposal ladders' target prices
- Conviction = max across contributors (winner-takes-all)
- Source attribution = all contributing agent IDs journalled in rationale

This is DIFFERENT from the Phi2.5 `aggregator.aggregate` same-direction
rule (which SUMS conviction and picks winner's ladder). Arm 3 gives a
merged intent whose sizing is controlled by the max conviction, not the
sum -- prevents artificial size inflation from concurrent proposals.

Opposite-direction proposals are NOT touched by this arm (that's still
the aggregator's downstream opposing-highest-conviction rule).

Reference: `experiments/phi5_aggregator/PROTOCOL.md` §3.2 Arm 3.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Iterable

from agent.squad.types import AgentProposal, LadderRung


def _merged_stop(members: list[AgentProposal]) -> float:
    """Tightest-stop rule: for long, largest stop value (closest to entry).
    For short, smallest stop value."""
    direction = members[0].direction
    if direction == "long":
        return max(m.stop for m in members)
    if direction == "short":
        return min(m.stop for m in members)
    return members[0].stop


def _median_ladder(members: list[AgentProposal]) -> list[LadderRung]:
    """Median-of-TPs ladder: for each rung index i, take the median of
    each member's rung-i price. Fractions come from the max-conviction
    member (canonical shape).

    Members may have different-length ladders. We normalise to the
    modal (most common) length; shorter ladders zero-pad by repeating
    the final rung, longer ladders truncate. In practice Phi4.1 agents
    have uniform ladder lengths within each agent.
    """
    if not members:
        return []
    max_conviction = max(members, key=lambda m: m.conviction)
    canon_ladder = max_conviction.ladder
    if len(canon_ladder) == 0:
        return []
    n_rungs = len(canon_ladder)
    merged: list[LadderRung] = []
    for i in range(n_rungs):
        prices_i: list[float] = []
        for m in members:
            if i < len(m.ladder):
                prices_i.append(m.ladder[i].price)
            else:
                # Reuse the member's final rung price if the ladder is shorter.
                prices_i.append(m.ladder[-1].price)
        merged.append(LadderRung(
            price=float(median(prices_i)),
            fraction=canon_ladder[i].fraction,
        ))
    return merged


def _merge_group(
    members: list[AgentProposal],
    tick_id: int,
) -> AgentProposal:
    """Merge N >= 2 same-direction proposals into a single proposal."""
    winner = max(members, key=lambda m: m.conviction)
    merged_stop = _merged_stop(members)
    merged_ladder = _median_ladder(members)
    contributing_ids = sorted({m.agent_id for m in members})
    rationale = dict(winner.rationale) if winner.rationale else {}
    rationale.update({
        "arm3_merged": True,
        "arm3_n_contributors": len(members),
        "arm3_contributing_agents": contributing_ids,
        "arm3_conviction_by_agent": {
            m.agent_id: float(m.conviction) for m in members
        },
        "arm3_stop_by_agent": {m.agent_id: float(m.stop) for m in members},
    })
    rationale["arm3_winner_agent_id"] = winner.agent_id
    return AgentProposal(
        agent_id=f"arm3_merged_{'+'.join(contributing_ids)}",
        tick_id=tick_id,
        source_thought_id=winner.source_thought_id,
        timestamp=winner.timestamp,
        symbol=winner.symbol,
        direction=winner.direction,
        entry=winner.entry,
        stop=merged_stop,
        ladder=merged_ladder,
        conviction=winner.conviction,
        regime_fit=max(m.regime_fit for m in members),
        valid_until=min(m.valid_until for m in members),
        rationale=rationale,
        # Winner's tier so the merged proposal competes in the R6
        # tournament with the same tier-anchor bias the winner would
        # have had standing alone (tier default of 2 would silently
        # penalise a merged tier-1 anchor).
        agent_tier=winner.agent_tier,
    )


def apply_same_direction_merge(
    proposals: Iterable[AgentProposal],
    *,
    tick_id: int,
) -> list[AgentProposal]:
    """Merge same-direction concurrent proposals per symbol.

    Groups by (symbol, direction). Groups of size >= 2 collapse to a
    single merged proposal; singletons pass through untouched. Opposite-
    direction groups are NOT combined (aggregator's opposing rule owns
    that).
    """
    props = [p for p in proposals if p is not None and p.direction != "flat"]
    if not props:
        return []
    grouped: dict[tuple[str, str], list[AgentProposal]] = defaultdict(list)
    for p in props:
        grouped[(p.symbol, p.direction)].append(p)

    out: list[AgentProposal] = []
    for (_symbol, _direction), members in grouped.items():
        if len(members) == 1:
            out.append(members[0])
        else:
            out.append(_merge_group(members, tick_id=tick_id))
    return out
