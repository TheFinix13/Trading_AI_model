"""Phi5 aggregator arm helpers (arm3 merge + arm4 multi-position).

Ported v1 (unvalidated port) from
``sim/core/aggregator_arms/`` @ commit e084c5b.
"""
from __future__ import annotations

from agent.squad.aggregator_arms.multi_position import (
    ARM4_K_POSITIONS,
    Arm4Decision,
    OpenPosition,
    admit_proposals,
)
from agent.squad.aggregator_arms.same_direction_merge import (
    apply_same_direction_merge,
)

__all__ = [
    "ARM4_K_POSITIONS",
    "Arm4Decision",
    "OpenPosition",
    "admit_proposals",
    "apply_same_direction_merge",
]
