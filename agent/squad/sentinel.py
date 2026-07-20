"""Sentinel — hard-rule enforcement (doctrine `06` sections 4.2 and 4.3).

Two surfaces in this module:

* **R1-R5 hard rules** (section 4.3) — block-or-allow decisions taken on
  every OrderIntent / per-agent-tick. Pure functions; no I/O.

* **External shock triggers** (section 4.2) — correlation jumps, spread
  spikes, calendar events, DXY shocks. Phi2.5 ships the data
  structures and a thin evaluator; the wiring to the live feed lands
  in Phi3+ together with the calendar adapter.

Critical invariant: any single hard-rule violation = trade blocked.
The Sentinel writes an audit log entry per block; the kernel never
silently passes a violating order downstream.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Literal, Optional

from agent.squad.types import AgentProposal, OrderIntent


# ---------------------------------------------------------------------------
# Defaults — sandbox-relaxed per architecture section 6
# ---------------------------------------------------------------------------

# Per-trade and per-basket caps inherit the sandbox-relaxed values
# (`03-architecture-v0-sketch.md` section 6).
SANDBOX_PER_TRADE_RISK_FRAC = 0.05    # R1 ceiling
SANDBOX_PER_BASKET_RISK_FRAC = 0.07   # informational only at sentinel layer
MIN_LOT = 0.01                        # R2 min-lot
LOT_INCREMENT = 0.01                  # R2 sizing increment
PASS_BIAS_PROPOSALS_PER_DAY = 3       # R3 over-firing threshold
CONCENTRATION_CAP = 0.40              # R4 hard backstop above HRP cap
LOSS_STREAK_TRIGGER = 3               # R5 trigger length
LOSS_STREAK_DAMPENER = 0.5            # R5 risk-scale
LOSS_STREAK_DURATION_HOURS = 24       # R5 dampener duration
SANDBOX_PER_SYMBOL_RISK_FRAC = 0.01   # R6 per-symbol total-risk cap
                                       # (Phi5 Arm 4 multi-position ceiling)


@dataclass(frozen=True)
class SentinelDecision:
    """Outcome of a single Sentinel evaluation."""

    allowed: bool
    rule: Literal["R1", "R2", "R3", "R4", "R5", "R6", "R7", "EXT", "OK"]
    reason: str
    payload: dict
    risk_scale: float = 1.0


# ---------------------------------------------------------------------------
# R1 — Min-lot risk floor
# ---------------------------------------------------------------------------

def check_r1_min_lot_risk_floor(
    *,
    sl_distance_pips: float,
    pip_value_per_min_lot: float,
    equity: float,
    cap_frac: float = SANDBOX_PER_TRADE_RISK_FRAC,
) -> SentinelDecision:
    """R1: refuse if min-lot-implied risk > cap_frac of equity.

    On a $100 / 1:1000 account with EURUSD pip value ~ $0.10 at 0.01
    lot, the implied max stop distance is ~50 pips at 5% cap. Wider
    stops are refusals, not size-downs.
    """
    implied_risk_dollars = float(sl_distance_pips) * float(pip_value_per_min_lot)
    cap_dollars = float(cap_frac) * float(equity)
    if implied_risk_dollars > cap_dollars:
        return SentinelDecision(
            allowed=False,
            rule="R1",
            reason=(
                f"min-lot risk ${implied_risk_dollars:.2f} > cap "
                f"${cap_dollars:.2f} (={cap_frac*100:.1f}% of equity)"
            ),
            payload={
                "sl_distance_pips": float(sl_distance_pips),
                "pip_value_per_min_lot": float(pip_value_per_min_lot),
                "equity": float(equity),
                "cap_frac": float(cap_frac),
            },
        )
    return SentinelDecision(
        allowed=True, rule="OK", reason="R1 ok", payload={}
    )


# ---------------------------------------------------------------------------
# R2 — Discrete position sizing (round down)
# ---------------------------------------------------------------------------

def check_r2_discrete_size(
    desired_lot: float,
    *,
    min_lot: float = MIN_LOT,
    increment: float = LOT_INCREMENT,
) -> tuple[float, SentinelDecision]:
    """R2: round desired lot down to nearest discrete increment.

    Returns ``(rounded_lot, decision)``. Decision is always "allowed"
    once the round-down is applied. The decision payload records the
    rounding event for the audit log.
    """
    if desired_lot < min_lot:
        return 0.0, SentinelDecision(
            allowed=False,
            rule="R2",
            reason=f"desired lot {desired_lot:.4f} < min_lot {min_lot:.4f}",
            payload={
                "desired_lot": float(desired_lot),
                "min_lot": float(min_lot),
                "rounded_lot": 0.0,
            },
        )
    # Round DOWN (toward smaller risk).
    units = int(desired_lot / increment)
    rounded = round(units * increment, 8)
    return rounded, SentinelDecision(
        allowed=True,
        rule="R2",
        reason=f"rounded {desired_lot:.4f} down to {rounded:.4f}",
        payload={
            "desired_lot": float(desired_lot),
            "rounded_lot": float(rounded),
        },
    )


# ---------------------------------------------------------------------------
# R3 — Pass bias (over-firing detector)
# ---------------------------------------------------------------------------

def check_r3_pass_bias(
    agent_id: str,
    proposals_today: int,
    *,
    threshold: int = PASS_BIAS_PROPOSALS_PER_DAY,
) -> SentinelDecision:
    """R3: flag agents firing more than `threshold` proposals per day.

    Returns ``allowed=True`` always (R3 is an audit-only flag — the
    kernel doesn't block the proposal, but the audit log records the
    over-firing for roster review).
    """
    if proposals_today > threshold:
        return SentinelDecision(
            allowed=True,
            rule="R3",
            reason=(
                f"agent {agent_id} emitted {proposals_today} proposals today "
                f"(> {threshold}/day threshold)"
            ),
            payload={
                "agent_id": agent_id,
                "proposals_today": int(proposals_today),
                "threshold": int(threshold),
            },
        )
    return SentinelDecision(
        allowed=True, rule="OK", reason="R3 ok", payload={}
    )


# ---------------------------------------------------------------------------
# R4 — Concentration cap (hard backstop above HRP)
# ---------------------------------------------------------------------------

def check_r4_concentration(
    agent_id: str,
    intended_weight: float,
    *,
    cap: float = CONCENTRATION_CAP,
) -> SentinelDecision:
    """R4: hard backstop on per-agent risk budget share."""
    if intended_weight > cap:
        return SentinelDecision(
            allowed=False,
            rule="R4",
            reason=(
                f"agent {agent_id} weight {intended_weight:.3f} > "
                f"concentration cap {cap:.2f}"
            ),
            payload={
                "agent_id": agent_id,
                "intended_weight": float(intended_weight),
                "cap": float(cap),
            },
        )
    return SentinelDecision(
        allowed=True, rule="OK", reason="R4 ok", payload={}
    )


# ---------------------------------------------------------------------------
# R5 — Loss-streak dampener
# ---------------------------------------------------------------------------

def check_r5_loss_streak(
    consecutive_losses: int,
    *,
    trigger: int = LOSS_STREAK_TRIGGER,
    dampener: float = LOSS_STREAK_DAMPENER,
) -> tuple[float, SentinelDecision]:
    """R5: return ``(risk_scale, decision)``.

    risk_scale is 1.0 if no streak active, `dampener` (default 0.5)
    when the streak has been triggered. Distinct from A10 Kunigami's
    in-cast anti-tilt logic — R5 is the Sentinel's outer multiplier
    that compounds with Kunigami's.
    """
    if consecutive_losses >= trigger:
        return dampener, SentinelDecision(
            allowed=True,
            rule="R5",
            reason=(
                f"{consecutive_losses} consecutive losses; "
                f"applying {dampener:.0%} risk scale for next "
                f"{LOSS_STREAK_DURATION_HOURS}h"
            ),
            payload={
                "consecutive_losses": int(consecutive_losses),
                "risk_scale": float(dampener),
                "duration_hours": int(LOSS_STREAK_DURATION_HOURS),
            },
        )
    return 1.0, SentinelDecision(
        allowed=True, rule="OK", reason="R5 ok", payload={}
    )


# ---------------------------------------------------------------------------
# R6 — Per-symbol total-risk cap (Phi5 Arm 4 multi-position ceiling)
# ---------------------------------------------------------------------------

def check_r6_per_symbol_risk_cap(
    symbol: str,
    current_symbol_risk_dollars: float,
    additional_risk_dollars: float,
    *,
    equity: float,
    cap_frac: float = SANDBOX_PER_SYMBOL_RISK_FRAC,
) -> SentinelDecision:
    """R6: refuse if opening this order would push total per-symbol risk above cap.

    Distinct from R1 (per-trade risk floor) and R4 (per-agent concentration).
    R6 is the ceiling used by Phi5 Arm 4 multi-position: even if two distinct
    agents each pass R1 individually on the same symbol, their combined risk
    cannot exceed ``cap_frac * equity``. Default cap 1% mirrors the sandbox
    single-position budget so Arm 4 splits, not doubles, the per-symbol risk.
    """
    combined = float(current_symbol_risk_dollars) + float(additional_risk_dollars)
    cap_dollars = float(cap_frac) * float(equity)
    if combined > cap_dollars:
        return SentinelDecision(
            allowed=False,
            rule="R6",
            reason=(
                f"symbol {symbol} combined risk ${combined:.2f} > cap "
                f"${cap_dollars:.2f} (={cap_frac*100:.2f}% of equity)"
            ),
            payload={
                "symbol": symbol,
                "current_symbol_risk_dollars": float(current_symbol_risk_dollars),
                "additional_risk_dollars": float(additional_risk_dollars),
                "combined_risk_dollars": float(combined),
                "cap_dollars": float(cap_dollars),
                "cap_frac": float(cap_frac),
            },
        )
    return SentinelDecision(
        allowed=True, rule="OK", reason="R6 ok", payload={
            "symbol": symbol,
            "combined_risk_dollars": float(combined),
        },
    )


# ---------------------------------------------------------------------------
# R7 -- News-impact ladder (Karasu-consumer)
# ---------------------------------------------------------------------------
#
# Karasu (A8) publishes advisories to the workspace; the Sentinel's R7 is
# the hard-rule layer that turns them into a decision:
#
#   impact == "high"   -> BLOCK the proposal (allowed=False, rule=R7).
#   impact == "medium" -> ALLOW but return risk_scale (default 0.5),
#                         which the executor is responsible for applying
#                         to the sizer output. Rule tag "R7" so the
#                         audit log can distinguish it from R5 dampening.
#   impact == "none"   -> pass through (rule="OK").
#
# The block/scale ladder is a two-knob surface on SentinelContext
# (``news_impact_block_min`` and ``news_impact_scale_medium``) so the
# Phase AD arm can vary them without a source patch.

NEWS_R7_BLOCK_IMPACTS_DEFAULT: frozenset[str] = frozenset({"high"})
NEWS_R7_SCALE_IMPACTS_DEFAULT: frozenset[str] = frozenset({"medium"})
NEWS_R7_SCALE_FACTOR_DEFAULT: float = 0.5


def check_r7_news_impact(
    *,
    impact: str,
    event_title: str | None = None,
    currencies: frozenset[str] | None = None,
    minutes_to_event: int | None = None,
    block_impacts: frozenset[str] = NEWS_R7_BLOCK_IMPACTS_DEFAULT,
    scale_impacts: frozenset[str] = NEWS_R7_SCALE_IMPACTS_DEFAULT,
    scale_factor: float = NEWS_R7_SCALE_FACTOR_DEFAULT,
) -> SentinelDecision:
    """R7: convert a Karasu news-window impact into a Sentinel decision.

    Inputs are the fields of :class:`agent.squad.agents.a08_karasu.KarasuWarning`;
    the caller (the engine's SentinelContext builder) resolves the
    warning per (symbol, as_of) and passes it here as flat kwargs so
    the rule stays a pure function.

    ``impact`` is compared **case-insensitively**. Passing ``"none"``
    (or the empty string) short-circuits to a pass-through OK.
    """
    imp = (impact or "none").strip().lower()
    if imp == "none" or not imp:
        return SentinelDecision(
            allowed=True, rule="OK", reason="R7 ok", payload={},
            risk_scale=1.0,
        )

    payload: dict = {
        "impact": imp,
        "event_title": event_title,
        "currencies": sorted(currencies) if currencies else [],
        "minutes_to_event": minutes_to_event,
    }
    block = {i.lower() for i in block_impacts}
    scale = {i.lower() for i in scale_impacts}

    if imp in block:
        return SentinelDecision(
            allowed=False,
            rule="R7",
            reason=(
                f"R7_news_high_impact: {imp}-impact news window"
                + (f" ('{event_title}')" if event_title else "")
                + (
                    f" in {minutes_to_event:+d} min"
                    if minutes_to_event is not None else ""
                )
            ),
            payload=payload,
            risk_scale=0.0,
        )
    if imp in scale:
        return SentinelDecision(
            allowed=True,
            rule="R7",
            reason=(
                f"R7_news_medium_impact_scale: applying "
                f"{scale_factor:.0%} risk scale"
                + (f" ('{event_title}')" if event_title else "")
            ),
            payload=payload,
            risk_scale=float(scale_factor),
        )
    return SentinelDecision(
        allowed=True, rule="OK", reason="R7 ok (impact not in ladder)",
        payload=payload, risk_scale=1.0,
    )


# ---------------------------------------------------------------------------
# External-shock triggers (doctrine section 4.2)
# ---------------------------------------------------------------------------

@dataclass
class ExternalShockState:
    """Inputs to the external-shock evaluator.

    Phi2.5 keeps this as a dataclass that the engine fills in from
    its market feed. Phi3+ wires this to the calendar adapter +
    DXY feed.
    """

    cross_pair_rho_30d: float = 0.0           # |rho| > 0.95 -> fire
    spread_x_trailing_median: float = 1.0     # > 3x -> fire
    high_impact_event_within_2h: bool = False
    high_impact_prior_regime_shift: bool = False
    dxy_h1_sigma_z: float = 0.0               # > 2 -> fire


def check_external_shocks(state: ExternalShockState) -> SentinelDecision:
    """Evaluate the four external-shock triggers from doctrine 4.2."""
    if abs(state.cross_pair_rho_30d) > 0.95:
        return SentinelDecision(
            allowed=False, rule="EXT",
            reason=f"cross-pair |rho|={state.cross_pair_rho_30d:.2f} > 0.95",
            payload={"trigger": "rho_jump"},
        )
    if state.spread_x_trailing_median > 3.0:
        return SentinelDecision(
            allowed=False, rule="EXT",
            reason=(
                f"spread is {state.spread_x_trailing_median:.1f}x trailing "
                "median (> 3x)"
            ),
            payload={"trigger": "spread_spike"},
        )
    if state.high_impact_event_within_2h and state.high_impact_prior_regime_shift:
        return SentinelDecision(
            allowed=False, rule="EXT",
            reason="high-impact calendar event within 2h with prior regime shift",
            payload={"trigger": "calendar"},
        )
    if state.dxy_h1_sigma_z > 2.0:
        return SentinelDecision(
            allowed=False, rule="EXT",
            reason=f"DXY H1 sigma-z={state.dxy_h1_sigma_z:.2f} > 2",
            payload={"trigger": "dxy_shock"},
        )
    return SentinelDecision(
        allowed=True, rule="OK", reason="no external shocks", payload={}
    )


# ---------------------------------------------------------------------------
# Aggregate evaluator used by the kernel
# ---------------------------------------------------------------------------

@dataclass
class SentinelContext:
    """Per-tick state passed to `evaluate`.

    `kunigami_loss_streak_active` is the Sentinel's R5 input: when Kunigami
    (or any other loss-streak signal source) says the squad is on a
    high-conviction losing streak, the Sentinel dampens risk 24 h.
    `open_symbol_risk_dollars` and `additional_risk_dollars` are the
    R6 (per-symbol total-risk cap) inputs used by Phi5 Arm 4.

    R7 news-impact inputs (Karasu-side):

    * ``karasu_impact``: one of ``"high"``, ``"medium"``, ``"none"``.
      Callers derive it by resolving the Karasu warning for the
      proposal's ``(symbol, timestamp)`` before invoking evaluate.
    * ``karasu_event_title`` / ``karasu_event_currencies`` /
      ``karasu_minutes_to_event``: passthrough fields; only used
      to enrich the R7 payload's audit trail.
    * ``news_impact_block_min`` / ``news_impact_scale_medium`` /
      ``news_impact_scale_factor``: ladder knobs. Defaults match
      the doctrine (block on 'high', 50 % on 'medium').
    """

    equity: float
    pip_value_per_min_lot: float
    consecutive_losses: int = 0
    proposals_today_by_agent: dict[str, int] | None = None
    intended_weights_by_agent: dict[str, float] | None = None
    external: ExternalShockState | None = None
    kunigami_loss_streak_active: bool = False
    open_symbol_risk_dollars: dict[str, float] | None = None
    additional_risk_dollars: float | None = None
    karasu_impact: str = "none"
    karasu_event_title: str | None = None
    karasu_event_currencies: frozenset[str] | None = None
    karasu_minutes_to_event: int | None = None
    news_impact_block_min: frozenset[str] = field(
        default_factory=lambda: NEWS_R7_BLOCK_IMPACTS_DEFAULT,
    )
    news_impact_scale_medium: frozenset[str] = field(
        default_factory=lambda: NEWS_R7_SCALE_IMPACTS_DEFAULT,
    )
    news_impact_scale_factor: float = NEWS_R7_SCALE_FACTOR_DEFAULT


def evaluate_proposal(
    proposal: AgentProposal,
    context: SentinelContext,
) -> SentinelDecision:
    """Convenience wrapper: evaluate a proposal without an OrderIntent.

    Harness callers use this when sizing has not yet been decided --
    Sentinel only needs the proposal's entry + stop + agent_id + symbol
    to run R1/R3/R4/R5/R6. Delegates to :func:`evaluate` with a minimal
    intent shim.
    """

    class _IntentShim:
        pass

    shim = _IntentShim()
    shim.entry = float(proposal.entry)      # type: ignore[attr-defined]
    shim.stop = float(proposal.stop)        # type: ignore[attr-defined]
    return evaluate(proposal, shim, context)  # type: ignore[arg-type]


def evaluate(
    proposal: AgentProposal,
    intent: OrderIntent,
    context: SentinelContext,
) -> SentinelDecision:
    """Run the full R1-R6 + external sequence on one OrderIntent.

    First failure wins (R-rules are precedence-ordered: R1, R3, R4, R5, R6,
    EXT). R2 is an in-line size adjustment applied separately by the caller
    when Sentinel is in physical-enforcement mode.
    """
    sl_distance_pips = abs(intent.entry - intent.stop) * 1e4

    r1 = check_r1_min_lot_risk_floor(
        sl_distance_pips=sl_distance_pips,
        pip_value_per_min_lot=context.pip_value_per_min_lot,
        equity=context.equity,
    )
    if not r1.allowed:
        return r1

    if context.proposals_today_by_agent is not None:
        r3 = check_r3_pass_bias(
            proposal.agent_id,
            context.proposals_today_by_agent.get(proposal.agent_id, 0),
        )
        if r3.rule == "R3":
            return r3

    if context.intended_weights_by_agent is not None:
        r4 = check_r4_concentration(
            proposal.agent_id,
            context.intended_weights_by_agent.get(proposal.agent_id, 0.0),
        )
        if not r4.allowed:
            return r4

    if context.kunigami_loss_streak_active or context.consecutive_losses >= LOSS_STREAK_TRIGGER:
        _, r5 = check_r5_loss_streak(
            max(context.consecutive_losses, LOSS_STREAK_TRIGGER),
        )
        if r5.rule == "R5":
            return r5

    if (
        context.open_symbol_risk_dollars is not None
        and context.additional_risk_dollars is not None
    ):
        r6 = check_r6_per_symbol_risk_cap(
            proposal.symbol,
            context.open_symbol_risk_dollars.get(proposal.symbol, 0.0),
            context.additional_risk_dollars,
            equity=context.equity,
        )
        if not r6.allowed:
            return r6

    if (context.karasu_impact or "none").lower() != "none":
        r7 = check_r7_news_impact(
            impact=context.karasu_impact,
            event_title=context.karasu_event_title,
            currencies=context.karasu_event_currencies,
            minutes_to_event=context.karasu_minutes_to_event,
            block_impacts=context.news_impact_block_min,
            scale_impacts=context.news_impact_scale_medium,
            scale_factor=context.news_impact_scale_factor,
        )
        if not r7.allowed:
            return r7
        if r7.rule == "R7":
            # Medium-impact scale-only path: R7 rides alongside the
            # subsequent rules (only EXT can still block). We return
            # the scale-decorated decision if EXT passes below.
            _r7_pending = r7
        else:
            _r7_pending = None
    else:
        _r7_pending = None

    if context.external is not None:
        ext = check_external_shocks(context.external)
        if not ext.allowed:
            return ext

    if _r7_pending is not None:
        return _r7_pending
    return SentinelDecision(
        allowed=True, rule="OK", reason="ok", payload={},
        risk_scale=1.0,
    )
