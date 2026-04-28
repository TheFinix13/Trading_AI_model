from agent.config import RiskConfig
from agent.risk.sizing import position_size


def test_size_at_100_with_30_pip_stop_forces_floor():
    cfg = RiskConfig()
    lot, risk = position_size(account_balance=100.0, stop_pips=30.0, pip_value_per_lot=10.0, risk_cfg=cfg)
    # 0.01 lot * 30 pips * $10 = $3 = 3% of $100 (right at the floor)
    assert lot == 0.01
    assert abs(risk - 0.03) < 0.001


def test_size_at_100_with_huge_stop_refuses():
    cfg = RiskConfig()
    lot, risk = position_size(account_balance=100.0, stop_pips=300.0, pip_value_per_lot=10.0, risk_cfg=cfg)
    assert lot == 0.0  # 0.01 lot * 300 pips * 10 = 30 = 30% > floor


def test_size_at_300_uses_target_pct():
    cfg = RiskConfig()
    lot, risk = position_size(account_balance=300.0, stop_pips=30.0, pip_value_per_lot=10.0, risk_cfg=cfg)
    assert lot == 0.01
    assert 0.009 < risk < 0.011  # ~1%


def test_size_at_1000_scales():
    cfg = RiskConfig()
    lot, risk = position_size(account_balance=1000.0, stop_pips=50.0, pip_value_per_lot=10.0, risk_cfg=cfg)
    # target risk $10, divisor 50*10=500, raw lot = 0.02
    assert lot == 0.02
    assert abs(risk - 0.01) < 0.001


def test_hard_cap_under_300():
    cfg = RiskConfig()
    lot, _ = position_size(account_balance=200.0, stop_pips=10.0, pip_value_per_lot=10.0, risk_cfg=cfg)
    # raw lot would be (200 * 0.01) / (10 * 10) = 0.02; hard cap is 0.01 under $300
    assert lot == 0.01
