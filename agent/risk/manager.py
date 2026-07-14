"""Account-level risk manager: daily DD circuit breaker, max positions, kill switch, position sizing.

This is the LAST gate before any order is placed. Hard rules, never overridden by ML."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from typing import Sequence

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


@dataclass
class DDHaltRecoveryState:
    """Cross-day bookkeeping for daily-DD-halt self-recovery.

    Unlike :class:`RiskState` (which is day-scoped and reset every UTC
    rollover), this survives day rollover AND process restart: it is how
    the thrash guard remembers that the *same symbol* auto-DD-halted on
    several consecutive days. Persisted via a dedicated, NON-day-scoped
    section of ``state.json`` (see ``get_recovery_state`` /
    ``restore_recovery_state``).
    """
    # UTC dates (ISO strings) on which a daily-DD auto-halt was recorded at
    # its rollover clear. Bounded tail; only the recent run matters.
    halt_dates: list[str] = field(default_factory=list)
    # Latched once the thrash guard escalates so we neither re-alert nor
    # keep re-arming a symbol that halts every single day.
    escalated: bool = False


@dataclass
class DDHaltRolloverDecision:
    """Result of :meth:`RiskManager.evaluate_dd_halt_rollover`.

    ``action`` is one of ``"hold"`` / ``"clear"`` / ``"escalate"``; the
    counts let the caller render an accurate operator notification without
    reaching back into risk state.
    """
    action: str
    consecutive_days: int = 0
    sticky_after: int = 0


class RiskDecision:
    APPROVED = "approved"
    SKIP_KILL_SWITCH = "skip_kill_switch"
    SKIP_DAILY_HALT = "skip_daily_halt"
    SKIP_MAX_POSITIONS = "skip_max_positions"
    SKIP_RISK_TOO_HIGH = "skip_risk_too_high"
    SKIP_LOT_TOO_SMALL = "skip_lot_too_small"
    SKIP_PORTFOLIO_RISK = "skip_portfolio_risk"


@dataclass
class RiskResult:
    decision: str
    lot_size: float = 0.0
    actual_risk_pct: float = 0.0
    reason: str = ""


class RiskManager:
    # Thrash guard: if the SAME symbol auto-DD-halts on this many
    # consecutive UTC days, stop silently re-arming — escalate to a sticky
    # halt + Telegram alert so a human looks at why it keeps blowing the 3%
    # daily budget (a persistently broken regime, not a one-off bad day).
    # 3 = "twice was noise, three days running is a pattern"; documented in
    # the reliability report and E019 protocol.
    DD_HALT_STICKY_AFTER_DAYS: int = 3
    # Bound the persisted history so state.json can't grow without limit.
    _DD_HALT_HISTORY_MAX: int = 30

    def __init__(self, cfg: Config, kill_switch_path: Path | None = None):
        self.cfg = cfg
        self.kill_switch_path = kill_switch_path or cfg.kill_switch_file
        self.state = RiskState()
        self.recovery = DDHaltRecoveryState()

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

    # ------------------------------------------------------------------
    # Daily-DD-halt self-recovery (auto-clear at UTC rollover + thrash guard)
    # ------------------------------------------------------------------

    def _record_dd_halt_day(self, halt_date: date) -> None:
        """Idempotently record a daily-DD auto-halt day (keeps the tail)."""
        iso = halt_date.isoformat()
        if iso not in self.recovery.halt_dates:
            self.recovery.halt_dates.append(iso)
            self.recovery.halt_dates = self.recovery.halt_dates[
                -self._DD_HALT_HISTORY_MAX:
            ]

    def consecutive_dd_halt_days(self) -> int:
        """Length of the run of consecutive UTC calendar days ending at the
        most recently recorded daily-DD halt day (the *active* streak)."""
        if not self.recovery.halt_dates:
            return 0
        try:
            days = sorted({date.fromisoformat(d) for d in self.recovery.halt_dates})
        except (ValueError, TypeError):
            return 0
        streak = 1
        for i in range(len(days) - 1, 0, -1):
            if (days[i] - days[i - 1]).days == 1:
                streak += 1
            else:
                break
        return streak

    def evaluate_dd_halt_rollover(
        self, halt_date: date, today: date
    ) -> DDHaltRolloverDecision:
        """Decide what to do with a daily-DD auto-kill file.

        Pure decision + bookkeeping; the caller (PositionMonitor) performs
        the file I/O and notifications. ``action`` is one of:

        * ``"hold"``     — still the same UTC day as the halt: the 3%-PER-DAY
          budget has not reset yet, stay halted (no state change).
        * ``"clear"``    — a UTC rollover has passed: re-arm (delete the kill
          file). Records ``halt_date`` in the thrash history.
        * ``"escalate"`` — the same symbol has now auto-DD-halted on
          ``DD_HALT_STICKY_AFTER_DAYS`` consecutive days: convert to a sticky
          halt instead of re-arming, and latch ``recovery.escalated``.

        Fails safe: any non-rollover / same-day case returns ``"hold"``.
        """
        n = self.DD_HALT_STICKY_AFTER_DAYS
        if today <= halt_date:
            return DDHaltRolloverDecision("hold", sticky_after=n)
        # A rollover has happened — this halt day is now behind us.
        self._record_dd_halt_day(halt_date)
        streak = self.consecutive_dd_halt_days()
        if streak >= n or self.recovery.escalated:
            self.recovery.escalated = True
            log.warning(
                "Daily-DD halt thrash guard: %d consecutive DD-halt days "
                ">= %d — escalating to a STICKY halt (manual review).",
                streak, n,
            )
            return DDHaltRolloverDecision("escalate", streak, n)
        return DDHaltRolloverDecision("clear", streak, n)

    def get_recovery_state(self) -> dict:
        """JSON-serialisable snapshot of the NON-day-scoped recovery state.

        Persisted and restored unconditionally (see
        ``SignalLoop._restore_state``) so the thrash counter survives both
        UTC day rollover and process restart.
        """
        return {
            "halt_dates": list(self.recovery.halt_dates),
            "escalated": bool(self.recovery.escalated),
        }

    def restore_recovery_state(self, data: dict) -> None:
        """Restore recovery state from a persisted dict (never raises)."""
        raw_dates = data.get("halt_dates", [])
        if isinstance(raw_dates, list):
            self.recovery.halt_dates = [
                str(d) for d in raw_dates[-self._DD_HALT_HISTORY_MAX:]
            ]
        self.recovery.escalated = bool(data.get("escalated", False))
        log.info(
            "[STATE LOADED] dd_halt_recovery restored: %d halt-day(s) "
            "(streak=%d) escalated=%s",
            len(self.recovery.halt_dates), self.consecutive_dd_halt_days(),
            self.recovery.escalated,
        )

    # ------------------------------------------------------------------
    # Portfolio-wide open-risk ceiling (Wave 2.2, 2026-07-01)
    # ------------------------------------------------------------------

    @staticmethod
    def portfolio_open_risk_pct(
        positions: Sequence,
        account_balance: float,
        pip_value_per_lot: float,
    ) -> float:
        """Return the ACTIVE risk across every open ticket the broker holds,
        as a fraction of ``account_balance``.

        For each ticket, active risk is
        ``abs(open_price - stop_loss) * volume * pip_value_per_lot``
        (currency at risk if the broker's stop level fires). Tickets with a
        missing or zero stop are treated as zero-risk (the broker's
        catastrophe stop is the source of truth for the resting level; if
        it is not set, the ticket's open risk is unbounded, so we count
        it as zero here to avoid falsely blocking every entry - the
        surrounding SIGNAL_LOOP validation guarantees a stop is set on
        every ticket this agent opens).

        ``account_balance <= 0`` returns +infinity so any downstream
        comparison against a positive cap will reject.
        """
        if account_balance <= 0:
            return float("inf")
        total = 0.0
        for pos in positions:
            open_price = float(getattr(pos, "open_price", 0.0) or 0.0)
            stop_loss = float(getattr(pos, "stop_loss", 0.0) or 0.0)
            volume = float(getattr(pos, "volume", 0.0) or 0.0)
            if open_price <= 0 or stop_loss <= 0 or volume <= 0:
                continue
            stop_dist_price = abs(open_price - stop_loss)
            stop_pips = stop_dist_price * 10_000.0
            total += stop_pips * volume * pip_value_per_lot
        return total / account_balance

    def evaluate_portfolio_ceiling(
        self,
        positions: Sequence,
        account_balance: float,
        prospective_stop_pips: float,
        prospective_lot: float,
    ) -> RiskResult:
        """Return APPROVED iff opening the prospective (stop_pips, lot)
        ticket would keep total portfolio open-risk under the configured
        cap. Otherwise ``SKIP_PORTFOLIO_RISK``.

        This is intentionally decoupled from :meth:`evaluate` so the loop
        can call it AFTER lot sizing produces a viable lot, or (with
        prospective_lot=0) BEFORE sizing as a defensive early-exit when
        the account is already at the cap.
        """
        cap = float(self.cfg.risk.portfolio_max_open_risk_pct or 0.0)
        if cap <= 0:
            return RiskResult(RiskDecision.APPROVED)
        pip_value_per_lot = self.cfg.backtest.pip_value_per_lot
        current = self.portfolio_open_risk_pct(
            positions, account_balance, pip_value_per_lot,
        )
        if account_balance <= 0:
            return RiskResult(
                RiskDecision.SKIP_PORTFOLIO_RISK,
                actual_risk_pct=current,
                reason=(
                    f"account_balance <= 0; cannot evaluate portfolio cap"
                ),
            )
        prospective_add = (
            prospective_stop_pips * prospective_lot * pip_value_per_lot
            / account_balance
            if account_balance > 0 else 0.0
        )
        total = current + prospective_add
        # 1e-6 tolerance = 0.0001 percentage points; well below any
        # operator-meaningful threshold and safely above per-ticket
        # floating-point noise from (open_price - stop_loss) * 10_000
        # rounding on 4-decimal quotes.
        if total > cap + 1e-6:
            return RiskResult(
                RiskDecision.SKIP_PORTFOLIO_RISK,
                actual_risk_pct=total,
                reason=(
                    f"portfolio risk {total*100:.2f}% > cap {cap*100:.2f}% "
                    f"(current {current*100:.2f}% + new {prospective_add*100:.2f}%)"
                ),
            )
        return RiskResult(RiskDecision.APPROVED, actual_risk_pct=total)

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

    # ------------------------------------------------------------------
    # Crash-resilient persistence
    # ------------------------------------------------------------------

    def get_persist_state(self) -> dict:
        """Return a JSON-serialisable snapshot of the day-level risk state."""
        return {
            "day": self.state.day.isoformat() if self.state.day else None,
            "day_pnl": self.state.day_pnl,
            "halted_today": self.state.halted_today,
            "day_open_balance": self.state.day_open_balance,
        }

    def restore_from_persist_state(self, data: dict) -> None:
        """Restore day-level state from a persisted dict.

        The caller is responsible for the same-UTC-day check before
        calling this method; if today != the persisted day, do not call.
        """
        day_str = data.get("day")
        try:
            self.state.day = date.fromisoformat(day_str) if day_str else None
        except (ValueError, TypeError):
            self.state.day = None
        self.state.day_pnl = float(data.get("day_pnl", 0.0))
        self.state.halted_today = bool(data.get("halted_today", False))
        self.state.day_open_balance = float(data.get("day_open_balance", 0.0))
        log.info(
            "[STATE LOADED] risk_manager restored: day=%s day_pnl=%.2f "
            "halted=%s day_open_balance=%.2f",
            self.state.day, self.state.day_pnl,
            self.state.halted_today, self.state.day_open_balance,
        )
