"""Squad roster factory -- 7 proposing agents + Kunigami R5 side channel
+ Karasu R7 news side channel + optional Sae event specialist.

Ported v1 (unvalidated port) from the research G7 walk-forward harness
(``run_g7_v1_checkpoint_gate.py::run_g7_walk_forward``) @ commit e084c5b
(2026-07-14). Kunigami is RETIRED from proposing (G7 §11.12) but retained
as a Sentinel R5 anti-tilt side channel via ``record_closed_trade`` /
``warning_active_at``.

Karasu (2026-07-20, Phase AD pending research pre-reg) joins the roster
as a side-channel-only auxiliary; the engine feeds his
``warning_active_at(as_of, symbol)`` into the Sentinel R7 news-impact
ladder. Like Kunigami, Karasu is NEVER in ``roster.proposers``.

Sae (Phase AE pending research pre-reg) is a Tier-1 event-specialist
striker that only fires inside a scheduled event window. He is
DISABLED BY DEFAULT (``sae_enabled=False`` on
:class:`agent.squad.sae_config.SaeConfig`) and only appears in
``roster.proposers`` when explicitly enabled by the caller. The
``roster.sae`` attribute is populated regardless, so the engine can
still ping it for tests / diagnostics without swapping the enabled
flag.

Default Barou config: Phase Y v1.3 weapon (``htf_align_mode="with"``)
when the agent constructor exposes that knob; otherwise the sealed v1
baseline. Callers that want byte-faithful g7retry1 comparison should
pass ``barou_v13=False``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agent.squad.agents.a01_isagi import A1IsagiV1
from agent.squad.agents.a02_bachira import A2BachiraV1
from agent.squad.agents.a03_rin import A3RinV1
from agent.squad.agents.a04_chigiri import A4ChigiriV1
from agent.squad.agents.a05_reo import A5ReoV1
from agent.squad.agents.a06_nagi import A6NagiV1
from agent.squad.agents.a07_barou import A7BarouV1
from agent.squad.agents.a08_karasu import A8KarasuV1
from agent.squad.agents.a09_sae import A9SaeV1
from agent.squad.agents.a10_kunigami import A10KunigamiV1
from agent.squad.news_config import DEFAULT_NEWS_CONFIG, NewsDefenderConfig
from agent.squad.sae_config import DEFAULT_SAE_CONFIG, SaeConfig

log = logging.getLogger(__name__)

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
    """Instantiated squad + the retired Kunigami side channel +
    Karasu news-window defender side channel + optional Sae
    event-specialist striker.

    ``karasu`` is always populated (a news defender exists in every
    build). ``sae`` is always populated too, but only appears in
    ``proposers`` when :class:`SaeConfig` has ``sae_enabled=True`` --
    ``sae_enabled`` on this dataclass mirrors that flag for callers.
    """

    proposers: list[Any]
    kunigami: A10KunigamiV1
    isagi: A1IsagiV1
    barou: A7BarouV1
    karasu: A8KarasuV1
    sae: A9SaeV1
    sae_enabled: bool = False

    @property
    def all_agents(self) -> list[Any]:
        """Proposing roster only (Kunigami + Karasu are NOT here;
        Sae is only here when enabled)."""
        return list(self.proposers)

    def by_id(self) -> dict[str, Any]:
        out = {a.agent_id: a for a in self.proposers}
        out[self.kunigami.agent_id] = self.kunigami
        out[self.karasu.agent_id] = self.karasu
        if not self.sae_enabled:
            # Sae still discoverable by id for diagnostics even when
            # not in proposers (matches the Kunigami side-channel pattern).
            out[self.sae.agent_id] = self.sae
        return out


def build_roster(
    *,
    symbols: tuple[str, ...] | list[str] = DEFAULT_SYMBOLS,
    barou_v12: bool = False,
    barou_v13: bool = True,
    news_config: NewsDefenderConfig | None = None,
    sae_config: SaeConfig | None = None,
) -> SquadRoster:
    """Construct the 7-proposer + Kunigami + Karasu roster (Sae opt-in).

    ``barou_v13=True`` (default for live paper observation) enables the
    Phase Y Barou v1.3 weapon config when available. Set ``barou_v13=False``
    (and ``barou_v12=False``) for g7retry1-parity replays.

    ``news_config`` overrides the default news-defender knobs (see
    :mod:`agent.squad.news_config`). Karasu is always instantiated;
    if no calendar is hydrated (missing cache), Karasu is fail-open
    and R7 passes through every proposal.

    ``sae_config`` overrides the default Sae knobs (see
    :mod:`agent.squad.sae_config`). Sae is instantiated regardless
    (so ``roster.sae`` is always a real object), but only appears
    in ``roster.proposers`` when ``sae_config.sae_enabled=True``.
    """
    news_cfg = news_config or DEFAULT_NEWS_CONFIG
    sae_cfg = sae_config or DEFAULT_SAE_CONFIG

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
    karasu = A8KarasuV1(config=news_cfg)
    sae = A9SaeV1(config=sae_cfg, news_config=news_cfg)

    proposers = [isagi, bachira, rin, chigiri, reo, nagi, barou]
    if sae_cfg.sae_enabled:
        proposers.append(sae)
        log.info("Sae ENABLED (event_specialist)")
    else:
        log.info("Sae DISABLED (awaiting Phase AE pre-reg)")

    # Narrow symbol whitelists to the caller's universe when agents
    # already subscribe to a wider (or equal) set. Agents whose home
    # symbol is outside the universe (e.g. Barou is USDCAD-only) keep
    # their natural symbols -- filtered at drive time by eligibility.
    # Karasu keeps his full multi-currency scope (news impact is a
    # currency-scoped signal, not a per-pair signal); the R7 gate
    # already filters by ``proposal.symbol`` at admission.
    for agent in proposers + [kunigami]:
        if hasattr(agent, "symbols") and agent.symbols:
            agent.symbols = [s for s in agent.symbols if s in symbols] or list(agent.symbols)

    return SquadRoster(
        proposers=proposers,
        kunigami=kunigami,
        isagi=isagi,
        barou=barou,
        karasu=karasu,
        sae=sae,
        sae_enabled=bool(sae_cfg.sae_enabled),
    )


def prepare_roster(roster: SquadRoster, bars_by_symbol: dict[str, list]) -> None:
    """Call ``prepare(symbol, bars)`` on every agent that exposes it."""
    for sym, bars in bars_by_symbol.items():
        if not bars:
            continue
        for agent in roster.proposers:
            if hasattr(agent, "prepare") and sym in getattr(agent, "symbols", ()):
                agent.prepare(sym, bars)
