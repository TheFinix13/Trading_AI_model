"""Build live-trading alphas from the validated zone routing table.

This is the only sanctioned bridge between ``agent.alphas.zone_routing``
(the evidence-backed deployment table) and the live signal loop. A live
process configured for a symbol gets exactly the alphas the router
deploys for that symbol — on the routed timeframe, at the routed
``risk_scale`` — or it refuses to start. There is deliberately no
fallback alpha: trading anything the validation pipeline didn't sign off
is worse than not trading.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha
from agent.alphas.zone_routing import alpha_for, survivors
from agent.config import Config


class UndeployedSymbolError(RuntimeError):
    """The configured symbol has no deployed cells in the routing table."""


@dataclass(frozen=True)
class LiveRoute:
    """One deployed routing cell, materialised for the live loop."""

    symbol: str
    timeframe: str
    session: str
    mode: str
    risk_scale: float
    alpha: SupplyDemandAlpha


def build_live_routes(symbol: str, cfg: Config | None = None) -> list[LiveRoute]:
    """Return the deployed :class:`LiveRoute` list for ``symbol``.

    Iterates the router's ``survivors()`` (never the raw table, so skip
    cells can't leak through) and constructs each cell's validated alpha
    via ``alpha_for``. Raises :class:`UndeployedSymbolError` when the
    symbol has no deployed cells — callers must treat that as a hard
    startup failure, not a cue to substitute another alpha.
    """
    routes: list[LiveRoute] = []
    for sym, tf, session, entry in survivors():
        if sym != symbol:
            continue
        alpha = alpha_for(sym, tf, session, cfg)
        if alpha is None:  # unreachable: survivors() excludes skip cells
            continue
        # Distinct per-cell name so SignalLoop.risk_scales can key on it.
        alpha.name = f"zone_{tf.lower()}_{session}"
        routes.append(LiveRoute(
            symbol=sym, timeframe=tf, session=session,
            mode=entry.mode, risk_scale=entry.risk_scale, alpha=alpha,
        ))
    if not routes:
        deployed = sorted({s for s, _, _, _ in survivors()})
        raise UndeployedSymbolError(
            f"Symbol {symbol!r} has no deployed cells in the zone routing "
            f"table (deployed symbols: {', '.join(deployed)}). Refusing to "
            f"start: live trading only runs validated router cells."
        )
    return routes
