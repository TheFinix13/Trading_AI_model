"""Unit tests for the portfolio-wide open-risk ceiling (Wave 2.2).

Exercises ``RiskManager.portfolio_open_risk_pct`` and
``RiskManager.evaluate_portfolio_ceiling`` with synthetic ``Position``-like
objects. No broker roundtrip and no signal-loop coupling; the test contract
is that:

* Total risk across ALL open tickets is computed as the sum of
  ``abs(open_price - stop_loss) * volume * pip_value_per_lot``.
* A prospective ticket that would push the total over
  ``RiskConfig.portfolio_max_open_risk_pct`` is hard-blocked.
* Tickets with missing or zero stop_loss contribute zero risk (they are
  the broker's problem, not the pre-trade gate's).
* An account_balance of zero returns SKIP_PORTFOLIO_RISK.
* Setting the cap to zero disables the check.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent.config import load_config
from agent.risk.manager import RiskDecision, RiskManager


@dataclass
class FakePosition:
    """Minimal duck-typed stand-in for :class:`agent.live.broker.Position`."""

    open_price: float
    stop_loss: float
    volume: float


PIP_VALUE_PER_LOT = 10.0  # matches BacktestConfig default for EUR-quoted pairs


def _cfg_with_cap(cap: float):
    cfg = load_config()
    cfg.risk.portfolio_max_open_risk_pct = cap
    return cfg


def test_zero_positions_returns_zero_pct():
    pct = RiskManager.portfolio_open_risk_pct([], 1000.0, PIP_VALUE_PER_LOT)
    assert pct == 0.0


def test_zero_balance_returns_infinity():
    positions = [FakePosition(1.10, 1.098, 0.10)]
    pct = RiskManager.portfolio_open_risk_pct(positions, 0.0, PIP_VALUE_PER_LOT)
    assert pct == float("inf")


def test_two_symbol_portfolio_sums_correctly():
    # EURUSD ticket: 20 pip stop x 0.10 lot x $10 pip = $20 risk
    eur = FakePosition(open_price=1.1000, stop_loss=1.0980, volume=0.10)
    # GBPUSD ticket: 50 pip stop x 0.05 lot x $10 pip = $25 risk
    gbp = FakePosition(open_price=1.3000, stop_loss=1.2950, volume=0.05)
    # Total = $45 on $1000 = 4.5%
    pct = RiskManager.portfolio_open_risk_pct(
        [eur, gbp], 1000.0, PIP_VALUE_PER_LOT,
    )
    assert pct == pytest.approx(0.045, abs=1e-6)


def test_missing_stop_counts_as_zero_risk():
    # A ticket where the broker has no stop set (shouldn't happen in
    # practice, but guard against divide-by-zero and false positives).
    p_no_stop = FakePosition(open_price=1.1000, stop_loss=0.0, volume=0.10)
    p_with_stop = FakePosition(open_price=1.1000, stop_loss=1.0980, volume=0.10)
    pct = RiskManager.portfolio_open_risk_pct(
        [p_no_stop, p_with_stop], 1000.0, PIP_VALUE_PER_LOT,
    )
    # Only the second ticket contributes: 20 pips * 0.10 * 10 = $20 = 2%
    assert pct == pytest.approx(0.02, abs=1e-6)


def test_new_ticket_pushes_over_cap_rejects():
    cfg = _cfg_with_cap(0.05)
    rm = RiskManager(cfg)
    # Current portfolio: 20 pip x 0.10 = $20; 50 pip x 0.05 = $25; total $45 = 4.5% of $1000
    positions = [
        FakePosition(1.1000, 1.0980, 0.10),
        FakePosition(1.3000, 1.2950, 0.05),
    ]
    # New ticket: 30 pip x 0.05 lot x $10 = $15 risk = 1.5%
    # 4.5 + 1.5 = 6.0% > 5% cap -> rejected
    res = rm.evaluate_portfolio_ceiling(
        positions=positions,
        account_balance=1000.0,
        prospective_stop_pips=30.0,
        prospective_lot=0.05,
    )
    assert res.decision == RiskDecision.SKIP_PORTFOLIO_RISK
    assert "6.00%" in res.reason
    assert "5.00%" in res.reason


def test_new_ticket_below_cap_approves():
    cfg = _cfg_with_cap(0.05)
    rm = RiskManager(cfg)
    positions = [FakePosition(1.1000, 1.0980, 0.10)]  # 20 * 0.10 * 10 = $20 = 2%
    # New ticket: 10 pip x 0.01 lot x $10 = $1 = 0.1%
    # 2.0 + 0.1 = 2.1% < 5% cap -> approved
    res = rm.evaluate_portfolio_ceiling(
        positions=positions,
        account_balance=1000.0,
        prospective_stop_pips=10.0,
        prospective_lot=0.01,
    )
    assert res.decision == RiskDecision.APPROVED
    assert res.actual_risk_pct == pytest.approx(0.021, abs=1e-6)


def test_at_exact_cap_boundary_approves():
    # Boundary case: prospective total == cap should approve
    # (cap is a "must not exceed" ceiling, not "must be strictly below").
    cfg = _cfg_with_cap(0.05)
    rm = RiskManager(cfg)
    positions = [
        FakePosition(1.1000, 1.0980, 0.10),  # $20 risk = 2%
    ]
    # New ticket that brings total to exactly 5%: needs $30 more risk
    # $30 = pips * lot * $10 -> at 30 pips, lot = 0.10
    res = rm.evaluate_portfolio_ceiling(
        positions=positions,
        account_balance=1000.0,
        prospective_stop_pips=30.0,
        prospective_lot=0.10,
    )
    assert res.decision == RiskDecision.APPROVED
    assert res.actual_risk_pct == pytest.approx(0.05, abs=1e-6)


def test_disabled_cap_always_approves():
    cfg = _cfg_with_cap(0.0)
    rm = RiskManager(cfg)
    # An absurdly over-risked prospective ticket
    res = rm.evaluate_portfolio_ceiling(
        positions=[],
        account_balance=1000.0,
        prospective_stop_pips=1000.0,
        prospective_lot=1.0,
    )
    assert res.decision == RiskDecision.APPROVED


def test_zero_balance_rejects():
    cfg = _cfg_with_cap(0.05)
    rm = RiskManager(cfg)
    res = rm.evaluate_portfolio_ceiling(
        positions=[],
        account_balance=0.0,
        prospective_stop_pips=30.0,
        prospective_lot=0.10,
    )
    assert res.decision == RiskDecision.SKIP_PORTFOLIO_RISK


def test_already_at_cap_rejects_any_new_ticket():
    """A portfolio that's already at the cap must reject even a tiny new
    ticket; the cap is total-inclusive."""
    cfg = _cfg_with_cap(0.05)
    rm = RiskManager(cfg)
    # $50 risk on $1000 = exactly 5%
    positions = [FakePosition(1.1000, 1.0950, 0.10)]  # 50 * 0.10 * 10 = $50
    # Try to add even a min-lot 10-pip stop = $1 = 0.1% -> pushes over
    res = rm.evaluate_portfolio_ceiling(
        positions=positions,
        account_balance=1000.0,
        prospective_stop_pips=10.0,
        prospective_lot=0.01,
    )
    assert res.decision == RiskDecision.SKIP_PORTFOLIO_RISK
