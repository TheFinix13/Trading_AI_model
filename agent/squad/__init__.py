"""agent.squad -- ported v1 Blue Lock squad core (unvalidated port).

Reimplemented from the research repo
``finance-research-experiments/programs/M001_multi_agent_ensemble/sim/``
@ commit e084c5b (2026-07-14). Research code is NEVER imported; only
artifact JSONL caches are read for the parity harness.

This package powers ``scripts/run_squad_live.py``: the MT5-connected
(or cache-replay) paper runtime that makes the v2 squad react to
today's H4 bars. Shadow-only -- never places broker orders. G7 gate
was FAIL 3/7; this runtime is for paper observation, not live trading.
"""
from __future__ import annotations

PORT_LABEL = "ported v1 (unvalidated port)"
PORT_SOURCE_COMMIT = "e084c5b"
PORT_SOURCE_REPO = (
    "finance-research-experiments/programs/M001_multi_agent_ensemble/sim"
)

__all__ = ["PORT_LABEL", "PORT_SOURCE_COMMIT", "PORT_SOURCE_REPO"]
