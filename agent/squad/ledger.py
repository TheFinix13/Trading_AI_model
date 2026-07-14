"""Thought Ledger -- append-only journal of every agent's reasoning.

Ported v1 (unvalidated port) from the research repo:
``finance-research-experiments/programs/M001_multi_agent_ensemble/
sim/core/ledger.py`` @ commit e084c5b (2026-07-14). Only the
``FullLedger`` (in-memory, optional JSONL persistence) is ported --
the Redacted / Frozen / Synthetic test adapters are research-harness
concerns the live runtime never needs.

Guard semantics (doctrine section 3.8) are preserved verbatim:
* Thoughts whose ``decision_horizon > as_of`` are filtered out.
* Thoughts whose ``tick_id >= current_tick`` are filtered out.
* ``ttl_ticks`` bounds the read window from below.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Protocol

from agent.squad.types import Thought


class ThoughtLedger(Protocol):
    """The read/write surface that every agent depends on."""

    mode: str

    def append(self, t: Thought) -> None: ...

    def read(
        self,
        *,
        as_of: datetime,
        current_tick: int,
        symbol: str | None = None,
    ) -> list[Thought]: ...


def _apply_guards(
    rows: Iterable[Thought],
    *,
    as_of: datetime,
    current_tick: int,
    symbol: str | None,
) -> list[Thought]:
    """Universal read filter: decision_horizon, backwards-only, ttl, symbol."""
    out: list[Thought] = []
    for t in rows:
        if t.tick_id >= current_tick:
            continue
        if t.decision_horizon > as_of:
            continue
        if (current_tick - t.tick_id) > t.ttl_ticks > 0:
            continue
        if symbol is not None and t.symbol != symbol:
            continue
        out.append(t)
    return out


@dataclass
class _MemoryBackend:
    """In-memory mirror with per-symbol index + thought_id dedup.

    Live runtime keeps the ledger purely in memory; restart warm-up
    rebuilds it by replaying recent bars through ``observe()`` (the
    engine's resume path), so no disk backend is needed. A ``max_rows``
    ring bound keeps memory O(1) over multi-month runs -- reads only
    ever need the last ``ttl_ticks`` (<= 12) ticks plus Kunigami's
    50-tick window, so 20_000 retained thoughts is orders of magnitude
    more than any consumer can see through the guards.
    """

    max_rows: int = 20_000
    _in_memory: list[Thought] = field(default_factory=list)
    _seen_ids: set[str] = field(default_factory=set)
    _by_symbol: dict[str, list[Thought]] = field(default_factory=dict)

    def append(self, t: Thought) -> None:
        if t.thought_id in self._seen_ids:
            return
        self._seen_ids.add(t.thought_id)
        self._in_memory.append(t)
        self._by_symbol.setdefault(t.symbol, []).append(t)
        if len(self._in_memory) > self.max_rows:
            dropped = self._in_memory.pop(0)
            self._seen_ids.discard(dropped.thought_id)
            bucket = self._by_symbol.get(dropped.symbol)
            if bucket and bucket[0] is dropped:
                bucket.pop(0)

    def iter_all(self) -> Iterator[Thought]:
        return iter(self._in_memory)

    def iter_by_symbol(self, symbol: str) -> Iterator[Thought]:
        bucket = self._by_symbol.get(symbol)
        if bucket is None:
            return iter(())
        return iter(bucket)


class FullLedger:
    """Tier-2 read access -- full ledger subject to section 3.8 guards.

    ``root`` is accepted for signature parity with the research
    implementation but persistence is in-memory only in the live port
    (see ``_MemoryBackend`` docstring for why that is sufficient).
    """

    mode = "full"

    def __init__(self, root: str | os.PathLike | None = None) -> None:
        self.root = Path(root) if root else None
        self._backend = _MemoryBackend()

    def append(self, t: Thought) -> None:
        self._backend.append(t)

    def read(
        self,
        *,
        as_of: datetime,
        current_tick: int,
        symbol: str | None = None,
    ) -> list[Thought]:
        if symbol is not None:
            return _apply_guards(
                self._backend.iter_by_symbol(symbol),
                as_of=as_of,
                current_tick=current_tick,
                symbol=symbol,
            )
        return _apply_guards(
            self._backend.iter_all(),
            as_of=as_of,
            current_tick=current_tick,
            symbol=symbol,
        )
