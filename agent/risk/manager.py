"""Account-level risk manager: daily DD circuit breaker, max positions, kill switch, position sizing.

This is the LAST gate before any order is placed. Hard rules, never overridden by ML."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from agent.config import Config
from agent.risk.sizing import position_size
from agent.types import Setup
from agent.utils import kill_switch_active

log = logging.getLogger(__name__)


@dataclass
class RiskState:
    day: date | None = None
    day_open_balance: float = 0.0
    day_pnl: float = 0.0
    halted_today: bool = False
    open_positions: int = 0
    history: list[float] = field(default_factory=list)


class RiskDecision:
    APPROVED = "approved"
    SKIP_KILL_SWITCH = "skip_kill_switch"
    SKIP_DAILY_HALT = "skip_daily_halt"
    SKIP_MAX_POSITIONS = "skip_max_positions"
    SKIP_RISK_TOO_HIGH = "skip_risk_too_high"
    SKIP_LOT_TOO_SMALL = "skip_lot_too_small"


@dataclass
class RiskResult:
    decision: str
    lot_size: float = 0.0
    actual_risk_pct: float = 0.0
    reason: str = ""


class RiskManager:
    def __init__(self, cfg: Config, kill_switch_path: Path | None = None):
        self.cfg = cfg
        self.kill_switch_path = kill_switch_path or cfg.kill_switch_file
        self.state = RiskState()

    def on_new_day(self, today: date, balance: float) -> None:
        if self.state.day != today:
            self.state.day = today
            self.state.day_open_balance = balance
            self.state.day_pnl = 0.0
            self.state.halted_today = False

    def record_trade_pnl(self, pnl: float) -> None:
        self.state.day_pnl += pnl
        if self.state.day_open_balance > 0:
            dd = -self.state.day_pnl / self.state.day_open_balance
            if dd >= self.cfg.risk.daily_dd_halt_pct:
                self.state.halted_today = True
                log.warning("Daily DD halt triggered: dd=%.4f >= %.4f", dd, self.cfg.risk.daily_dd_halt_pct)

    def evaluate(
        self,
        setup: Setup,
        account_balance: float,
        open_positions: int,
        now: datetime,
    ) -> RiskResult:
        self.on_new_day(now.date(), account_balance)
        self.state.open_positions = open_positions

        if kill_switch_active(self.kill_switch_path):
            return RiskResult(RiskDecision.SKIP_KILL_SWITCH, reason="kill switch file present")

        if self.state.halted_today:
            return RiskResult(RiskDecision.SKIP_DAILY_HALT, reason="daily DD halt active")

        if open_positions >= self.cfg.risk.max_open_positions:
            return RiskResult(RiskDecision.SKIP_MAX_POSITIONS, reason=f"open={open_positions}")

        lot, actual_risk = position_size(
            account_balance=account_balance,
            stop_pips=setup.stop_pips,
            pip_value_per_lot=self.cfg.backtest.pip_value_per_lot,
            risk_cfg=self.cfg.risk,
        )

        if lot <= 0 and actual_risk > self.cfg.risk.pct_floor:
            return RiskResult(
                RiskDecision.SKIP_RISK_TOO_HIGH,
                actual_risk_pct=actual_risk,
                reason=f"min lot risk {actual_risk:.4f} > floor {self.cfg.risk.pct_floor:.4f}",
            )

        if lot <= 0:
            return RiskResult(RiskDecision.SKIP_LOT_TOO_SMALL, reason="computed lot <= 0")

        return RiskResult(RiskDecision.APPROVED, lot_size=lot, actual_risk_pct=actual_risk)
