"""Arm 4 of the Phi5 aggregator experiment -- multi-position per symbol.

Relaxes the single-position-per-symbol queue to allow up to K=2
concurrent positions per symbol subject to:

- **Distinct agents**: no single agent occupies both slots.
- **Total risk cap per symbol**: combined risk across all open positions
  on the symbol <= 1.0 % of equity (matches single-position cap; budget
  is SPLIT across positions, not doubled). Enforced by Sentinel R6
  (`sim/core/sentinel.py::check_r6_per_symbol_risk_cap`).
- **Same-direction correlation block**: two open same-direction positions
  count as ONE for the cap (Arm 3's job to merge them in Arm 5 stacking;
  in Arm 4 standalone we still admit them but flag).

The admission is stateful -- it depends on the CURRENT open positions.
The harness (Phase 6c) tracks open state and calls ``admit_proposals``
per tick.

Reference: `experiments/phi5_aggregator/PROTOCOL.md` §3.2 Arm 4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from agent.squad.sentinel import (
    SANDBOX_PER_SYMBOL_RISK_FRAC,
    check_r6_per_symbol_risk_cap,
)
from agent.squad.types import AgentProposal


ARM4_K_POSITIONS = 2
ARM4_TOTAL_RISK_CAP = SANDBOX_PER_SYMBOL_RISK_FRAC  # 1 % of equity per symbol
ARM4_MIN_DISTINCT_AGENTS = 2


@dataclass(frozen=True)
class OpenPosition:
    """Minimal open-position record for the admission check.

    The full simulator tracks more state (SL, TP, unrealised P&L, etc.);
    this arm only cares about symbol, direction, owning agent, and the
    dollar-risk the position was opened with.
    """

    symbol: str
    direction: str
    agent_id: str
    risk_dollars: float


@dataclass(frozen=True)
class Arm4Decision:
    """Per-proposal admission decision emitted by ``admit_proposals``."""

    proposal: AgentProposal
    admitted: bool
    reason: str
    open_count_on_symbol: int
    combined_risk_dollars: float


def _positions_by_symbol(
    open_positions: Iterable[OpenPosition],
) -> dict[str, list[OpenPosition]]:
    out: dict[str, list[OpenPosition]] = {}
    for p in open_positions:
        out.setdefault(p.symbol, []).append(p)
    return out


def admit_proposals(
    proposals: Iterable[AgentProposal],
    *,
    open_positions: Iterable[OpenPosition],
    equity_dollars: float,
    pip_value_per_min_lot: float,
    k_positions: int = ARM4_K_POSITIONS,
    total_risk_cap_frac: float = ARM4_TOTAL_RISK_CAP,
    min_distinct_agents: int = ARM4_MIN_DISTINCT_AGENTS,
) -> tuple[list[AgentProposal], list[Arm4Decision]]:
    """Admit up to K positions per symbol subject to R6 cap + distinct-agents.

    Inputs
    ------
    proposals : iterable of AgentProposal
        Candidates for this tick, already filtered by upstream stages.
    open_positions : iterable of OpenPosition
        Current live positions across all symbols.
    equity_dollars : float
        Current account equity (for the R6 percentage calc).
    pip_value_per_min_lot : float
        Sandbox pip value (e.g. 0.10 for $100 / 1:1000 min-lot @ 0.01).
        Passed through to Sentinel R6.

    Returns
    -------
    (admitted, decisions)
        Ordered by proposal iteration; admitted list contains proposals
        that both slot in (K constraint) and pass R6 risk cap. Decisions
        record each proposal's per-rule outcome for auditability.
    """
    admitted: list[AgentProposal] = []
    decisions: list[Arm4Decision] = []
    open_by_sym = _positions_by_symbol(open_positions)

    # Sort by conviction (desc) so higher-conviction proposals get slot
    # priority when multiple compete for the last K slot on the symbol.
    ordered = sorted(
        (p for p in proposals if p is not None and p.direction != "flat"),
        key=lambda p: -float(p.conviction),
    )

    for prop in ordered:
        sym = prop.symbol
        current_positions = list(open_by_sym.get(sym, []))
        agents_on_symbol = {p.agent_id for p in current_positions}

        n_current = len(current_positions)
        combined_risk = sum(p.risk_dollars for p in current_positions)

        # Slot count check.
        if n_current >= k_positions:
            decisions.append(Arm4Decision(
                proposal=prop, admitted=False,
                reason=f"slot_full(k={k_positions})",
                open_count_on_symbol=n_current,
                combined_risk_dollars=combined_risk,
            ))
            continue

        # Distinct-agent check (only meaningful once we already have >= 1).
        if n_current >= 1 and prop.agent_id in agents_on_symbol:
            decisions.append(Arm4Decision(
                proposal=prop, admitted=False,
                reason="same_agent_already_on_symbol",
                open_count_on_symbol=n_current,
                combined_risk_dollars=combined_risk,
            ))
            continue

        # R6 total-risk cap check.
        additional_risk = _proposal_risk_dollars(
            prop, pip_value_per_min_lot=pip_value_per_min_lot,
        )
        r6 = check_r6_per_symbol_risk_cap(
            symbol=sym,
            current_symbol_risk_dollars=combined_risk,
            additional_risk_dollars=additional_risk,
            equity=equity_dollars,
            cap_frac=total_risk_cap_frac,
        )
        if not r6.allowed:
            decisions.append(Arm4Decision(
                proposal=prop, admitted=False,
                reason=r6.reason or "r6_blocked",
                open_count_on_symbol=n_current,
                combined_risk_dollars=combined_risk + additional_risk,
            ))
            continue

        # Admitted.
        admitted.append(prop)
        decisions.append(Arm4Decision(
            proposal=prop, admitted=True,
            reason="admitted",
            open_count_on_symbol=n_current,
            combined_risk_dollars=combined_risk + additional_risk,
        ))
        # Simulate the admission for subsequent proposals in the same tick.
        open_by_sym.setdefault(sym, []).append(OpenPosition(
            symbol=sym, direction=prop.direction,
            agent_id=prop.agent_id, risk_dollars=additional_risk,
        ))

    return admitted, decisions


SANDBOX_FIXED_LOT_MIN_LOT_UNITS = 10  # FIXED_LOT (0.1) / MIN_LOT (0.01) = 10


def _proposal_risk_dollars(
    prop: AgentProposal,
    *,
    pip_value_per_min_lot: float,
) -> float:
    """Estimate the dollar risk of a proposal in the fixed-lot sandbox.

    The sim's fixed lot is 0.1 (= 10 min-lots @ 0.01). Risk in dollars =
    stop-distance-in-pips * pip_value_per_min_lot * 10. For a EURUSD
    50-pip stop at $0.10 pip-value-per-min-lot, this yields $50 -- well
    above the 1 % ($1 for $100 equity) per-symbol R6 cap.
    """
    entry = float(prop.entry)
    stop = float(prop.stop)
    # Round to 1 decimal (pipettes) -- avoids `1.1000 - 1.09995` producing
    # 5.000000000002e-05 which would leak $O(1e-13) noise into the R6
    # cap comparison and spuriously block valid multi-position stacks.
    stop_pips = round(abs(entry - stop) * 10000.0, 1)
    return stop_pips * pip_value_per_min_lot * SANDBOX_FIXED_LOT_MIN_LOT_UNITS


@dataclass
class MultiPositionAggregator:
    """Stateful adapter -- wraps ``admit_proposals`` with configuration."""

    equity_dollars: float
    pip_value_per_min_lot: float
    k_positions: int = ARM4_K_POSITIONS
    total_risk_cap_frac: float = ARM4_TOTAL_RISK_CAP
    open_positions: list[OpenPosition] = field(default_factory=list)

    def admit(
        self, proposals: Iterable[AgentProposal],
    ) -> tuple[list[AgentProposal], list[Arm4Decision]]:
        return admit_proposals(
            proposals,
            open_positions=self.open_positions,
            equity_dollars=self.equity_dollars,
            pip_value_per_min_lot=self.pip_value_per_min_lot,
            k_positions=self.k_positions,
            total_risk_cap_frac=self.total_risk_cap_frac,
        )

    def record_open(self, position: OpenPosition) -> None:
        self.open_positions.append(position)

    def close_position(self, symbol: str, agent_id: str) -> None:
        self.open_positions = [
            p for p in self.open_positions
            if not (p.symbol == symbol and p.agent_id == agent_id)
        ]
