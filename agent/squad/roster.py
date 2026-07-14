"""Squad roster factory -- 7 proposing agents + Kunigami R5 side channel.

Ported v1 (unvalidated port) from the research G7 walk-forward harness
(``run_g7_v1_checkpoint_gate.py::run_g7_walk_forward``) @ commit e084c5b
(2026-07-14). Kunigami is RETIRED from proposing (G7 §11.12) but retained
as a Sentinel R5 anti-tilt side channel via ``record_closed_trade`` /
``warning_active_at``.

Default Barou config: Phase Y v1.3 weapon (``htf_align_mode="with"``)
when the agent constructor exposes that knob; otherwise the sealed v1
baseline. Callers that want byte-faithful g7retry1 comparison should
pass ``barou_v13=False``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.squad.agents.a01_isagi import A1IsagiV1
from agent.squad.agents.a02_bachira import A2BachiraV1
from agent.squad.agents.a03_rin import A3RinV1
from agent.squad.agents.a04_chigiri import A4ChigiriV1
from agent.squad.agents.a05_reo import A5ReoV1
from agent.squad.agents.a06_nagi import A6NagiV1
from agent.squad.agents.a07_barou import A7BarouV1
from agent.squad.agents.a10_kunigami import A10KunigamiV1

DEFAULT_SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDCAD")

PROPOSING_AGENT_IDS: tuple[str, ...] = (
    "isagi_yoichi",
    "bachira_meguru",
    "itoshi_rin",
    "chigiri_hyoma",
    "reo_mikage",
    "nagi_seishiro",
    "barou_shoei",
)


@dataclass
class SquadRoster:
    """Instantiated squad + the retired Kunigami side channel."""

    proposers: list[Any]
    kunigami: A10KunigamiV1
    isagi: A1IsagiV1
    barou: A7BarouV1

    @property
    def all_agents(self) -> list[Any]:
        """Proposing roster only (Kunigami is NOT in the publisher list)."""
        return list(self.proposers)

    def by_id(self) -> dict[str, Any]:
        out = {a.agent_id: a for a in self.proposers}
        out[self.kunigami.agent_id] = self.kunigami
        return out


def build_roster(
    *,
    symbols: tuple[str, ...] | list[str] = DEFAULT_SYMBOLS,
    barou_v12: bool = False,
    barou_v13: bool = True,
) -> SquadRoster:
    """Construct the 7-proposer + Kunigami roster.

    ``barou_v13=True`` (default for live paper observation) enables the
    Phase Y Barou v1.3 weapon config when available. Set ``barou_v13=False``
    (and ``barou_v12=False``) for g7retry1-parity replays.
    """
    isagi = A1IsagiV1()
    bachira = A2BachiraV1()
    rin = A3RinV1()
    chigiri = A4ChigiriV1()
    reo = A5ReoV1()
    nagi = A6NagiV1()

    # Phase Y v1.3 weapon is Barou's constructor default (weapon_v13=True).
    # Pass weapon_v13=False for g7retry1-parity replays that predate Phase Y.
    barou = A7BarouV1(
        continuation_entry_enabled=barou_v12,
        weapon_v13=barou_v13,
    )

    kunigami = A10KunigamiV1()
    proposers = [isagi, bachira, rin, chigiri, reo, nagi, barou]

    # Narrow symbol whitelists to the caller's universe when agents
    # already subscribe to a wider (or equal) set. Agents whose home
    # symbol is outside the universe (e.g. Barou is USDCAD-only) keep
    # their natural symbols -- filtered at drive time by eligibility.
    for agent in proposers + [kunigami]:
        if hasattr(agent, "symbols") and agent.symbols:
            agent.symbols = [s for s in agent.symbols if s in symbols] or list(agent.symbols)

    return SquadRoster(
        proposers=proposers,
        kunigami=kunigami,
        isagi=isagi,
        barou=barou,
    )


def prepare_roster(roster: SquadRoster, bars_by_symbol: dict[str, list]) -> None:
    """Call ``prepare(symbol, bars)`` on every agent that exposes it."""
    for sym, bars in bars_by_symbol.items():
        if not bars:
            continue
        for agent in roster.proposers:
            if hasattr(agent, "prepare") and sym in getattr(agent, "symbols", ()):
                agent.prepare(sym, bars)
