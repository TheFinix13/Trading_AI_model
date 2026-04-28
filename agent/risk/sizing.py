"""Position sizing: derive lot size from stop distance and risk percentage."""
from __future__ import annotations

from agent.config import RiskConfig


def position_size(
    account_balance: float,
    stop_pips: float,
    pip_value_per_lot: float,
    risk_cfg: RiskConfig,
) -> tuple[float, float]:
    """Return (lot_size, actual_risk_pct).

    Tries to honor risk_cfg.pct_target. If the resulting lot is below the broker minimum,
    snaps to minimum, which may push the actual risk above target up to risk_cfg.pct_floor.
    Above the floor, refuses to trade (returns lot=0)."""
    if stop_pips <= 0 or pip_value_per_lot <= 0 or account_balance <= 0:
        return 0.0, 0.0

    target_risk_dollars = account_balance * risk_cfg.pct_target
    raw_lot = target_risk_dollars / (stop_pips * pip_value_per_lot)

    cap = _hard_cap(account_balance, risk_cfg)

    rounded = _floor_to_step(raw_lot, risk_cfg.lot_step)

    if rounded < risk_cfg.lot_min:
        # snap up to minimum and check the resulting risk
        candidate = risk_cfg.lot_min
        risk_at_min = (candidate * stop_pips * pip_value_per_lot) / account_balance
        if risk_at_min > risk_cfg.pct_floor:
            return 0.0, risk_at_min  # too risky to trade, skip
        rounded = candidate

    rounded = min(rounded, cap)
    if rounded < risk_cfg.lot_min:
        return 0.0, 0.0

    actual_risk = (rounded * stop_pips * pip_value_per_lot) / account_balance
    return round(rounded, 2), actual_risk


def _hard_cap(balance: float, cfg: RiskConfig) -> float:
    if balance < 300:
        return cfg.lot_hard_cap_under_300
    if balance < 1000:
        return cfg.lot_hard_cap_under_1000
    return cfg.lot_hard_cap


def _floor_to_step(value: float, step: float) -> float:
    return round(int(value / step) * step, 2)
