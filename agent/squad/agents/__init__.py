"""Squad agent implementations (ported v1, unvalidated port)."""
from __future__ import annotations

from agent.squad.agents.a01_isagi import A1IsagiV1
from agent.squad.agents.a02_bachira import A2BachiraV1
from agent.squad.agents.a03_rin import A3RinV1
from agent.squad.agents.a04_chigiri import A4ChigiriV1
from agent.squad.agents.a05_reo import A5ReoV1
from agent.squad.agents.a06_nagi import A6NagiV1
from agent.squad.agents.a07_barou import A7BarouV1
from agent.squad.agents.a10_kunigami import A10KunigamiV1, ClosedTradeRecord

__all__ = [
    "A1IsagiV1",
    "A2BachiraV1",
    "A3RinV1",
    "A4ChigiriV1",
    "A5ReoV1",
    "A6NagiV1",
    "A7BarouV1",
    "A10KunigamiV1",
    "ClosedTradeRecord",
]
