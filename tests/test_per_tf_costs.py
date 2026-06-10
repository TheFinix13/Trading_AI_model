"""Per-TF cost model: lower TFs must be quoted realistically wider."""
from __future__ import annotations

from agent.config import BacktestConfig


def test_cost_for_returns_tf_specific_values():
    bt = BacktestConfig()
    d1_spread, d1_slip, d1_comm = bt.cost_for("D1")
    m1_spread, m1_slip, m1_comm = bt.cost_for("M1")
    assert m1_spread > d1_spread
    assert m1_slip > d1_slip
    assert m1_comm == d1_comm  # commission is a broker constant


def test_cost_for_unknown_tf_falls_back_to_defaults():
    bt = BacktestConfig(spread_pips=2.5, slippage_pips=1.1, commission_per_lot=8.0)
    spread, slip, comm = bt.cost_for("XYZ")
    assert spread == 2.5
    assert slip == 1.1
    assert comm == 8.0


def test_cost_monotonic_top_to_bottom():
    """Realism check: spread must not decrease as we walk down the TF ladder."""
    bt = BacktestConfig()
    ladder = ["D1", "H4", "H1", "M30", "M15", "M5", "M3", "M1"]
    prev_spread = -1.0
    for tf in ladder:
        s, _, _ = bt.cost_for(tf)
        assert s >= prev_spread, f"{tf} spread {s} < previous {prev_spread}"
        prev_spread = s


def test_override_via_cost_by_tf():
    bt = BacktestConfig(cost_by_tf={"H1": {"spread": 0.1, "slippage": 0.0}})
    s, slip, _ = bt.cost_for("H1")
    assert s == 0.1
    assert slip == 0.0
