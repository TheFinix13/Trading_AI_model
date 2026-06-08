"""Tests for the adaptive, risk-based PositionSizer."""
from agent.live.position_sizer import PositionSizer, SymbolConstraints


def _sizer() -> PositionSizer:
    return PositionSizer(min_risk_pct=0.005, max_risk_pct=0.02)


def test_risk_pct_scales_with_conviction():
    s = _sizer()
    assert s.risk_pct_for_conviction(0.0) == 0.005
    assert s.risk_pct_for_conviction(1.0) == 0.02
    mid = s.risk_pct_for_conviction(0.5)
    assert abs(mid - 0.0125) < 1e-9


def test_conviction_clamped():
    s = _sizer()
    assert s.risk_pct_for_conviction(-1.0) == 0.005
    assert s.risk_pct_for_conviction(2.0) == 0.02


def test_lot_risks_requested_pct():
    s = _sizer()
    # 1% of $10,000 = $100 risk; 20-pip stop * $10/pip = $200/lot -> 0.5 lots.
    res = s.calculate_lot(
        balance=10_000.0, stop_distance_pips=20.0, risk_pct=0.01,
        pip_value=10.0, price=1.10, leverage=500,
    )
    assert abs(res.lot - 0.50) < 1e-9
    assert abs(res.risk_amount - 100.0) < 1e-6
    assert abs(res.actual_risk_pct - 0.01) < 1e-6


def test_lot_floored_to_step_never_exceeds_budget():
    s = _sizer()
    # Raw lot = 0.137 -> floored to 0.13 at 0.01 step.
    res = s.calculate_lot(
        balance=10_000.0, stop_distance_pips=73.0, risk_pct=0.01,
        pip_value=10.0, price=1.10, leverage=500,
        constraints=SymbolConstraints(lot_step=0.01),
    )
    assert res.lot == 0.13
    # Floored size risks no more than the requested budget.
    assert res.risk_amount <= 10_000.0 * 0.01 + 1e-6


def test_min_lot_snap_for_small_account():
    s = _sizer()
    # $100 balance, 20-pip stop. Raw lot tiny; snaps to 0.01 min since the
    # min-lot risk (0.01*20*10/100 = 2%) is within the band.
    res = s.calculate_lot(
        balance=100.0, stop_distance_pips=20.0, conviction=0.5,
        pip_value=10.0, price=1.10, leverage=1000,
    )
    assert res.lot == 0.01
    assert res.capped_by == "min_lot"


def test_skips_when_min_lot_risk_too_high():
    s = _sizer()
    # $100 balance, 300-pip stop: min-lot risk = 0.01*300*10/100 = 30% -> skip.
    res = s.calculate_lot(
        balance=100.0, stop_distance_pips=300.0, conviction=0.5,
        pip_value=10.0, price=1.10, leverage=1000,
    )
    assert res.lot == 0.0
    assert res.capped_by == "risk_too_high"


def test_free_margin_caps_lot():
    s = _sizer()
    # Risk lot would be 2.0 (0.02*10000 / (10*10)). Tiny leverage + limited free
    # margin should bind the size well below that.
    res = s.calculate_lot(
        balance=10_000.0, stop_distance_pips=10.0, risk_pct=0.02,
        pip_value=10.0, price=1.10, leverage=1,
        free_margin=5_000.0,
        constraints=SymbolConstraints(contract_size=100_000.0),
    )
    # margin per lot = 100000*1.10/1 = 110,000; 90% of $5000 -> 0.04 lots.
    assert res.capped_by == "free_margin"
    assert res.lot == 0.04
    assert res.margin_required <= 5_000.0


def test_insufficient_margin_returns_zero():
    s = _sizer()
    # Free margin can't even cover the minimum lot's margin -> skip.
    res = s.calculate_lot(
        balance=10_000.0, stop_distance_pips=10.0, risk_pct=0.02,
        pip_value=10.0, price=1.10, leverage=1,
        free_margin=500.0,
        constraints=SymbolConstraints(contract_size=100_000.0),
    )
    assert res.lot == 0.0
    assert res.capped_by == "insufficient_margin"


def test_manual_cap_upper_bounds_lot():
    s = _sizer()
    res = s.calculate_lot(
        balance=100_000.0, stop_distance_pips=10.0, risk_pct=0.02,
        pip_value=10.0, price=1.10, leverage=1000, manual_cap=0.05,
    )
    assert res.lot == 0.05
    assert res.capped_by == "manual_cap"


def test_invalid_inputs_return_zero():
    s = _sizer()
    res = s.calculate_lot(balance=0.0, stop_distance_pips=20.0, risk_pct=0.01)
    assert res.lot == 0.0
    assert res.capped_by == "invalid_inputs"
