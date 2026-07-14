from datetime import date, datetime

from agent.config import load_config
from agent.risk.manager import RiskDecision, RiskManager
from agent.types import Direction, Setup, Timeframe


def make_setup(stop_pips=30.0):
    return Setup(
        direction=Direction.LONG,
        timeframe=Timeframe.H1,
        detected_at=datetime(2024, 1, 1, 14, 0),
        detected_bar_index=100,
        entry=1.10000,
        stop=1.10000 - stop_pips * 0.0001,
        take_profit=1.10000 + 2 * stop_pips * 0.0001,
    )


def test_kill_switch_blocks(tmp_path):
    cfg = load_config()
    ks = tmp_path / "kill"
    ks.write_text("halt")
    rm = RiskManager(cfg, kill_switch_path=ks)
    res = rm.evaluate(make_setup(), 100.0, 0, datetime(2024, 1, 1, 14, 0))
    assert res.decision == RiskDecision.SKIP_KILL_SWITCH


def test_max_positions_blocks(tmp_path):
    cfg = load_config()
    rm = RiskManager(cfg, kill_switch_path=tmp_path / "nokill")
    res = rm.evaluate(make_setup(), 100.0, 1, datetime(2024, 1, 1, 14, 0))
    assert res.decision == RiskDecision.SKIP_MAX_POSITIONS


def test_approves_at_100_with_30_pip_stop(tmp_path):
    cfg = load_config()
    rm = RiskManager(cfg, kill_switch_path=tmp_path / "nokill")
    res = rm.evaluate(make_setup(30.0), 100.0, 0, datetime(2024, 1, 1, 14, 0))
    assert res.decision == RiskDecision.APPROVED
    assert res.lot_size == 0.01


def test_blocks_oversized_risk_at_100(tmp_path):
    cfg = load_config()
    rm = RiskManager(cfg, kill_switch_path=tmp_path / "nokill")
    res = rm.evaluate(make_setup(300.0), 100.0, 0, datetime(2024, 1, 1, 14, 0))
    assert res.decision == RiskDecision.SKIP_RISK_TOO_HIGH


def test_daily_dd_halts(tmp_path):
    cfg = load_config()
    rm = RiskManager(cfg, kill_switch_path=tmp_path / "nokill")
    rm.on_new_day(datetime(2024, 1, 1).date(), 100.0)
    rm.record_trade_pnl(-3.5)  # 3.5% loss > 3% halt
    res = rm.evaluate(make_setup(), 96.5, 0, datetime(2024, 1, 1, 14, 0))
    assert res.decision == RiskDecision.SKIP_DAILY_HALT


# ---------------------------------------------------------------------------
# Daily-DD-halt self-recovery decision + thrash guard
# ---------------------------------------------------------------------------


def _rm(tmp_path):
    return RiskManager(load_config(), kill_switch_path=tmp_path / "nokill")


def test_dd_rollover_holds_on_same_utc_day(tmp_path):
    rm = _rm(tmp_path)
    d = date(2026, 7, 10)
    dec = rm.evaluate_dd_halt_rollover(halt_date=d, today=d)
    assert dec.action == "hold"
    # No halt day recorded while still holding on the same day.
    assert rm.consecutive_dd_halt_days() == 0


def test_dd_rollover_clears_on_next_utc_day(tmp_path):
    rm = _rm(tmp_path)
    dec = rm.evaluate_dd_halt_rollover(
        halt_date=date(2026, 7, 10), today=date(2026, 7, 11))
    assert dec.action == "clear"
    assert dec.consecutive_days == 1
    assert rm.recovery.escalated is False


def test_dd_rollover_escalates_after_three_consecutive_days(tmp_path):
    rm = _rm(tmp_path)
    d1 = rm.evaluate_dd_halt_rollover(date(2026, 7, 10), date(2026, 7, 11))
    d2 = rm.evaluate_dd_halt_rollover(date(2026, 7, 11), date(2026, 7, 12))
    d3 = rm.evaluate_dd_halt_rollover(date(2026, 7, 12), date(2026, 7, 13))
    assert (d1.action, d2.action, d3.action) == ("clear", "clear", "escalate")
    assert d3.consecutive_days == 3
    assert rm.recovery.escalated is True
    # Once escalated it stays escalated (never silently re-arms again).
    d4 = rm.evaluate_dd_halt_rollover(date(2026, 7, 13), date(2026, 7, 14))
    assert d4.action == "escalate"


def test_dd_rollover_streak_resets_on_a_gap_day(tmp_path):
    rm = _rm(tmp_path)
    rm.evaluate_dd_halt_rollover(date(2026, 7, 1), date(2026, 7, 2))   # clear
    rm.evaluate_dd_halt_rollover(date(2026, 7, 2), date(2026, 7, 3))   # clear
    # A gap (no halt on the 3rd/4th); next halt is the 5th — streak restarts.
    dec = rm.evaluate_dd_halt_rollover(date(2026, 7, 5), date(2026, 7, 6))
    assert dec.action == "clear"
    assert dec.consecutive_days == 1


def test_recovery_state_round_trips_across_restart(tmp_path):
    rm = _rm(tmp_path)
    rm.evaluate_dd_halt_rollover(date(2026, 7, 10), date(2026, 7, 11))
    rm.evaluate_dd_halt_rollover(date(2026, 7, 11), date(2026, 7, 12))
    snap = rm.get_recovery_state()

    fresh = _rm(tmp_path)
    fresh.restore_recovery_state(snap)
    assert fresh.consecutive_dd_halt_days() == 2
    # A third consecutive day after restart still escalates — the counter
    # survived the "restart".
    dec = fresh.evaluate_dd_halt_rollover(date(2026, 7, 12), date(2026, 7, 13))
    assert dec.action == "escalate"
