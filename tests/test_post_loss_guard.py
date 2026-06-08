"""Tests for the post-loss cooldown / no-revenge guard."""
from datetime import datetime, timedelta, timezone

from agent.risk.post_loss_guard import GuardConfig, PostLossGuard


def _now() -> datetime:
    return datetime(2026, 6, 2, 6, 31, tzinfo=timezone.utc)


def test_loss_starts_time_cooldown_blocking_new_entry():
    g = PostLossGuard(GuardConfig(cooldown_minutes=60.0))
    t = _now()
    assert g.pre_trade_check(t).allowed  # clean slate
    g.register_close(pnl=-10.0, now=t)
    # 30 min later still blocked
    d = g.pre_trade_check(t + timedelta(minutes=30))
    assert not d.allowed
    assert d.code == "cooldown"
    # after 60 min cooldown clears
    assert g.pre_trade_check(t + timedelta(minutes=61)).allowed


def test_bar_cooldown_blocks_next_n_bars():
    g = PostLossGuard(GuardConfig(cooldown_bars=2, cooldown_minutes=0.0))
    g.register_close(pnl=-5.0, bar_index=100)
    assert not g.pre_trade_check(bar_index=100).allowed
    assert not g.pre_trade_check(bar_index=101).allowed
    assert g.pre_trade_check(bar_index=102).allowed


def test_risk_halved_after_loss_restored_after_win():
    g = PostLossGuard(GuardConfig(loss_risk_multiplier=0.5))
    t = _now()
    assert g.risk_multiplier() == 1.0
    g.register_close(pnl=-5.0, now=t)
    assert g.risk_multiplier() == 0.5
    # A loss does not compound below the configured multiplier.
    g.register_close(pnl=-5.0, now=t)
    assert g.risk_multiplier() == 0.5
    g.register_close(pnl=+12.0, now=t)
    assert g.risk_multiplier() == 1.0


def test_consecutive_loss_circuit_breaker_halts_session():
    g = PostLossGuard(GuardConfig(max_consecutive_losses=3, cooldown_minutes=0.0))
    t = _now()
    g.register_close(pnl=-1.0, now=t)
    g.register_close(pnl=-1.0, now=t)
    assert g.pre_trade_check(t).allowed  # 2 losses, not yet halted
    g.register_close(pnl=-1.0, now=t)
    d = g.pre_trade_check(t)
    assert not d.allowed
    assert d.code == "circuit_breaker"


def test_catastrophic_loss_halts_session_immediately():
    # The Jun 2 −$124 on a ~$124 account: one loss > 10% of balance halts.
    g = PostLossGuard(GuardConfig(catastrophic_loss_frac=0.10))
    t = _now()
    g.register_close(pnl=-124.0, now=t, account_balance=124.0)
    d = g.pre_trade_check(t)
    assert not d.allowed
    assert d.code == "stop_out_halt"


def test_stop_out_exit_reason_halts_session():
    g = PostLossGuard(GuardConfig(halt_on_stop_out=True))
    t = _now()
    g.register_close(pnl=-5.0, exit_reason="margin stop_out", now=t)
    assert not g.pre_trade_check(t).allowed


def test_redeposit_does_not_reset_halt_same_day():
    # Re-funding a blown account must NOT clear the halt within the same session.
    g = PostLossGuard(GuardConfig(catastrophic_loss_frac=0.10))
    t = _now()
    g.register_close(pnl=-100.0, now=t, account_balance=100.0)
    assert g.session_halted
    # Simulate a later same-day re-deposit + attempt (no state input is balance).
    later = t + timedelta(hours=9)
    assert not g.pre_trade_check(later).allowed


def test_new_day_resets_session_state():
    g = PostLossGuard(GuardConfig(catastrophic_loss_frac=0.10))
    t = _now()
    g.register_close(pnl=-100.0, now=t, account_balance=100.0)
    assert not g.pre_trade_check(t).allowed
    next_day = t + timedelta(days=1)
    d = g.pre_trade_check(next_day)
    assert d.allowed
    assert g.risk_multiplier() == 1.0
    assert g.consecutive_losses == 0


def test_disabled_guard_allows_everything():
    g = PostLossGuard(GuardConfig(enabled=False))
    t = _now()
    g.register_close(pnl=-100.0, now=t, account_balance=100.0)
    assert g.pre_trade_check(t).allowed
    assert g.risk_multiplier() == 1.0


def test_scratch_is_neutral():
    g = PostLossGuard(GuardConfig())
    t = _now()
    g.register_close(pnl=-1.0, now=t)
    assert g.consecutive_losses == 1
    g.register_close(pnl=0.0, now=t)  # breakeven scratch
    assert g.consecutive_losses == 1  # unchanged
