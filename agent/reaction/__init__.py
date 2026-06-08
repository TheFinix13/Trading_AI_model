"""Reaction engine — present-tense commitment detection.

Where the anticipation stack waits for a full retest choreography (touch ->
consume -> reaction wick -> displacement) and so almost never fires, the
reaction engine measures what price is doing *right now*. It scores four
MEASURED facts about the just-closed bar(s):

    1. Displacement      — body vs ATR with a strong directional close
    2. Range expansion   — current range vs the rolling average (vol ignition)
    3. Momentum          — ROC normalised by ATR + consecutive closes
    4. Order-flow proxy  — close location, wick asymmetry, tick volume

and fires a :class:`ReactionSignal` when the composite conviction clears a
threshold AND price is acting on a pre-marked level of interest.
"""
from __future__ import annotations

from agent.reaction.components import (
    ReactionComponents,
    compute_components,
    displacement_score,
    imbalance_score,
    momentum_score,
    range_expansion_score,
)
from agent.reaction.engine import (
    LevelOfInterest,
    ReactionAssessment,
    ReactionEngine,
    ReactionSignal,
)

__all__ = [
    "ReactionComponents",
    "compute_components",
    "displacement_score",
    "range_expansion_score",
    "momentum_score",
    "imbalance_score",
    "ReactionEngine",
    "ReactionSignal",
    "ReactionAssessment",
    "LevelOfInterest",
]
