"""agent.squad -- ported v1 Blue Lock squad core (unvalidated port).

Reimplemented from the research repo
``finance-research-experiments/programs/M001_multi_agent_ensemble/sim/``
@ commit e084c5b (2026-07-14). Research code is NEVER imported; only
artifact JSONL caches are read for the parity harness.

This package powers ``scripts/run_squad_live.py``: the MT5-connected
(or cache-replay) paper runtime that makes the v2 squad react to
today's H4 bars. Shadow-only -- never places broker orders. G7 gate
was FAIL 3/7; this runtime is for paper observation, not live trading.

Post-2026-07-20 additions:

* **Karasu** (A8) -- news-window advisor + Sentinel R7 side-channel
  consumer. NEVER proposes; not in ``roster.proposers``. His warning
  is fed into the Sentinel R7 rule by the engine's admission gate.
* **Sae** (A9) -- event-specialist Tier-1 striker. **Disabled by
  default** via ``SaeConfig.sae_enabled=False``; only appears in
  ``roster.proposers`` when explicitly enabled by the caller.
  ``roster.sae`` is always populated for discovery.

The Phase AD (Karasu) and Phase AE (Sae) research pre-regs live in
the sibling research repo (`finance-research-experiments`) as
working-tree drafts pending user ratification.
"""
from __future__ import annotations

from agent.squad.agents.a08_karasu import A8KarasuV1, KarasuWarning
from agent.squad.agents.a09_sae import A9SaeV1
from agent.squad.news_config import DEFAULT_NEWS_CONFIG, NewsDefenderConfig
from agent.squad.news_refresher import NewsFeedRefresher
from agent.squad.sae_config import DEFAULT_SAE_CONFIG, SaeConfig

PORT_LABEL = "ported v1 (unvalidated port)"
PORT_SOURCE_COMMIT = "e084c5b"
PORT_SOURCE_REPO = (
    "finance-research-experiments/programs/M001_multi_agent_ensemble/sim"
)

__all__ = [
    "A8KarasuV1",
    "A9SaeV1",
    "DEFAULT_NEWS_CONFIG",
    "DEFAULT_SAE_CONFIG",
    "KarasuWarning",
    "NewsDefenderConfig",
    "NewsFeedRefresher",
    "SaeConfig",
    "PORT_LABEL",
    "PORT_SOURCE_COMMIT",
    "PORT_SOURCE_REPO",
]
