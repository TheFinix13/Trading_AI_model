"""Post-loss cooldown / no-revenge guard.

The June 2026 account post-mortem (`docs/reviews/2026-06-01_week_review.md`)
found the account was blown twice by the same human reflex: a loss, then an
immediate, oversized, structureless re-entry to "win it back". The codebase had
account-level gates (daily DD halt, max positions, kill switch) but nothing that
reacts to the *sequence* of recent outcomes.

This module adds that missing layer as a small, pure-Python state machine that
is trivial to unit-test and is consulted by the live loop before every entry:

  * **Cooldown** — after any loss, no new entry for ``cooldown_minutes`` (or
    ``cooldown_bars`` in bar-driven harnesses). Kills the instant revenge
    re-entry.
  * **Size reduction** — after a loss, the next trade's risk is multiplied by
    ``loss_risk_multiplier`` (default 0.5 = halved) until a win restores it.
    Stops "sizing up to win it back".
  * **Consecutive-loss circuit breaker** — after ``max_consecutive_losses`` in a
    row, halt new entries for the rest of the session/day.
  * **Stop-out halt** — a single catastrophic loss (>= ``catastrophic_loss_frac``
    of balance, or an exit the broker flagged as a margin stop-out) halts the
    session immediately. This is what would have stopped the Jun 2 evening
    revenge cluster after the −$124 margin stop-out.

State is keyed on the UTC trading day and on trade *outcomes only* — never on
balance — so re-depositing into a blown account does NOT reset a halt (the
"re-deposit guard" the post-mortem asked for).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)


@dataclass
class GuardConfig:
    """Tunable thresholds for the post-loss / no-revenge guard."""

    enabled: bool = True
    # Cooldown after a loss. Both are honoured; whichever is supplied at the
    # call site applies (live uses wall-clock minutes, bar harnesses use bars).
    cooldown_minutes: float = 60.0
    cooldown_bars: int = 2
    # Risk multiplier applied to the next trade(s) after a loss, until a win.
    loss_risk_multiplier: float = 0.5
    # Halt new entries for the rest of the session after this many losses in a row.
    max_consecutive_losses: int = 3
    # A single loss this large (fraction of balance) halts the session — models
    # a margin stop-out / account-killer trade.
    catastrophic_loss_frac: float = 0.10
    halt_on_stop_out: bool = True


@dataclass
class GuardDecision:
    """Result of a pre-trade guard check."""

    allowed: bool
    code: str = "ok"  # ok | cooldown | circuit_breaker | stop_out_halt | disabled
    reason: str = ""


class PostLossGuard:
    """Stateful post-loss cooldown / size-reduction / circuit-breaker guard."""

    def __init__(self, config: GuardConfig | None = None):
        self.cfg = config or GuardConfig()
        self.consecutive_losses = 0
        self.size_multiplier = 1.0
        self.cooldown_until: datetime | None = None
        self.cooldown_until_bar: int | None = None
        self.session_halted = False
        self.halt_reason = ""
        self._day: date | None = None

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    def _maybe_roll_day(self, now: datetime | None) -> None:
        """Reset session state on a new UTC day. A new calendar day clears the
        circuit breaker and cooldown; it never clears mid-session on a deposit."""
        if now is None:
            return
        today = now.date()
        if self._day is None:
            self._day = today
            return
        if today != self._day:
            self._day = today
            self.consecutive_losses = 0
            self.size_multiplier = 1.0
            self.cooldown_until = None
            self.cooldown_until_bar = None
            self.session_halted = False
            self.halt_reason = ""

    # ------------------------------------------------------------------
    # Outcome recording
    # ------------------------------------------------------------------

    def register_close(
        self,
        *,
        pnl: float,
        r_multiple: float = 0.0,
        exit_reason: str = "",
        now: datetime | None = None,
        bar_index: int | None = None,
        account_balance: float | None = None,
    ) -> None:
        """Update guard state from a just-closed trade.

        A loss starts the cooldown, halves the next trade's risk, and counts
        toward the circuit breaker. A win clears the loss streak and restores
        full size. A scratch (pnl == 0) is neutral.
        """
        if not self.cfg.enabled:
            return
        self._maybe_roll_day(now)

        if pnl < 0:
            self.consecutive_losses += 1
            self.size_multiplier = self.cfg.loss_risk_multiplier

            if now is not None and self.cfg.cooldown_minutes > 0:
                self.cooldown_until = now + timedelta(minutes=self.cfg.cooldown_minutes)
            if bar_index is not None and self.cfg.cooldown_bars > 0:
                self.cooldown_until_bar = bar_index + self.cfg.cooldown_bars

            reason_l = (exit_reason or "").lower()
            is_stop_out = "stop_out" in reason_l or "stopout" in reason_l or "margin" in reason_l
            if (account_balance and account_balance > 0
                    and abs(pnl) >= self.cfg.catastrophic_loss_frac * account_balance):
                is_stop_out = True
            if self.cfg.halt_on_stop_out and is_stop_out:
                self.session_halted = True
                self.halt_reason = (
                    f"catastrophic loss {pnl:+.2f} ({abs(pnl) / account_balance * 100:.0f}% of balance)"
                    if account_balance else f"stop-out exit ({exit_reason})"
                )
                log.warning("Post-loss guard: session HALTED — %s", self.halt_reason)

            if self.consecutive_losses >= self.cfg.max_consecutive_losses:
                self.session_halted = True
                self.halt_reason = f"{self.consecutive_losses} consecutive losses"
                log.warning("Post-loss guard: circuit breaker — %s; halting session",
                            self.halt_reason)
            else:
                log.info(
                    "Post-loss guard armed: loss #%d this session, next risk x%.2f, "
                    "cooldown until %s",
                    self.consecutive_losses, self.size_multiplier,
                    self.cooldown_until.strftime("%H:%M UTC") if self.cooldown_until else "n/a",
                )
        elif pnl > 0:
            if self.consecutive_losses or self.size_multiplier != 1.0:
                log.info("Post-loss guard: win — loss streak reset, full size restored")
            self.consecutive_losses = 0
            self.size_multiplier = 1.0
        # pnl == 0 (scratch / breakeven): neutral, leave state unchanged.

    # ------------------------------------------------------------------
    # Pre-trade check
    # ------------------------------------------------------------------

    def pre_trade_check(
        self, now: datetime | None = None, bar_index: int | None = None
    ) -> GuardDecision:
        """Decide whether a new entry is allowed right now."""
        if not self.cfg.enabled:
            return GuardDecision(True, "disabled", "guard disabled")
        self._maybe_roll_day(now)

        if self.session_halted:
            return GuardDecision(
                False, "circuit_breaker" if "consecutive" in self.halt_reason else "stop_out_halt",
                f"session halted for the day ({self.halt_reason})",
            )

        if now is not None and self.cooldown_until is not None and now < self.cooldown_until:
            mins = (self.cooldown_until - now).total_seconds() / 60.0
            return GuardDecision(
                False, "cooldown",
                f"post-loss cooldown active — {mins:.0f} min remaining "
                f"(until {self.cooldown_until.strftime('%H:%M UTC')})",
            )

        if (bar_index is not None and self.cooldown_until_bar is not None
                and bar_index < self.cooldown_until_bar):
            return GuardDecision(
                False, "cooldown",
                f"post-loss cooldown active — {self.cooldown_until_bar - bar_index} bar(s) remaining",
            )

        return GuardDecision(True, "ok", "")

    # ------------------------------------------------------------------
    # Risk scaling + introspection
    # ------------------------------------------------------------------

    def risk_multiplier(self) -> float:
        """Current risk multiplier (1.0 normally, < 1.0 after a loss)."""
        return self.size_multiplier if self.cfg.enabled else 1.0

    def status(self) -> dict:
        return {
            "enabled": self.cfg.enabled,
            "consecutive_losses": self.consecutive_losses,
            "size_multiplier": self.size_multiplier,
            "session_halted": self.session_halted,
            "halt_reason": self.halt_reason,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
        }
