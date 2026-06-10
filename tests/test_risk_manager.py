from datetime import datetime

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
