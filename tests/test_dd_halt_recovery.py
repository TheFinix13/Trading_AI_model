"""Daily-DD-halt self-recovery (auto-clear at UTC rollover + thrash guard).

Motivated by the real 2026-07-10 incident: EURUSD's 3%/day drawdown circuit
breaker tripped, the agent correctly closed the open position and wrote a
per-symbol ``kill.txt`` — then stayed blind for 50+ hours because the kill
file persisted until a human deleted it, and nobody did.

These tests pin the safety invariants of the fix:

1. The protective close is untouched (tested elsewhere); only the *persistence*
   of the blind halt changes.
2. A clean daily-DD auto-kill auto-clears at the next UTC day rollover.
3. A manually-created kill file (or the master kill file) is NEVER auto-cleared.
4. A non-DD auto-kill (catastrophe / consecutive-error) stays sticky.
5. Repeated DD halts (N days in a row) escalate to a sticky halt + alert.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from agent.config import load_config
from agent.live.config import LiveConfig
from agent.live.monitor import PositionMonitor
from agent.live.soft_stop import SoftStopConfig
from agent.risk.manager import RiskManager
from agent.utils import (
    is_daily_dd_auto_kill,
    kill_file_creation_utc_date,
    kill_switch_active,
)

# The EXACT kill-file content the agent wrote on 2026-07-10 (from the real
# incident log EURUSD_2026-07-10.log): reason line + UTC creation timestamp.
JUL10_KILL_CONTENT = (
    "Auto-kill: Daily DD halt: 3.0% (limit 3.0%)\n"
    "2026-07-10T02:15:16.856320+00:00\n"
)


def _make_monitor(tmp_path: Path, symbol: str = "EURUSD",
                  *, wire_recovery: bool = True) -> tuple[PositionMonitor, RiskManager]:
    broker = MagicMock()
    cfg = load_config()
    kill_file = tmp_path / symbol / "kill.txt"
    live = LiveConfig(symbol=symbol, kill_file=str(kill_file))
    notifier = MagicMock()
    notifier.notify_text = MagicMock()
    rm = RiskManager(cfg, kill_switch_path=tmp_path / "master_kill")
    mon = PositionMonitor(
        broker=broker, config=cfg, live_config=live, notifier=notifier,
        soft_stop_cfg=SoftStopConfig(enabled=False),
        dd_halt_recovery_cb=(rm.evaluate_dd_halt_rollover if wire_recovery else None),
    )
    return mon, rm


def _write_kill(mon: PositionMonitor, content: str) -> Path:
    p = Path(mon.live_config.kill_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# utils classification / creation-date helpers
# ---------------------------------------------------------------------------


def test_is_daily_dd_auto_kill_classification():
    assert is_daily_dd_auto_kill("Auto-kill: Daily DD halt: 3.0% (limit 3.0%)")
    # Case-insensitive.
    assert is_daily_dd_auto_kill("auto-kill: daily dd halt: 3.1%")
    # Non-DD auto-kills stay sticky.
    assert not is_daily_dd_auto_kill("Auto-kill: catastrophic loss 12%")
    assert not is_daily_dd_auto_kill("Auto-kill: 3 consecutive losses")
    # Manual / master kills stay sticky.
    assert not is_daily_dd_auto_kill("manual stop for maintenance")
    assert not is_daily_dd_auto_kill("Daily DD halt but no auto-kill prefix")
    assert not is_daily_dd_auto_kill(None)
    assert not is_daily_dd_auto_kill("")


def test_kill_file_creation_date_parses_iso_timestamp(tmp_path):
    p = tmp_path / "kill.txt"
    p.write_text(JUL10_KILL_CONTENT)
    assert kill_file_creation_utc_date(p) == _utc(2026, 7, 10).date()


def test_kill_file_creation_date_missing_file_is_none(tmp_path):
    assert kill_file_creation_utc_date(tmp_path / "nope.txt") is None


# ---------------------------------------------------------------------------
# THE REPLAY: 2026-07-10 EURUSD daily-DD halt auto-clears at next UTC midnight
# ---------------------------------------------------------------------------


def test_replay_jul10_eurusd_halt_holds_same_day_then_clears_at_rollover(tmp_path):
    mon, rm = _make_monitor(tmp_path, "EURUSD")
    kill = _write_kill(mon, JUL10_KILL_CONTENT)

    # Same UTC day (halt created 07-10 02:15) — the 3%/day budget has NOT
    # reset yet, so the halt must persist.
    action = mon._maybe_auto_clear_dd_halt(now=_utc(2026, 7, 10, 12, 0))
    assert action == "hold"
    assert kill.exists()
    assert kill_switch_active(kill) is True
    assert rm.consecutive_dd_halt_days() == 0

    # Next UTC midnight — auto-clear, re-arm, notify.
    action = mon._maybe_auto_clear_dd_halt(now=_utc(2026, 7, 11, 0, 0))
    assert action == "clear"
    assert not kill.exists()
    assert kill_switch_active(kill) is False
    # RE-ARMED notification fired exactly once.
    assert mon.notifier.notify_text.call_count == 1
    assert "RE-ARMED" in mon.notifier.notify_text.call_args[0][0]
    # The thrash counter recorded the halt day so a run can be detected.
    assert rm.consecutive_dd_halt_days() == 1


def test_replay_resumes_evaluating_after_clear(tmp_path):
    """After auto-clear the loop is no longer blinded: the per-symbol kill
    file (the exact gate the live loop checks) is gone, and the RiskManager
    approves a fresh setup on the new UTC day."""
    from agent.risk.manager import RiskDecision
    from agent.types import Direction, Setup, Timeframe

    mon, rm = _make_monitor(tmp_path, "EURUSD")
    kill = _write_kill(mon, JUL10_KILL_CONTENT)
    mon._maybe_auto_clear_dd_halt(now=_utc(2026, 7, 11, 0, 0))
    assert not kill.exists()

    setup = Setup(
        direction=Direction.LONG, timeframe=Timeframe.H4,
        detected_at=_utc(2026, 7, 11, 8, 0), detected_bar_index=100,
        entry=1.10000, stop=1.09700, take_profit=1.10600,
    )
    res = rm.evaluate(setup, account_balance=1000.0, open_positions=0,
                      now=_utc(2026, 7, 11, 8, 0))
    assert res.decision == RiskDecision.APPROVED


# ---------------------------------------------------------------------------
# Sticky cases: human stop + non-DD safety halts are NEVER auto-cleared
# ---------------------------------------------------------------------------


def test_manual_kill_file_never_auto_clears(tmp_path):
    mon, _rm = _make_monitor(tmp_path, "EURUSD")
    kill = _write_kill(mon, "manual: operator stop for the weekend\n")
    action = mon._maybe_auto_clear_dd_halt(now=_utc(2026, 7, 20, 0, 0))
    assert action is None
    assert kill.exists()
    mon.notifier.notify_text.assert_not_called()


def test_non_dd_auto_kill_stays_sticky(tmp_path):
    """Invariant 4: a catastrophe / broker-misread / consecutive-error
    auto-kill must NOT auto-clear — only the clean daily-DD case does."""
    mon, _rm = _make_monitor(tmp_path, "EURUSD")
    kill = _write_kill(
        mon,
        "Auto-kill: catastrophic loss 12.0% of balance\n"
        "2026-07-10T02:15:16+00:00\n",
    )
    action = mon._maybe_auto_clear_dd_halt(now=_utc(2026, 7, 15, 0, 0))
    assert action is None
    assert kill.exists()


def test_master_kill_file_is_never_touched(tmp_path):
    """Invariant 3: even if the MASTER kill file looks like a daily-DD
    auto-kill, the per-symbol recovery path never inspects or removes it."""
    mon, _rm = _make_monitor(tmp_path, "EURUSD")
    # No per-symbol kill file at all.
    master = mon.config.kill_switch_file
    Path(master).parent.mkdir(parents=True, exist_ok=True)
    Path(master).write_text(JUL10_KILL_CONTENT)
    try:
        action = mon._maybe_auto_clear_dd_halt(now=_utc(2026, 7, 20, 0, 0))
        assert action is None
        assert Path(master).exists()
    finally:
        Path(master).unlink(missing_ok=True)


def test_disabled_without_recovery_callback(tmp_path):
    """Legacy behaviour is preserved when no recovery cb is wired: a stale
    daily-DD kill file simply stays put (sticky-until-manual-delete)."""
    mon, _rm = _make_monitor(tmp_path, "EURUSD", wire_recovery=False)
    kill = _write_kill(mon, JUL10_KILL_CONTENT)
    action = mon._maybe_auto_clear_dd_halt(now=_utc(2026, 7, 20, 0, 0))
    assert action is None
    assert kill.exists()


def test_unparseable_creation_date_fails_safe(tmp_path):
    """If the creation day can't be established we must NOT guess a rollover
    — stay halted (fail safe)."""
    mon, _rm = _make_monitor(tmp_path, "EURUSD")
    # DD reason but no timestamp line and (forced) no usable mtime fallback:
    # patch the util to simulate an unresolvable date.
    import agent.live.monitor as monitor_mod
    kill = _write_kill(mon, "Auto-kill: Daily DD halt: 3.0% (limit 3.0%)\n")
    orig = monitor_mod.kill_file_creation_utc_date
    monitor_mod.kill_file_creation_utc_date = lambda _p: None
    try:
        action = mon._maybe_auto_clear_dd_halt(now=_utc(2026, 7, 20, 0, 0))
    finally:
        monitor_mod.kill_file_creation_utc_date = orig
    assert action is None
    assert kill.exists()


# ---------------------------------------------------------------------------
# Thrash guard: N consecutive DD-halt days escalate to a sticky halt + page
# ---------------------------------------------------------------------------


def test_thrash_guard_escalates_after_three_days(tmp_path):
    mon, rm = _make_monitor(tmp_path, "EURUSD")
    # Pre-seed two prior consecutive DD-halt days (as if already re-armed).
    rm.restore_recovery_state({"halt_dates": ["2026-07-10", "2026-07-11"],
                               "escalated": False})
    # Third consecutive halt (created 07-12) reaches rollover on 07-13.
    kill = _write_kill(
        mon,
        "Auto-kill: Daily DD halt: 3.2% (limit 3.0%)\n"
        "2026-07-12T05:00:00+00:00\n",
    )
    action = mon._maybe_auto_clear_dd_halt(now=_utc(2026, 7, 13, 0, 0))
    assert action == "escalate"
    # File is NOT removed — it is converted to a sticky halt.
    assert kill.exists()
    assert is_daily_dd_auto_kill(kill.read_text()) is False
    assert kill_switch_active(kill) is True
    # Operator was paged.
    assert mon.notifier.notify_text.call_count == 1
    assert "STICKY HALT" in mon.notifier.notify_text.call_args[0][0]
    assert rm.recovery.escalated is True

    # A later cycle finds a now-sticky file and does nothing.
    mon.notifier.notify_text.reset_mock()
    action2 = mon._maybe_auto_clear_dd_halt(now=_utc(2026, 7, 14, 0, 0))
    assert action2 is None
    assert kill.exists()
    mon.notifier.notify_text.assert_not_called()
