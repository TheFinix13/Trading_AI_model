"""F21 -- Reasoning Workspace (per-tick shared blackboard).

Ported v1 (unvalidated port) from the research repo:
``finance-research-experiments/programs/M001_multi_agent_ensemble/
sim/core/reasoning_workspace.py`` @ commit e084c5b (2026-07-14).

Agents publish Thoughts during ``observe()`` (Phase 1) and read peers
during ``intend()`` (Phase 2) via an immutable snapshot taken at the
tick barrier. Doctrine section 3.8 guards are enforced at snapshot
time; F22b ``snapshot_at_barrier`` additionally exposes same-tick peer
publishes (committed at the barrier, hence not look-ahead).

Live-runtime extension (port-only, not in the research sim):
``prune_before(tick_id)`` bounds memory over multi-month runs. Every
workspace consumer in the v1 roster reads at most the last few ticks,
so pruning ticks older than ~500 cannot change any read result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from agent.squad.types import Symbol, Thought

Tier = Literal[1, 2, 3]


@dataclass
class ReasoningWorkspace:
    """Per-tick shared blackboard (stateful; snapshots are immutable)."""

    thoughts: list[Thought] = field(default_factory=list)
    _thought_ids: set[str] = field(default_factory=set, init=False, repr=False)

    def publish(self, thought: Thought) -> bool:
        """Append ``thought``. Idempotent on ``thought_id``.

        Returns True if newly appended, False on duplicate id.
        """
        if thought.thought_id in self._thought_ids:
            return False
        self._thought_ids.add(thought.thought_id)
        self.thoughts.append(thought)
        return True

    def prune_before(self, tick_id: int) -> int:
        """Drop thoughts with ``tick_id`` strictly below the given tick.

        Live-runtime memory bound; returns the number of rows dropped.
        """
        keep = [t for t in self.thoughts if t.tick_id >= tick_id]
        dropped = len(self.thoughts) - len(keep)
        if dropped:
            self.thoughts = keep
            self._thought_ids = {t.thought_id for t in keep}
        return dropped

    def snapshot(
        self,
        *,
        as_of: datetime,
        current_tick: int,
    ) -> "WorkspaceSnapshot":
        """Strict backwards-only projection (no same-tick reads)."""
        visible = tuple(
            t for t in self.thoughts
            if t.timestamp <= as_of
            and t.tick_id < current_tick
            and t.decision_horizon <= as_of
        )
        return WorkspaceSnapshot(
            thoughts=visible,
            as_of=as_of,
            current_tick=current_tick,
        )

    def snapshot_at_barrier(
        self,
        *,
        as_of: datetime,
        current_tick: int,
    ) -> "WorkspaceSnapshot":
        """F22b -- tick-barrier snapshot; includes this tick's publishes."""
        visible = tuple(
            t for t in self.thoughts
            if t.timestamp <= as_of
            and t.tick_id <= current_tick
            and t.decision_horizon <= as_of
        )
        return WorkspaceSnapshot(
            thoughts=visible,
            as_of=as_of,
            current_tick=current_tick,
        )


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Immutable per-tick view returned by ``ReasoningWorkspace``."""

    thoughts: tuple[Thought, ...]
    as_of: datetime
    current_tick: int

    def read_for(
        self,
        *,
        agent_id: str,
        tier: Tier = 2,
        symbol: Symbol | None = None,
        tag: str | None = None,
        signal_family: str | None = None,
    ) -> tuple[Thought, ...]:
        """Thoughts visible to ``agent_id`` under ``tier``, oldest first."""
        if tier == 3:
            filtered = tuple(t for t in self.thoughts if t.agent_id == agent_id)
        else:
            filtered = self.thoughts

        if symbol is not None:
            filtered = tuple(t for t in filtered if t.symbol == symbol)
        if tag is not None:
            filtered = tuple(t for t in filtered if tag in t.tags)
        if signal_family is not None:
            filtered = tuple(
                t for t in filtered
                if t.read is not None and t.read.signal_family == signal_family
            )

        return tuple(sorted(filtered, key=lambda t: (t.tick_id, t.timestamp)))

    def peer_thoughts(
        self,
        *,
        agent_id: str,
        symbol: Symbol | None = None,
        tag: str | None = None,
        signal_family: str | None = None,
    ) -> tuple[Thought, ...]:
        """Tier-2 view minus own Thoughts (peer confluence reads)."""
        peers = tuple(t for t in self.thoughts if t.agent_id != agent_id)
        if symbol is not None:
            peers = tuple(t for t in peers if t.symbol == symbol)
        if tag is not None:
            peers = tuple(t for t in peers if tag in t.tags)
        if signal_family is not None:
            peers = tuple(
                t for t in peers
                if t.read is not None and t.read.signal_family == signal_family
            )
        return tuple(sorted(peers, key=lambda t: (t.tick_id, t.timestamp)))

    def latest_by_agent(
        self,
        *,
        symbol: Symbol | None = None,
    ) -> dict[str, Thought]:
        """Most recent Thought per agent in the snapshot."""
        latest: dict[str, Thought] = {}
        for t in self.thoughts:
            if symbol is not None and t.symbol != symbol:
                continue
            existing = latest.get(t.agent_id)
            if existing is None or t.tick_id > existing.tick_id:
                latest[t.agent_id] = t
            elif t.tick_id == existing.tick_id and t.timestamp > existing.timestamp:
                latest[t.agent_id] = t
        return latest


__all__ = ["ReasoningWorkspace", "WorkspaceSnapshot", "Tier"]
